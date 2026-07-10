# Alerting Runbook

Three Prometheus alert rules are defined in [`alert-rules.yml`](../alert-rules.yml),
loaded by Prometheus via `rule_files` in [`prometheus.yml`](../prometheus.yml), and
routed to Alertmanager (`http://localhost:9093`). Alertmanager's default receiver has
no external notification channel wired up yet (see
[`alertmanager/alertmanager.yml`](../alertmanager/alertmanager.yml) for how to add
Slack/Discord/email/webhook) — alerts are fully visible and queryable, just not paged
anywhere outside this stack.

All three were triggered for real against a running stack while writing this doc; the
timings below are observed, not assumed.

## Where to look

| What | Where |
|---|---|
| Alert rule state (inactive/pending/firing) | `http://localhost:9090/alerts` or `curl http://localhost:9090/api/v1/alerts` |
| Routed/active alerts | `http://localhost:9093` or `curl http://localhost:9093/api/v2/alerts` |
| Alert state on the operating dashboard | Grafana → "Group Seven — Service Overview" → **Alert State** panel |

---

## Alert 1: ServiceDown

- **PromQL**: `up{job=~"service-a|service-b|service-c"} == 0`
- **`for`**: 30s
- **What it means**: Prometheus has failed to scrape one of the three services for at
  least 30 seconds straight. The service is down, crashed, or unreachable on the network.
- **Possible causes**: container stopped/crashed, out of memory, port misconfiguration,
  the `backend` Docker network is unreachable, the service is still starting up (cold
  start takes a few seconds).
- **How to reproduce**:
  ```bash
  docker compose stop service-b
  # wait ~30-45s
  curl http://localhost:9090/api/v1/alerts   # alertname=ServiceDown, state=firing
  ```
- **First checks**:
  ```bash
  docker compose ps service-b
  docker compose logs --tail=50 service-b
  curl http://localhost:9090/targets   # confirm which target shows "down"
  ```
- **Confirm normal state**:
  ```bash
  docker compose start service-b
  curl http://localhost:8080/service-a/health   # service-a should report service-b "ok"
  ```
  Observed: with `service-b` stopped, `service-a`'s `/health` immediately reported
  `{"dependencies":{"service-b":"unreachable"},"status":"degraded"}`, and
  `ServiceDown{job="service-b"}` transitioned to `firing` ~30-45s later. After
  `docker compose start service-b`, `/health` returned to `"ok"` within seconds, and the
  alert cleared on Prometheus's next scrape+evaluation cycle (well under a minute).

---

## Alert 2: HighErrorRate

- **PromQL**: `rate(http_errors_total[2m]) > 0.1`
- **`for`**: 1m
- **What it means**: a route has been returning more than 0.1 errors/sec (5xx status)
  on average over the last 2 minutes, sustained for at least 1 minute.
- **Possible causes**: a downstream dependency failing (see `downstream_call_failed` /
  `callback_failed` structured logs), a bug in a specific route, or the lab-only `/fail`
  endpoint being hit (intentionally, for testing).
- **How to reproduce**:
  ```bash
  # sustained load beats a single request - a burst of a few requests won't
  # hold rate() > 0.1 for the full 1m "for" window
  for i in $(seq 1 200); do curl -s -o /dev/null http://localhost:8080/service-a/fail; sleep 0.3; done
  curl http://localhost:9090/api/v1/alerts   # alertname=HighErrorRate, state=firing
  ```
- **First checks**:
  ```bash
  docker compose logs service-a | grep '"level": "error"' | tail -20
  curl -s http://localhost:9090/api/v1/query --data-urlencode \
    'query=rate(http_errors_total[2m])'
  ```
- **Confirm normal state**: stop sending traffic to `/fail`; once `rate(http_errors_total[2m])`
  drops back under 0.1 and stays there, the alert clears automatically (no restart needed).
  Observed: a single short burst of failing requests only reached `pending` (the
  condition needs to hold continuously for the full 1-minute `for` window); ~2 minutes
  of sustained `/fail` traffic pushed it to `firing` (observed rate: ~2.8 errors/sec,
  well above the 0.1 threshold). It cleared within ~2.5 minutes of stopping the traffic,
  consistent with the `rate(...[2m])` window needing to age out the last error.

---

## Alert 3: HighLatency

- **PromQL**: `histogram_quantile(0.95, sum by (service, route, le) (rate(http_request_duration_seconds_bucket[5m]))) > 0.5`
- **`for`**: 1m
- **What it means**: the 95th-percentile request duration for some service/route has
  been above 500ms for at least 1 minute.
- **Possible causes**: a genuinely slow downstream dependency, resource contention under
  load (see the stress-traffic scenario in
  [`docs/benchmark-report.md`](benchmark-report.md), which raised p95 from ~81ms to
  ~369ms without tripping this alert), or the lab-only `/slow` endpoint being hit.
- **How to reproduce**:
  ```bash
  for i in $(seq 1 15); do
    curl -s -o /dev/null "http://localhost:8080/service-a/slow?delay=1"
  done
  curl http://localhost:9090/api/v1/alerts   # alertname=HighLatency, state=firing
  ```
- **First checks**:
  ```bash
  curl -s http://localhost:9090/api/v1/query --data-urlencode \
    'query=histogram_quantile(0.95, sum by (service, route, le) (rate(http_request_duration_seconds_bucket[5m])))'
  # open Jaeger and look for the slow span: http://localhost:16686
  ```
- **Confirm normal state**: stop sending `/slow` traffic; the alert clears once the
  5-minute rate window ages out the slow samples.
  Observed: with `/slow?delay=1` called a few times, the alert reached `pending`
  immediately but needed the full 1-minute `for` window with no further requests to tip
  into `firing` (occasional bucket-boundary noise with very few samples delayed this
  slightly). It stayed `firing` for several minutes afterward — because the condition
  uses a **5-minute** rate window, the alert doesn't clear the instant you stop sending
  slow requests; it clears once those samples age out of the 5-minute lookback (observed
  clearing roughly 5 minutes after the last slow request, matching the window size).

---

## Notes on all three

- **Prometheus counters are cumulative for the life of the container.** Restarting a
  service resets its counters to zero (a fresh process, fresh `prometheus_client`
  registry); restarting *Prometheus itself* does not, since `http_errors_total` etc. live
  in the scraped service, not in Prometheus.
- **`for:` duration means "condition true for the whole window", not "true at least
  once".** A single failing/slow request will show up in `pending` but won't fire an
  alert — this is by design, to avoid paging on transient blips. Reproducing an alert for
  a demo means sustaining the condition, not just hitting the endpoint once.
- **Alertmanager has no external channel configured.** `docs: alertmanager/alertmanager.yml`
  documents how to add one (Slack/Discord/email/generic webhook) — until then, "alerting"
  in this repo means "visible and queryable in Prometheus/Alertmanager", not "paged to a
  human", which matches the PRD's stated minimum bar (documented manual verification).
