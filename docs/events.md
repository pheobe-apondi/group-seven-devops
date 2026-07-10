# Operational Events

Per PRD §4.5, at least three meaningful operational events, documented here rather than
scattered only through structured logs. These are real events pulled from this repo's
git history and from the failure/load-test verification sessions — not fabricated.

| Timestamp | Event | Detail |
|---|---|---|
| 2026-07-10T21:59:45+03:00 | Configuration changed | PR #11 merged — Prometheus metrics + Grafana operating view added (`d672742`) |
| 2026-07-10T23:02:32+03:00 | Configuration changed | Distributed tracing, richer health checks, and failure endpoints added (`6368f54`) |
| 2026-07-10T23:27:03+03:00 | Configuration changed | PR #13 merged — k6 load testing and benchmark report added (`7967ae2`) |
| ~2026-07-10T20:11Z | Load test started | `./scripts/load-test.sh` — normal scenario (500 req, 10 VUs) against the gateway |
| ~2026-07-10T20:11Z | Load test completed | All three scenarios (normal/stress/failure) finished in well under a minute total; results in [`docs/benchmark-report.md`](benchmark-report.md) |
| 2026-07-11T00:10:31+03:00 | Configuration changed | PR #14 merged — `alert-rules.yml` + Alertmanager added (`39fb543`) |
| 2026-07-10T21:39:31Z (approx) | Failure triggered | `docker compose stop service-b` — see [`docs/failure-simulation.md`](failure-simulation.md) |
| 2026-07-10T21:39:50.813Z | Failure triggered | Request during outage failed; trace `86a1dfbaf1baee4f57054ab300f7c230` recorded, `service-a` logged `downstream_call_failed` |
| ~45s after outage start | Alert fired | `ServiceDown{job="service-b"}` transitioned to `firing` in Prometheus |
| — | Service recovered | `docker compose start service-b`; `/health` back to `"ok"` within seconds |
| ~20s after recovery | Alert cleared | `ServiceDown` alert cleared on Prometheus's next scrape+evaluation cycle |
| 2026-07-11T00:32:58+03:00 | Configuration changed | PR #15 merged — `docs/architecture.md` and related doc fixes added (`1230295`) |

## Where else events show up

- **Structured logs** already carry per-request events (`request_received`,
  `downstream_call_failed`, `forced_failure`, `slow_request_start`, etc. — see
  [`docs/architecture.md`](architecture.md#logging-flow)) — this file is for the
  higher-level operational moments *around* those requests, not a duplicate of them.
- **Alert firing/clearing** is also visible live in Prometheus (`/alerts`) and
  Alertmanager (`:9093`), and on Grafana's Alert State panel.
- **Deployment events** for the systemd/production path are tracked in
  [`../README.md`](../README.md#container-cicd-deployment) (image tags, commit SHAs,
  GitHub Actions run links).
