# Jaeger

Distributed tracing for `service-a` → `service-b` → `service-c` (and the
`service-c` → `service-a` callback). This directory has no config of its own —
Jaeger runs as the `jaegertracing/all-in-one:1.57` image in
[`docker-compose.yml`](../docker-compose.yml) with its OTLP receiver enabled
(`COLLECTOR_OTLP_ENABLED: "true"`), and each service is instrumented with
OpenTelemetry (see [`docs/architecture.md`](../docs/architecture.md#tracing-flow)
for how spans are created and propagated).

## What problem it solves

Prometheus can tell you *that* latency increased or a route started failing.
Jaeger shows *where* in the request chain that happened — which hop was slow,
which hop errored, and how the request actually flowed across all three
services for a single client request.

## What data it collects

One span per request per service, plus child spans for every outgoing
`requests` call, exported via OTLP/HTTP (`http://jaeger:4318/v1/traces`). Each
span carries the service name, endpoint, duration, status, and error state.
The resulting `trace_id` is also embedded in that request's structured logs
(see [`docs/architecture.md`](../docs/architecture.md#logging-flow)), so you
can pivot from a trace straight to `docker compose logs`.

## Where the data is viewed

Jaeger UI at `http://localhost:16686` — search by service name
(`service-a`, `service-b`, or `service-c`) to find a trace, or paste a
`trace_id` copied from a log line directly into the search box.

## How it helps debugging

- Confirms trace propagation is actually wired correctly: a healthy request
  through the gateway produces one trace with 7 spans spanning all three
  services (verified live — see [`docs/architecture.md`](../docs/architecture.md#request-flow)).
- Triggering `/slow` or `/fail` (see [`docs/failure-simulation.md`](../docs/failure-simulation.md))
  shows exactly which span is slow or errored, rather than just "latency went up."
- Lets you go from "Prometheus says p95 is high" to "here's the exact request
  and the exact hop that was slow" in a couple of clicks.
