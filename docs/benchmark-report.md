# Benchmark Report

## Test Tool

[k6](https://k6.io/), run via the `grafana/k6` Docker image attached to the compose
network (no host k6 install required). See [`scripts/load-test.js`](../scripts/load-test.js)
for the scenario definitions and [`scripts/load-test.sh`](../scripts/load-test.sh) for the
one-command runner.

## Test Command

```bash
docker compose up -d
./scripts/load-test.sh
```

This runs all three scenarios below sequentially against the gateway (`nginx`) and writes
the full k6 output to `docs/benchmark-results/{normal,stress,failure}.log`.

- **Normal traffic** and **stress traffic** hit `GET /service-a/greet-service-b`, which
  drives the full cross-service chain: gateway → service-a → service-b → service-c →
  callback to service-a.
- **Failure traffic** hits `GET /service-a/fail`, a lab-only endpoint that always returns
  500, used to prove error-rate detection.

## Results

| Scenario | Requests | Concurrency | Avg Latency | p95 Latency | Error Rate | Alert Condition |
| --- | --- | --- | --- | --- | --- | --- |
| Normal traffic | 500 | 10 VUs | 53.6ms | 80.7ms | 0% | Not triggered |
| Stress traffic | 2,000 | 50 VUs | 288.6ms | 368.5ms | 0% | Not triggered (below 500ms p95 threshold) |
| Failure traffic | 300 | 10 VUs | 12.7ms | 24.3ms | 100% | **Triggered** — high error rate |

Raw k6 output for each run is in [`docs/benchmark-results/`](benchmark-results/).

Note: this benchmark run predates [`alert-rules.yml`](../alert-rules.yml) (added in a
later PR), so the "Alert Condition" column above reflects manually evaluating the PRD's
PromQL conditions against Prometheus (see below), not an actual firing Alertmanager
notification. Those same three conditions are now live Prometheus alert rules
(`ServiceDown`, `HighErrorRate`, `HighLatency`) — see [`docs/alerting.md`](alerting.md)
for each one triggered and cleared for real against a running stack.

## Metrics Observed

Queried Prometheus directly after the full run (`normal` + `stress` executed twice during
script iteration, so counters below are cumulative across two back-to-back runs):

```promql
sum by (route, status_code) (http_requests_total{service="service-a"})
```

```text
{route="/greet-service-b", status_code="200"} 5000
{route="/greeting-rcvd",   status_code="200"} 5000
{route="/fail",            status_code="500"}  600
```

**Error-rate alert condition** (`rate(http_errors_total[2m]) > 0.1`):

```promql
rate(http_errors_total{service="service-a"}[2m])
```

```text
{route="/fail"} 2.79
```
2.79 >> 0.1 — condition is true while failure traffic is running. This confirms
`http_errors_total` and the alert's PromQL expression correctly detect the forced-failure
scenario.

**Latency alert condition** (`histogram_quantile(0.95, rate(http_request_duration_seconds_bucket[5m])) > 0.5`):

```promql
histogram_quantile(0.95, rate(http_request_duration_seconds_bucket{service="service-a"}[5m])) > 0.5
```
Returned no result — p95 stayed under the 500ms threshold even under the stress scenario's
50 VUs, because `/greet-service-b`'s latency is dominated by real (fast) network hops, not
an artificial bottleneck. **To reliably demonstrate the latency alert, use the dedicated
`/slow` endpoint** (Failure B from the PRD):

```bash
docker compose exec service-b python3 -c \
  "import urllib.request; urllib.request.urlopen('http://localhost:3002/slow?delay=3')"
```

Verified this separately: the raw histogram buckets for `service-b{route="/slow"}` after a
single `delay=3` call show the request landed in the `le="5.0"` bucket (every bucket
`le<=2.5` reads 0, `le="5.0"` reads 1) — unambiguously past the 500ms threshold. Running
`histogram_quantile()` over `rate()` immediately after only 1-2 scrapes returned `NaN`
rather than a clean number — `rate()` needs multiple samples across the window to
extrapolate a stable per-second rate, so a single one-off slow request is better confirmed
by reading the raw bucket counts than by querying the quantile function right away. Over a
sustained load (or a few more `/slow` calls a scrape-interval apart), the quantile query
resolves normally. `/slow` doesn't run as part of the automated k6 scenarios because it's
a one-shot degradation trigger, not sustained traffic.

## Traces Observed

Every request in the normal/stress scenarios produced a Jaeger trace spanning all three
services plus the service-c → service-a callback (`/greeting-rcvd`), confirmed via:

```bash
curl -s "http://localhost:16686/api/traces?service=service-a&limit=50"
```

A representative trace from this run (`c95ca1d2989394c83859b644e3736e91` style trace IDs)
contains 7 spans across `service-a`, `service-b`, and `service-c`. Failure-traffic requests
(`/fail`) produce a single-span trace on `service-a`, since that endpoint never calls
downstream services — visible in Jaeger as a short trace with an error-tagged span.

## Lessons Learned

- **Counters are cumulative, not scenario-scoped.** Prometheus counters don't reset between
  k6 runs, so if you re-run `load-test.sh` without restarting the stack, `http_requests_total`
  and `http_errors_total` reflect *all* runs since the container started, not just the last
  one. For a clean before/after comparison, either restart the services or compare `rate()`
  over a short window (as done above) rather than raw counter values.
- **Concurrency alone doesn't guarantee a latency alert fires.** Going from 10 to 50 VUs on
  the real request chain raised p95 from ~81ms to ~369ms — a real, measurable degradation —
  but not enough to cross the 500ms alerting threshold. A load test proves the
  instrumentation *reacts* to load; it doesn't automatically prove every alert threshold is
  reachable. The dedicated `/slow` and `/fail` endpoints exist specifically so failure modes
  can be triggered on demand rather than hoped for under load.
- **The dockerized k6 run needs to be on the compose network, not the host port.** Running
  k6 via `docker run --network <compose-network>` and hitting `http://nginx` sidesteps any
  host port conflicts entirely (relevant on this machine, where port 8080 was already taken
  by an unrelated process) and works identically in CI where no host ports are published.
- **`--summary-export` needs a writable mount from the container's perspective.** The
  `grafana/k6` image runs as a non-root user, so writing directly into a host-owned bind
  mount failed with `permission denied`. Capturing stdout via `tee` on the host side (as
  `load-test.sh` does) avoided the issue entirely and is simpler than fixing container UID
  mapping.
