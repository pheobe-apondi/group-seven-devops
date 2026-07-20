# Phase 1 — Dependency Graph, Failure Predictions, Traffic Contracts

**Group:** 7 &nbsp;|&nbsp; **Region:** eu-west-2 (London, assigned per-group) &nbsp;|&nbsp; **Naming prefix:** `devops-g7-`


---

## 0. Architecture changes: docker-compose → AWS

The following technical differences from the current `docker-compose` setup inform the dependency
graph and traffic contracts below.

- **Nginx is replaced by the ALB.** Nginx currently strips the `/service-a/` prefix before proxying
  to service-a (`nginx/docker.conf:31-39`), so `service_a.py` only receives root paths (`/health`,
  `/greet-service-b`, `/metrics`). The ALB does not perform path rewriting, so the public URL on AWS
  is `http://<alb-dns>/greet-service-b`, not `http://<alb-dns>/service-a/greet-service-b`. The ALB
  target group health check points at `/health`.
- **Service-to-service hostnames are unchanged.** `service_a.py` calls `http://service-b:3002/greet`
  directly rather than via the `SERVICE_B_URL` environment variable set in `docker-compose.yml` (see
  `services/service-a/service_a.py:129`). The ECS Service Connect discovery name for service-b must
  therefore be exactly `service-b` (and service-c exactly `service-c`) for the existing code to work
  without modification.
- **The observability stack is out of scope.** Prometheus, Grafana, Jaeger, and Alertmanager exist
  only in the dev `docker-compose.yml`, not `docker-compose.prod.yml`, and are not part of this
  assignment's requirements. CloudWatch Logs is the only required logging destination.
- **`BIND_HOST=0.0.0.0` is already the container default** (`service_a.py:231` binds to `0.0.0.0`
  unless `--loopback` is passed, which the Dockerfile CMD does not do), satisfying the assignment's
  "does the application listen on 0.0.0.0" requirement (section 2.2) with no code change.

---

## 1.1 Dependency graph

```
IAM identity (per-member IAM user, London-region-scoped permissions)
    │
Assigned Region: eu-west-2
    │
Default VPC (eu-west-2 default VPC)
    │
Default subnets in two AZs (eu-west-2a, eu-west-2b)
    │
Security groups
    devops-g7-alb-sg
    devops-g7-service-a-sg
    devops-g7-service-b-sg
    devops-g7-service-c-sg
    │
ECR repositories
    devops-g7-service-a
    devops-g7-service-b
    devops-g7-service-c
    │
ECS cluster: devops-g7-cluster
    │
Task definitions
    devops-g7-service-a-task
    devops-g7-service-b-task
    devops-g7-service-c-task
    │
ECS services
    devops-g7-service-a-svc (desired count 2)
    devops-g7-service-b-svc (desired count 1)
    devops-g7-service-c-svc (desired count 1)
    │
Service Connect namespace: g7.internal
    (service names: service-a, service-b, service-c)
    │
Target group: devops-g7-service-a-tg  (type: ip, port 3001, health check /health)
    │
Application Load Balancer: devops-g7-alb  (internet-facing, listener :80)
    │
DNS: ALB's auto-generated DNS name (no Route 53 zone required for this lab)
```

Attached at every layer from ECS cluster downward:
- **CloudWatch Logs** — one log group per service, e.g. `/ecs/devops-g7-service-a`
- **CodeConnections** — one GitHub connection, owned by the platform role, reused by all 3 pipelines
- **CodePipeline** — one pipeline per service
- **CodeBuild** — one project per service, using `buildspecs/service-a.yml` etc.
- **ECS deploy action** — registers new task-definition revision, triggers rolling deployment

---

## 1.2 Dependency questions

| Question | Team answer |
|---|---|
| What must exist before a Fargate task can start? | Cluster, task definition (valid execution role + image URI), subnets, security group. Execution role must have `AmazonECSTaskExecutionRolePolicy` (or equivalent scoped policy) so ECS can call `ecr:GetAuthorizationToken`/`GetDownloadUrlForLayer`/`BatchGetImage` and `logs:CreateLogStream`/`PutLogEvents`. |
| What must exist before ECS can pull an image? | ECR repository with at least one pushed, immutable-tagged image; execution role with ECR pull permissions; outbound network path from the subnet (default subnet + public IP, since this lab does not use a NAT gateway or VPC endpoint). |
| What must exist before the ALB can route traffic? | ALB, listener (:80), target group (type `ip`, correct port), at least one registered target that passes its health check, and a security-group path from the ALB SG to the target's SG on the app port. |
| What depends on the named container port? | Service Connect port-mapping name must match what's referenced in the Service Connect configuration; the target group's port must match the container's actual listening port (3001 for service-a). Get the name wrong and Service Connect silently fails to route; get the port wrong and ECS deploys a task the ALB will mark unhealthy. |
| Which resources survive task replacement? | ECR images, task-definition revisions, ECS service, cluster, ALB, target group, security groups, CloudWatch log group, Service Connect namespace/config. Only the task ENI/IP and the specific task ID are ephemeral. |
| Which resources generate cost while idle? | Fargate tasks (vCPU/memory-hours regardless of traffic), the ALB (hourly + LCU), CloudWatch Logs storage/ingestion, ECR image storage. CodeBuild only bills per build minute (no idle cost). ECS cluster, security groups, Service Connect namespace, and the default VPC have no direct cost. |

---

## 1.3 Failure predictions

Picking three edges most likely to break first, based on what's new relative to the working docker-compose setup (Service Connect and IAM are new; ports/health checks are the same as today).

| Broken edge | Expected user symptom | Expected AWS evidence |
|---|---|---|
| ECS execution role → ECR (missing `ecr:GetDownloadUrlForLayer`/pull perms) | Task never reaches `RUNNING`; ALB has no healthy targets | ECS service events: `CannotPullContainerError`; stopped-task "stoppedReason" mentions image pull |
| ALB target group health check path/port mismatch (checking `/service-a/health` instead of `/health`, or wrong port) | `curl http://<alb-dns>/` times out or 503s; app seems fine when hit directly via ECS Exec | Target group console shows targets `unhealthy`; health check failure reason `Health checks failed` |
| Service Connect alias for service-b/service-c not exactly `service-b`/`service-c` (case, typo, or missing from namespace) | `/greet-service-b` returns `504` (callback timeout, matching the existing `callback_timeout` log event at `service_a.py:154`) or a connection error, not a clean 4xx | CloudWatch Logs for service-a show `downstream_call_failed` with a DNS/connection error; Service Connect config in the ECS service shows the alias mismatch |

---

## 1.4 Traffic contracts

```
Internet → ALB → A → B → C
```

No other application path is permitted.

| Source | Destination | Port | Allowed? | Enforcement |
|---|---|---|---|---|
| Internet | ALB | 80 | Yes | `devops-g7-alb-sg` |
| Internet | service-a | 3001 | No | `devops-g7-service-a-sg` |
| Internet | service-b | 3002 | No | `devops-g7-service-b-sg` |
| Internet | service-c | 3003 | No | `devops-g7-service-c-sg` |
| ALB | service-a | 3001 | Yes | ALB SG → service-a SG (SG reference, not CIDR) |
| service-a | service-b | 3002 | Yes | service-a SG → service-b SG |
| service-a | service-c | 3003 | No | no matching rule |
| service-b | service-c | 3003 | Yes | service-b SG → service-c SG |
| service-c | service-a | 3001 | Yes | service-c SG → service-a SG (needed for the `/greeting-rcvd` callback — this is easy to miss since it's the *reverse* of the main flow) |

Note the last row: the assignment's traffic-contract template doesn't include it, but this app's C→A callback (`service_c.py` posting to `service-a:3001/greeting-rcvd`) is a real edge this system needs. Without it, every request will 504 on the callback wait even though A→B→C all succeed — worth calling out explicitly in the scar log if it's missed initially.

### Per-pair contract details

| Pair | Protocol | Port | Service Connect name | Health endpoint | Timeout |
|---|---|---|---|---|---|
| ALB → service-a | HTTP | 3001 | n/a (target group) | `/health` | ALB default (health check interval, not request timeout) |
| service-a → service-b | HTTP | 3002 | `service-b` | `/health` | 5s (`service_a.py:132`) |
| service-b → service-c | HTTP | 3003 | `service-c` | `/health` | 5s (`service_b.py:120`) |
| service-c → service-a | HTTP | 3001 | `service-a` | n/a (callback POST, not health-checked) | 5s (`service_c.py:116`) |

---

## Resource ownership (Working Rules)

| Owner | Responsibilities | Person |
|---|---|---|
| Service A owner | Image, ECR, task definition, security group, ECS service, pipeline | Pheobe |
| Service B owner | Image, ECR, task definition, security group, ECS service, pipeline | Mercylin |
| Service C owner | Image, ECR, task definition, security group, ECS service, pipeline | Mercylin |
| Platform owner | Cluster, namespace, ALB, target group, CodeConnections | Pheobe |

---

## Expected resource names

| Resource | Name |
|---|---|
| ECS cluster | `devops-g7-cluster` |
| ECR repos | `devops-g7-service-a`, `devops-g7-service-b`, `devops-g7-service-c` |
| Task definitions | `devops-g7-service-a-task`, `-service-b-task`, `-service-c-task` |
| ECS services | `devops-g7-service-a-svc`, `-service-b-svc`, `-service-c-svc` |
| Security groups | `devops-g7-alb-sg`, `devops-g7-service-a-sg`, `devops-g7-service-b-sg`, `devops-g7-service-c-sg` |
| Service Connect namespace | `g7.internal` |
| Target group | `devops-g7-service-a-tg` |
| ALB | `devops-g7-alb` |
| CloudWatch log groups | `/ecs/devops-g7-service-a`, `/ecs/devops-g7-service-b`, `/ecs/devops-g7-service-c` |
| CodeBuild projects | `devops-g7-service-a-build`, `-service-b-build`, `-service-c-build` |
| CodePipeline pipelines | `devops-g7-service-a-pipeline`, `-service-b-pipeline`, `-service-c-pipeline` |
| CodeConnections connection | `devops-g7-github-connection` |

## Required tags (apply to every resource that supports tags)

| Key | Value |
|---|---|
| Project | `devops-mentorship` |
| Group | `group-7` |
| Owner | `service-a-owner` / `service-b-owner` / `service-c-owner` / `platform-owner` (per resource) |
| Environment | `lab` |
