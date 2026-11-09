"""In-memory simulation of ordered events and fenced order workers."""

from dataclasses import dataclass, field
from threading import Lock


STATUSES = {0: "CREATED", 1: "PAID", 2: "SHIPPED"}


@dataclass(frozen=True)
class OrderEvent:
    order_id: str
    version: int
    status: str

    def __post_init__(self):
        if not isinstance(self.order_id, str) or not self.order_id.strip():
            raise ValueError("order_id must be a nonempty string")
        if type(self.version) is not int or self.version not in (1, 2):
            raise ValueError("event version must be 1 or 2")
        if self.status != STATUSES[self.version]:
            raise ValueError("status does not match the versioned order lifecycle")


class StaleWorkerError(Exception):
    """The worker no longer holds the current fencing token."""


@dataclass
class _Order:
    version: int = 0
    status: str = "CREATED"
    fencing_token: int = 0
    pending: dict = field(default_factory=dict)
    history: list = field(default_factory=list)


@dataclass(frozen=True)
class DeliveryResult:
    outcome: str
    applied_versions: tuple = ()


class OrderProcessor:
    """Keep each order's state, pending events, and current worker token together.

    The lock makes token allocation and each check-and-update atomic within
    this process. A new token immediately invalidates all earlier workers.
    """

    def __init__(self):
        self._orders = {}
        self._lock = Lock()

    def acquire_worker(self, order_id):
        """Create the order if needed and issue its next fencing token."""
        if not isinstance(order_id, str) or not order_id.strip():
            raise ValueError("order_id must be a nonempty string")
        with self._lock:
            order = self._orders.setdefault(order_id, _Order())
            order.fencing_token += 1
            return order.fencing_token

    def process_event(self, event, fencing_token):
        """Buffer gaps, apply contiguous versions, and ignore redeliveries."""
        if not isinstance(event, OrderEvent):
            raise TypeError("event must be an OrderEvent")
        with self._lock:
            order = self._orders[event.order_id]
            # Fence before even deduplicating or buffering a stale delivery.
            if type(fencing_token) is not int or fencing_token != order.fencing_token:
                raise StaleWorkerError(
                    f"token={fencing_token} current_token={order.fencing_token}"
                )
            if event.version <= order.version or event.version in order.pending:
                return DeliveryResult("duplicate")

            order.pending[event.version] = event
            applied = []
            while order.version + 1 in order.pending:
                next_event = order.pending.pop(order.version + 1)
                order.version = next_event.version
                order.status = next_event.status
                order.history.append(next_event)
                applied.append(next_event.version)
            return DeliveryResult("applied" if applied else "pending", tuple(applied))

    def snapshot(self, order_id):
        """Return a detached, JSON-friendly view for logs and assertions."""
        with self._lock:
            order = self._orders[order_id]
            missing = []
            if order.pending:
                missing = [
                    version for version in range(order.version + 1, max(order.pending))
                    if version not in order.pending
                ]
            return {
                "order_id": order_id,
                "version": order.version,
                "status": order.status,
                "fencing_token": order.fencing_token,
                "pending_versions": sorted(order.pending),
                "missing_versions": missing,
                "applied_versions": [event.version for event in order.history],
            }
