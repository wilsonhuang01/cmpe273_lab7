# CMPE 273 Lab 7 — Versioned Order Processing

## 1. Run the program

```bash
python3 demo.py
```

## 2. Event and state model

Each event includes `order_id`, `version`, and `status`, for example:

```json
{"order_id": "order-1", "version": 2, "status": "SHIPPED"}
```

Creating an order by acquiring its first worker token establishes version 0.
The two event versions represent these transitions:

```text
CREATED (version 0) -> PAID (version 1) -> SHIPPED (version 2)
```

`order_processing.py` owns the shared order state. `process_event()` checks the
worker token, ignores duplicates, and stores future events in a pending buffer.
It applies only the next consecutive version, draining the buffer when a gap is
filled. The `(order_id, version)` pair identifies a duplicate; status must match
the lifecycle above, so conflicting version/status pairs are rejected.

## 3. Correct ordering and duplicate handling

The first scenario in `demo.py` delivers version **2**, then **1**, then **2 again**.
Captured output:

```text
=== Out-of-order delivery: 2, 1, 2 again ===
deliver order_id=order-1 version=2 status=SHIPPED
result=pending applied_versions=[]
{"order_id": "order-1", "version": 0, "status": "CREATED", "fencing_token": 1, "pending_versions": [2], "missing_versions": [1], "applied_versions": []}
deliver order_id=order-1 version=1 status=PAID
result=applied applied_versions=[1, 2]
{"order_id": "order-1", "version": 2, "status": "SHIPPED", "fencing_token": 1, "pending_versions": [], "missing_versions": [], "applied_versions": [1, 2]}
deliver order_id=order-1 version=2 status=SHIPPED
result=duplicate applied_versions=[]
{"order_id": "order-1", "version": 2, "status": "SHIPPED", "fencing_token": 1, "pending_versions": [], "missing_versions": [], "applied_versions": [1, 2]}
```

![out of order](screenshots/1%20out%20of%20order.png)

Version 2 initially waits. When version 1 arrives, the processor applies `PAID`
before `SHIPPED`. The final delivery is a duplicate: the applied history remains
`[1, 2]` and state does not change. Repeating an event while it is still pending
also has no effect, as verified by the tests.

## 4. Missing-event case

A separate order receives only version 2:

```text
=== Missing event: only version 2 arrives ===
deliver order_id=order-missing version=2 status=SHIPPED
result=pending applied_versions=[]
{"order_id": "order-missing", "version": 0, "status": "CREATED", "fencing_token": 1, "pending_versions": [2], "missing_versions": [1], "applied_versions": []}
```

![missing](screenshots/2%20missing.png)

The order stays `CREATED` at version 0. Version 2 is recorded as pending and
version 1 is explicitly reported missing. Waiting means retaining the event
until the missing version arrives; the program does not block or invent an
event to skip the gap. This scenario deliberately leaves the gap unresolved.

## 5. Stale-worker rejection

Worker A acquires token 1 and applies version 1. Worker B then acquires token 2
for the same order. A resumes with its old token and attempts version 2, followed
by B attempting the same update with its current token:

```text
=== Stale worker: newer worker takes over ===
worker-A token=1
deliver order_id=order-fenced version=1 status=PAID
result=applied applied_versions=[1]
{"order_id": "order-fenced", "version": 1, "status": "PAID", "fencing_token": 1, "pending_versions": [], "missing_versions": [], "applied_versions": [1]}
worker-B token=2
deliver order_id=order-fenced version=2 status=SHIPPED
result=rejected_stale_worker token=1 current_token=2
{"order_id": "order-fenced", "version": 1, "status": "PAID", "fencing_token": 2, "pending_versions": [], "missing_versions": [], "applied_versions": [1]}
deliver order_id=order-fenced version=2 status=SHIPPED
result=applied applied_versions=[2]
{"order_id": "order-fenced", "version": 2, "status": "SHIPPED", "fencing_token": 2, "pending_versions": [], "missing_versions": [], "applied_versions": [1, 2]}
```

![stale](screenshots/3%20stale.png)

Tokens increase per order and come from `acquire_worker()`. Issuing a new token
immediately revokes the previous one. The shared processor rejects an old token
before changing state or buffering anything, even if the event would otherwise
be valid. B's current token successfully advances t-he order to `SHIPPED`.

## Reflection

Timestamps alone are not enough to guarantee correct event ordering in a distributed 
system because programs are often run on different physical machines. This can introduce a difference in timestamp between two machines, for example, a machine may
be 50 ms behind, and two requests sent by these two machines to another machine may be out of order. If the program only uses timestamps in the request parameter, unexpected behavior may occur. Using other mechanisms like fencing tokens and version ensure more consistency and correctness across a distributed system.
