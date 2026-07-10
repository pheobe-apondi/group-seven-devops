# Architecture

## Service Architecture

```
                        Client / Load Test Tool (k6)
                                    |
                                    v
                         Nginx Gateway (:8080, public)
                                    |
                                    v
                  +-------------- service-a (:3001) --------------+
                  |                    |                           |
                  |                    v                           |
                  |            service-b (:3002)                   |
                  |                    |                           |
                  |                    v                           |
                  |            service-c (:3003)                   |
                  |                    |                           |
                  +------ callback POST /greeting-rcvd -------------+
                                    |
        (every hop above emits) Metrics, Logs, Traces
                                    |
        +---------------------------+---------------------------+
        v                           v                           v
  Prometheus (:9090)          Jaeger (:16686)              docker compose logs
  scrapes /metrics            receives OTLP spans          (stdout, structured JSON)
        |
        v
  Alertmanager (:9093) <--- alert-rules.yml evaluated by Prometheus
        |
        v
  Grafana (:3000) <--- queries Prometheus (dashboards + Alert State panel)
```

**Networks** (see `docker-compose.yml`):
- `frontend` — nginx + service-a (the only externally-reachable path)
- `backend` (internal) — service-a/b/c, jaeger, prometheus — service-to-service traffic
  and metrics/trace scraping never leaves this network
- `observability` — prometheus, grafana, jaeger, alertmanager — lets the operating-view
  tools talk to each other without being on the same network as the app services

`service-b` and `service-c` are never published to the host or routed through nginx —
by design, only `service-a` is a public entry point (see `nginx/docker.conf`).

## Request Flow

1. Client sends `GET /service-a/greet-service-b` to nginx (`:8080`)
2. Nginx generates or forwards an `X-Request-ID` header, proxies to `service-a:3001`
3. `service-a` calls `service-b:3002/greet`, propagating `X-Request-ID`
4. `service-b` calls `service-c:3003/greet-c`, propagating `X-Request-ID`
5. `service-c` posts a callback to `service-a:3001/greeting-rcvd` (also carrying
   `X-Request-ID`), then returns its own response back up the chain to `service-b`
6. `service-a` was blocked waiting on that callback (via a `threading.Event`); once it
   arrives, `service-a` returns the final response to nginx, then to the client

The same `X-Request-ID` appears in every service's logs for that request, and the same
distributed-trace `trace_id` (see Tracing Flow below) links the same hops in Jaeger —
confirmed end-to-end: a single client request produces one Jaeger trace containing 7
spans across `service-a`, `service-b`, and `service-c`.

## Telemetry Flow

Every hop in the request flow above emits all three telemetry signals at once:

- a Prometheus counter/histogram observation (Metrics Collection Flow)
- an OpenTelemetry span, auto-propagated to the next hop (Tracing Flow)
- a structured JSON log line carrying both `request_id` and `trace_id` (Logging Flow)

This is what makes it possible to start from any one signal (a Grafana graph, a Jaeger
trace, a log line) and pivot to the other two for the same request.

## Metrics Collection Flow

- Each service exposes `GET /metrics` (via `prometheus_client`) with four required
  metrics: `http_requests_total`, `http_request_duration_seconds`, `http_errors_total`,
  `service_up` — labeled by `service`, `method`, `route`, `status_code` where applicable.
- Prometheus (`prometheus.yml`) scrapes all three by **Compose DNS name**
  (`service-a:3001`, `service-b:3002`, `service-c:3003`), every 15s, into a persistent
  named volume (`prometheus-data`) with 7-day retention.
- Grafana's only datasource is Prometheus (`grafana/provisioning/datasources/prometheus.yml`),
  and the dashboard (`grafana/dashboards/services-overview.json`) is auto-provisioned on
  startup — no manual dashboard import needed.

## Tracing Flow

- Each service auto-instruments Flask (`FlaskInstrumentor`) and the `requests` library
  (`RequestsInstrumentor`) via OpenTelemetry. This means every incoming request gets a
  span, and every outgoing `requests.get`/`requests.post` call automatically injects a
  `traceparent` header — trace context propagation requires no manual code per call site.
- Spans are exported via OTLP/HTTP to Jaeger (`http://jaeger:4318/v1/traces`, overridable
  via the `JAEGER_OTLP_ENDPOINT` env var per service in `docker-compose.yml`).
- The current span's `trace_id` is read back out (`get_trace_id()` in each `service_*.py`)
  and embedded into every structured log line, so a trace found in Jaeger can be pivoted
  straight to `docker compose logs | grep <trace_id>`.
- Verified live: a single client request through the gateway produces one Jaeger trace
  with spans from all three services plus the service-c → service-a callback.

## Logging Flow

- Every service logs structured JSON to stdout — captured by `docker compose logs
  service-a` (or `-b`/`-c`), no separate log shipping required for the minimum bar.
- Common fields: `timestamp`, `service`, `level` (`info`/`warn`/`error`), `event`,
  `request_id` (read from or generated for `X-Request-ID`), `trace_id` (from the current
  span, omitted only when there's genuinely no active span — e.g. at process startup),
  and `duration_ms` wherever a duration was actually measured.
- Error-level events (`level: "error"`) are filterable independently of routine request
  logs, e.g. `docker compose logs service-a | grep '"level": "error"'`.

## Alerting Flow

- Prometheus loads `alert-rules.yml` (`rule_files` in `prometheus.yml`) and evaluates all
  three rules every 15s: `ServiceDown`, `HighErrorRate`, `HighLatency`.
- When a rule's condition holds continuously for its `for:` duration, Prometheus notifies
  Alertmanager (`alerting.alertmanagers` in `prometheus.yml`, pointed at
  `alertmanager:9093`).
- Alertmanager groups and routes to a default receiver (`alertmanager/alertmanager.yml`).
  No external channel (Slack/Discord/webhook) is configured yet — see Known Limitations.
- Grafana's dashboard has an **Alert State** panel querying Prometheus's own `ALERTS`
  metric, so firing alerts are visible on the same operating view as the metrics that
  triggered them.
- All three alerts were triggered and cleared for real against a running stack, with
  observed timings (not just theoretical PromQL) documented in
  [`docs/alerting.md`](alerting.md).

## Known Limitations

- **`docker-compose.prod.yml` has no observability stack.** Prometheus, Grafana, Jaeger,
  and Alertmanager only exist in the dev `docker-compose.yml`. The production compose
  file still only runs the three app services + nginx from pre-built images.
- **Alertmanager has no real notification channel wired up.** There's no Slack/Discord
  webhook or email configured in this environment, so alerts are visible and queryable
  (`:9093`, Prometheus `/alerts`, Grafana's Alert State panel) but nothing is actually
  paged. `alertmanager/alertmanager.yml` documents how to add one.
- **No Loki/Promtail.** Logs are viewed via `docker compose logs`, which the PRD lists as
  the minimum acceptable path — they are not queryable inside Grafana.
- **`/slow` and `/fail` on `service-b`/`service-c` aren't reachable through the gateway.**
  Only `service-a` is routed through nginx by design (network isolation). Reaching the
  other two services' lab-only endpoints requires `docker compose exec` or a container
  attached directly to the `backend` network.
- **Prometheus counters are cumulative for the life of a container**, not per load-test
  run. Restarting a service resets its own counters; restarting Prometheus does not.
  Re-running `scripts/load-test.sh` without restarting the app services accumulates
  totals across runs (see `docs/benchmark-report.md`'s Lessons Learned).
- **`histogram_quantile()` over very few samples can return `NaN`** instead of a number —
  observed when checking the latency alert condition immediately after a single `/slow`
  call. Raw histogram bucket counts are more reliable for one-off manual verification;
  the quantile query resolves normally under sustained load (see `docs/alerting.md`).
