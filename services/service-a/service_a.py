from flask import Flask, request, jsonify
from prometheus_client import Counter, Histogram, Gauge, generate_latest, CONTENT_TYPE_LATEST
from opentelemetry import trace
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor
from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
from opentelemetry.instrumentation.flask import FlaskInstrumentor
from opentelemetry.instrumentation.requests import RequestsInstrumentor
import json
import os
import uuid
import time
from datetime import datetime
import requests
import sys
import threading

app = Flask(__name__)

SERVICE_NAME = "service-a"
PORT = 3001

# --- Prometheus metrics ---
REQUEST_COUNT = Counter(
    "http_requests_total",
    "Total HTTP requests",
    ["service", "method", "route", "status_code"]
)
REQUEST_DURATION = Histogram(
    "http_request_duration_seconds",
    "HTTP request duration in seconds",
    ["service", "method", "route"],
    buckets=[0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0]
)
ERROR_COUNT = Counter(
    "http_errors_total",
    "Total HTTP errors (status >= 500)",
    ["service", "route"]
)
SERVICE_UP = Gauge("service_up", "Service is up (1) or down (0)", ["service"])
SERVICE_UP.labels(service=SERVICE_NAME).set(1)

# --- Distributed tracing (OpenTelemetry -> Jaeger via OTLP) ---
JAEGER_OTLP_ENDPOINT = os.environ.get("JAEGER_OTLP_ENDPOINT", "http://jaeger:4318/v1/traces")

if not isinstance(trace.get_tracer_provider(), TracerProvider):
    trace.set_tracer_provider(TracerProvider(resource=Resource.create({"service.name": SERVICE_NAME})))
trace.get_tracer_provider().add_span_processor(BatchSpanProcessor(OTLPSpanExporter(endpoint=JAEGER_OTLP_ENDPOINT)))

FlaskInstrumentor().instrument_app(app)
RequestsInstrumentor().instrument()


def get_trace_id():
    """Hex-encoded trace ID of the current span, or None outside a request."""
    ctx = trace.get_current_span().get_span_context()
    return format(ctx.trace_id, "032x") if ctx and ctx.is_valid else None


def build_service_url(base_url, path):
    base = base_url.rstrip("/")
    normalized_path = path.lstrip("/")
    return f"{base}/{normalized_path}" if normalized_path else base


def log_event(event, level="info", **kwargs):
    log_entry = {
        "timestamp": datetime.utcnow().isoformat() + "Z",
        "service": SERVICE_NAME,
        "level": level,
        "event": event,
    }
    trace_id = get_trace_id()
    if trace_id:
        log_entry["trace_id"] = trace_id
    log_entry.update(kwargs)
    print(json.dumps(log_entry), file=sys.stdout)
    sys.stdout.flush()


# Holds per-request callback events so /greet-service-b can wait for C's callback
_pending_callbacks = {}


@app.route("/health", methods=["GET"])
def health():
    start = time.time()
    dependencies = {}
    overall = "ok"

    try:
        r = requests.get("http://service-b:3002/health", timeout=2)
        dependencies["service-b"] = "ok" if r.status_code == 200 else "degraded"
        if r.status_code != 200:
            overall = "degraded"
    except Exception:
        dependencies["service-b"] = "unreachable"
        overall = "degraded"

    duration_ms = round((time.time() - start) * 1000, 2)
    log_event("health_check", status=200, overall=overall, dependencies=dependencies, duration_ms=duration_ms)
    return jsonify({
        "service": SERVICE_NAME,
        "status": overall,
        "port": PORT,
        "dependencies": dependencies
    }), 200


@app.route("/metrics", methods=["GET"])
def metrics():
    return generate_latest(), 200, {"Content-Type": CONTENT_TYPE_LATEST}


@app.route("/greet-service-b", methods=["GET"])
def greet_service_b():
    start = time.time()
    request_id = request.headers.get("X-Request-ID", str(uuid.uuid4()))
    route = "/greet-service-b"

    log_event("request_received", request_id=request_id, method="GET", path=route)

    event = threading.Event()
    _pending_callbacks[request_id] = event

    try:
        response = requests.get(
            build_service_url("http://service-b:3002", "/greet"),
            headers={"X-Request-ID": request_id},
            timeout=5
        )
        log_event("downstream_call_success", request_id=request_id,
                  target="service-b", status=response.status_code)

        callback_received = event.wait(timeout=5)
        _pending_callbacks.pop(request_id, None)

        duration = time.time() - start
        REQUEST_DURATION.labels(service=SERVICE_NAME, method="GET", route=route).observe(duration)

        if callback_received:
            REQUEST_COUNT.labels(service=SERVICE_NAME, method="GET", route=route, status_code="200").inc()
            log_event("request_complete", request_id=request_id, method="GET", path=route,
                      status=200, duration_ms=round(duration * 1000, 2))
            return jsonify({
                "request_id": request_id,
                "status": "success",
                "message": "Request completed successfully"
            }), 200
        else:
            REQUEST_COUNT.labels(service=SERVICE_NAME, method="GET", route=route, status_code="504").inc()
            ERROR_COUNT.labels(service=SERVICE_NAME, route=route).inc()
            log_event("callback_timeout", level="error", request_id=request_id, method="GET", path=route,
                      status=504, duration_ms=round(duration * 1000, 2),
                      error="callback from service-c timed out")
            return jsonify({"error": "Callback from service-c timed out"}), 504

    except Exception as e:
        _pending_callbacks.pop(request_id, None)
        duration = time.time() - start
        REQUEST_COUNT.labels(service=SERVICE_NAME, method="GET", route=route, status_code="500").inc()
        ERROR_COUNT.labels(service=SERVICE_NAME, route=route).inc()
        REQUEST_DURATION.labels(service=SERVICE_NAME, method="GET", route=route).observe(duration)
        log_event("downstream_call_failed", level="error", request_id=request_id, target="service-b",
                  error=str(e), status=500, duration_ms=round(duration * 1000, 2))
        return jsonify({"error": str(e)}), 500


@app.route("/greeting-rcvd", methods=["POST"])
def greeting_rcvd():
    data = request.json
    request_id = data.get("request_id", "unknown")
    REQUEST_COUNT.labels(service=SERVICE_NAME, method="POST", route="/greeting-rcvd", status_code="200").inc()
    log_event("callback_received", request_id=request_id,
              source_service=data.get("source_service"), status=200)
    event = _pending_callbacks.get(request_id)
    if event:
        event.set()
    return jsonify({"status": "received"}), 200


# --- Lab-only controlled failure endpoints (for observability/alerting testing) ---

@app.route("/slow", methods=["GET"])
def slow():
    """Lab only: simulate a slow response to test p95 latency alerting."""
    start = time.time()
    request_id = request.headers.get("X-Request-ID", str(uuid.uuid4()))
    route = "/slow"
    delay = float(request.args.get("delay", 2))

    log_event("slow_request_start", level="warn", request_id=request_id, delay_s=delay)
    time.sleep(delay)

    duration = time.time() - start
    REQUEST_COUNT.labels(service=SERVICE_NAME, method="GET", route=route, status_code="200").inc()
    REQUEST_DURATION.labels(service=SERVICE_NAME, method="GET", route=route).observe(duration)
    log_event("slow_request_complete", request_id=request_id, method="GET", path=route,
              status=200, duration_ms=round(duration * 1000, 2))
    return jsonify({"request_id": request_id, "delayed_s": delay}), 200


@app.route("/fail", methods=["GET"])
def fail():
    """Lab only: always returns 500 to test error rate alerting."""
    start = time.time()
    request_id = request.headers.get("X-Request-ID", str(uuid.uuid4()))
    route = "/fail"

    duration = time.time() - start
    REQUEST_COUNT.labels(service=SERVICE_NAME, method="GET", route=route, status_code="500").inc()
    ERROR_COUNT.labels(service=SERVICE_NAME, route=route).inc()
    REQUEST_DURATION.labels(service=SERVICE_NAME, method="GET", route=route).observe(duration)
    log_event("forced_failure", level="error", request_id=request_id, method="GET", path=route,
              status=500, duration_ms=round(duration * 1000, 2),
              error="forced failure for observability testing")
    return jsonify({"error": "forced failure", "request_id": request_id}), 500


@app.errorhandler(404)
def not_found(e):
    request_id = request.headers.get("X-Request-ID", str(uuid.uuid4()))
    REQUEST_COUNT.labels(service=SERVICE_NAME, method=request.method, route=request.path, status_code="404").inc()
    log_event("route_not_found", level="warn", request_id=request_id, path=request.path, status=404)
    return jsonify({"error": "Not found"}), 404


if __name__ == "__main__":
    log_event("service_starting", port=PORT)
    bind_host = "127.0.0.1" if "--loopback" in sys.argv else "0.0.0.0"
    app.run(host=bind_host, port=PORT, debug=False, threaded=True)
