# Failure Simulation

Chosen failure: **Failure A — Service Down** (PRD §7). This is the fullest
demonstration of all four MELT signals reacting to the same incident, so it's
documented in full below. Failures B (High Latency) and C (High Error Rate)
were also triggered and verified separately — see
[`docs/alerting.md`](alerting.md) for their reproduction steps and observed
timings.

## Trigger

```bash
docker compose up -d
docker compose stop service-b
```

## Evidence, in the order it actually appeared

**1. A request sent during the outage fails, and the failure is visible in the trace.**

```bash
curl -s -H "X-Request-ID: during-failure-001" --max-time 8 \
  http://localhost:8080/service-a/greet-service-b
```
```json
{"error":"HTTPConnectionPool(host='service-b', port=3002): Max retries exceeded with url: /greet (Caused by NameResolutionError(...))"}
```

The response carried `trace_id=86a1dfbaf1baee4f57054ab300f7c230`. Looking that
trace up in Jaeger (`http://localhost:16686` or
`GET /api/traces/86a1dfbaf1baee4f57054ab300f7c230`) shows both spans tagged
`error=True`:

```
service=service-a op=GET /greet-service-b   duration=108.8ms  error=True
service=service-a op=GET                    duration=107.2ms  error=True
```

**2. Logs show the failed dependency, correlated by the same trace_id.**

```json
{"timestamp": "2026-07-10T21:39:50.813111Z", "service": "service-a", "level": "info",
 "event": "request_received", "trace_id": "86a1dfbaf1baee4f57054ab300f7c230",
 "request_id": "during-failure-001", "method": "GET", "path": "/greet-service-b"}
{"timestamp": "2026-07-10T21:39:50.921009Z", "service": "service-a", "level": "error",
 "event": "downstream_call_failed", "trace_id": "86a1dfbaf1baee4f57054ab300f7c230",
 "request_id": "during-failure-001", "target": "service-b",
 "error": "HTTPConnectionPool(host='service-b', port=3002): ...NameResolutionError...",
 "status": 500, "duration_ms": 107.83}
```

**3. The dependent service (`service-a`) reports itself degraded.**

```bash
curl -s http://localhost:8080/service-a/health
```
```json
{"service":"service-a","status":"degraded","port":3001,"dependencies":{"service-b":"unreachable"}}
```

**4. The Prometheus target goes down, and the `ServiceDown` alert fires.**

```bash
curl -s http://localhost:9090/api/v1/targets    # job="service-b" -> health="down"
curl -s http://localhost:9090/api/v1/alerts     # alertname="ServiceDown", state="firing"
```

Observed: the target flipped to `down` on the next scrape (within 15s of
stopping the container); the alert itself reached `firing` about 45s after
`docker compose stop service-b` (its `for: 30s` window, rounded up to the next
15s evaluation tick).

## Recovery

```bash
docker compose start service-b
curl -s http://localhost:8080/service-a/health
# -> {"status":"ok","dependencies":{"service-b":"ok"}}
curl -s http://localhost:8080/service-a/greet-service-b
# -> {"status":"success", ...}
```

Observed: `/health` returned to `"ok"` within seconds of the container
restarting, a fresh request through the gateway succeeded immediately, and the
`ServiceDown` alert cleared on Prometheus's next scrape+evaluation cycle
(within 20s, no restart of Prometheus needed).

## MELT summary for this incident

| Signal | What it showed |
|---|---|
| **Metrics** | `up{job="service-b"}` dropped to 0; Prometheus target list showed `service-b` as `down` |
| **Events** | "Failure triggered" and "Service recovered" — see [`docs/events.md`](events.md) |
| **Logs** | `service-a` logged a `downstream_call_failed` error event with the connection failure reason, correlated by `request_id` and `trace_id` |
| **Traces** | The failing request's trace showed both its spans tagged `error=True`, pinpointing exactly which call failed |
| **Alerts** | `ServiceDown{job="service-b"}` fired ~45s after the outage started, and cleared within 20s of recovery |
