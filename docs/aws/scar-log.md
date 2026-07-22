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

---

## Scar 2: task-definition file changes silently never deployed

| Field | Entry |
|---|---|
| Symptom | `ecs/service-a-task-definition.json` was edited to add `AWS_REGION` and `CALLBACKS_TABLE_NAME` (part of the Scar 1 repair). The app worked correctly after deployment, so this went unnoticed until manually opening task definition revision 7 in the console and finding "Environment variables (1)" — only `BIND_HOST` — despite the file in the repo clearly listing three. |
| First hypothesis | None formed yet at discovery — this was caught by directly inspecting the console rather than by a failure symptom, since the running application showed no visible error. |
| Evidence | `aws ecs describe-task-definition` compared across revisions 1, 6, and 7 all showed only `BIND_HOST` in `containerDefinitions[0].environment`, confirming the console wasn't a display artifact. |
| Actual cause | The CodePipeline ECS deploy action was configured with only `ClusterName`/`ServiceName`/`FileName: imagedefinitions.json` — no task-definition template artifact. In that mode, the deploy action clones whatever task definition the service is *currently* running and patches only the container image; it never re-reads `ecs/service-a-task-definition.json` from the repo. The only time that file's contents were actually registered was the very first manual `aws ecs register-task-definition` call, made before `AWS_REGION`/`CALLBACKS_TABLE_NAME` were even added to the file. Every automated deploy since (triggered by any merge, including ones from Mercylin's unrelated B/C work retriggering A's pipeline) cloned that original environment block forward, unchanged. The app still worked because `os.environ.get(...)` fallback defaults in the code happened to match the real values — masking the drift functionally while it was still present structurally. |
| Repair | Rendered the current `ecs/service-a-task-definition.json` (all 3 env vars) with the actually-deployed image tag preserved, registered it as revision 8, and pointed the service at it directly via `aws ecs update-service --task-definition`. Verified: revision 8's environment block now has all 3 variables; 5/5 live `/greet-service-b` calls succeeded post-deploy; `/version` still correct. This is a one-time correction, not a structural fix — the next automated deploy will clone revision 8 forward correctly, but *only* because revision 8 is now correct; any future manual edit to the JSON file would silently fail to deploy again, the same way. |
| Prevention | The durable fix is to make the pipeline actually deploy from the checked-in file, e.g. have CodeBuild render `ecs/service-a-task-definition.json` (substituting the new image URI) as a build artifact, and configure the ECS deploy action with a `TaskDefinitionTemplateArtifact`/`TaskDefinitionTemplatePath` instead of relying on clone-and-patch. Not implemented here due to time, but documented as the correct production pattern. More generally: a config file changing in a repo is not evidence it changed in production — this class of drift is invisible unless someone diffs the deployed resource against the file, which is exactly how this was caught. |

**Why this is a strong scar:** it was found by verification, not failure — the running system gave
no error signal at all, since the code's fallback defaults happened to match the intended values.
That's arguably more valuable to flag than a loud failure: it demonstrates the checked-in
task-definition file and CI/CD pipeline can drift apart silently, and that "the app still works" is
not sufficient evidence that a config change actually deployed.
