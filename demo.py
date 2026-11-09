"""Run deterministic ordering, missing-event, and stale-worker scenarios."""

import json

from order_processing import OrderEvent, OrderProcessor, StaleWorkerError


def deliver(processor, event, token):
    print(f"deliver order_id={event.order_id} version={event.version} status={event.status}")
    try:
        result = processor.process_event(event, token)
        print(f"result={result.outcome} applied_versions={list(result.applied_versions)}")
    except StaleWorkerError as error:
        print(f"result=rejected_stale_worker {error}")
    print(json.dumps(processor.snapshot(event.order_id)))


def main():
    processor = OrderProcessor()

    print("=== Out-of-order delivery: 2, 1, 2 again ===")
    token = processor.acquire_worker("order-1")
    deliver(processor, OrderEvent("order-1", 2, "SHIPPED"), token)
    deliver(processor, OrderEvent("order-1", 1, "PAID"), token)
    deliver(processor, OrderEvent("order-1", 2, "SHIPPED"), token)

    print("\n=== Missing event: only version 2 arrives ===")
    token = processor.acquire_worker("order-missing")
    deliver(processor, OrderEvent("order-missing", 2, "SHIPPED"), token)

    print("\n=== Stale worker: newer worker takes over ===")
    old_token = processor.acquire_worker("order-fenced")
    print(f"worker-A token={old_token}")
    deliver(processor, OrderEvent("order-fenced", 1, "PAID"), old_token)
    new_token = processor.acquire_worker("order-fenced")
    print(f"worker-B token={new_token}")
    # A still tries to finish its work after B takes ownership.
    deliver(processor, OrderEvent("order-fenced", 2, "SHIPPED"), old_token)
    deliver(processor, OrderEvent("order-fenced", 2, "SHIPPED"), new_token)


if __name__ == "__main__":
    main()
