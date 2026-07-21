# Scar Log

Group 7 — `devops-g7-`.

---

## Scar 1: intermittent 504 on `/greet-service-b` under desired count 2

| Field | Entry |
|---|---|
| Symptom | `curl http://<alb-dns>/greet-service-b` succeeded on the first call after Service C came online, then returned `504 Gateway Timeout` (~5.5s) on the next two calls, repeating intermittently on subsequent calls. `/health` reported all dependencies `ok` throughout — the failure was not visible as a health-check failure. |
| First hypothesis | Missing security-group rule for the `service-c → service-a` callback path (port 3001), since that rule was known to be pending on Mercylin's `service-c-sg` being created. |
| Evidence | `describe-security-groups` on `devops-g7-service-a-sg` showed the rule already present (both the ALB and `service-c-sg` as peers on port 3001 — AWS had merged them into a single permission block, which the hypothesis-forming query initially missed by only reading the first `UserIdGroupPairs` entry). Ruled out the SG hypothesis. Pulled CloudWatch Logs for both running service-a tasks (`60adb8ef`, `d98cadd3`) and cross-referenced timestamps: a request that succeeded had its `POST /greeting-rcvd` logged on the *same* task that received the original `GET /greet-service-b`. A request that timed out had its `POST /greeting-rcvd` logged on the *other* task. |
| Actual cause | `service_a.py` stores per-request callback coordination (`_pending_callbacks`, a `threading.Event` keyed by `request_id`) in a plain in-process Python dict. This works when service-a runs as a single instance (true in the local docker-compose setup) but breaks under Fargate's required desired count of 2: Service Connect load-balances the callback POST across both replicas, and roughly half the time it lands on a task that never issued the original request, so that task's dict has no matching entry. The `/greeting-rcvd` handler doesn't error in that case (`event = _pending_callbacks.get(request_id)` is `None`-safe) — it just silently drops the signal, and the original task's `event.wait(timeout=5)` times out. |
| Repair | Replaced the in-process `_pending_callbacks` dict + `threading.Event` with a shared DynamoDB table (`devops-g7-service-a-callbacks`, on-demand billing, TTL on `expires_at` for automatic cleanup). `/greeting-rcvd` now writes an item keyed by `request_id` instead of setting a local event; `/greet-service-b` polls the table (`wait_for_callback()`, 0.2s interval, same 5s budget as before) instead of waiting on a local event, and deletes the item once consumed. `devops-g7-service-a-task-role` was granted `PutItem`/`GetItem`/`DeleteItem` scoped to only that table's ARN. Verified locally against the real table (not mocked) before deploying: `POST /greeting-rcvd` wrote a real item, confirmed via `aws dynamodb get-item`; `wait_for_callback()` found it, returned `True`, and deleted it, confirmed by a follow-up `get-item` returning empty. Unit tests (`test_service_a.py`) rewritten to mock `callbacks_table` instead of the removed dict; all 16 pass. |
| Prevention | Any service design using in-process state for cross-request coordination must either run at a fixed desired count of 1, or move that state to something external and shared (DynamoDB, ElastiCache, etc.) before scaling horizontally. More generally: behavior that is correct in a single-instance local environment (docker-compose) is not guaranteed to hold once the same service is horizontally scaled behind a load balancer — this is exactly the kind of gap Phase 1's dependency/failure-prediction exercise is meant to surface, and in this case the local environment could not have caught it since docker-compose never runs more than one service-a container. |

**Why this is a strong scar, not just a bug:** the AWS-side configuration (security groups, Service
Connect, ALB, IAM) is entirely correct — this was verified directly via `describe-security-groups`
and cross-task CloudWatch log correlation before concluding the cause was architectural. The failure
is deterministic given the log evidence (which task received the callback vs. which task was
waiting), not flaky infrastructure.
