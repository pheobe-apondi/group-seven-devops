from flask import Flask, request, jsonify
from prometheus_client import Counter, Histogram, Gauge, generate_latest, CONTENT_TYPE_LATEST
import json
import uuid
import time
from datetime import datetime
import requests
import sys

app = Flask(__name__)

SERVICE_NAME = "service-c"
PORT = 3003

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


def build_service_url(base_url, path):
    base = base_url.rstrip("/")
    normalized_path = path.lstrip("/")
    return f"{base}/{normalized_path}" if normalized_path else base


def log_event(event, **kwargs):
    log_entry = {
        "timestamp": datetime.utcnow().isoformat() + "Z",
        "service": SERVICE_NAME,
        "event": event,
        **kwargs
    }
    print(json.dumps(log_entry), file=sys.stdout)
    sys.stdout.flush()


@app.route("/health", methods=["GET"])
def health():
    log_event("health_check", status=200)
    return jsonify({
        "service": SERVICE_NAME,
        "status": "healthy",
        "port": PORT,
        "message": f"Hello {SERVICE_NAME} listening on {PORT}"
    }), 200


@app.route("/metrics", methods=["GET"])
def metrics():
    return generate_latest(), 200, {"Content-Type": CONTENT_TYPE_LATEST}


@app.route("/greet-c", methods=["GET"])
def greet_c():
    start = time.time()
    request_id = request.headers.get("X-Request-ID", str(uuid.uuid4()))
    route = "/greet-c"

    log_event("request_received", request_id=request_id, method="GET", path=route)

    try:
        callback_data = {
            "request_id": request_id,
            "source_service": SERVICE_NAME,
            "message": "Greeting processed",
            "timestamp": datetime.utcnow().isoformat() + "Z"
        }
        response = requests.post(
            build_service_url("http://service-a:3001", "/greeting-rcvd"),
            json=callback_data,
            headers={"X-Request-ID": request_id},
            timeout=5
        )
        duration = time.time() - start
        REQUEST_COUNT.labels(service=SERVICE_NAME, method="GET", route=route, status_code="200").inc()
        REQUEST_DURATION.labels(service=SERVICE_NAME, method="GET", route=route).observe(duration)
        log_event("callback_sent", request_id=request_id, target="service-a",
                  status=response.status_code, duration_ms=round(duration * 1000, 2))
        return jsonify({
            "request_id": request_id,
            "status": "processed",
            "callback_sent": True
        }), 200

    except Exception as e:
        duration = time.time() - start
        REQUEST_COUNT.labels(service=SERVICE_NAME, method="GET", route=route, status_code="500").inc()
        ERROR_COUNT.labels(service=SERVICE_NAME, route=route).inc()
        REQUEST_DURATION.labels(service=SERVICE_NAME, method="GET", route=route).observe(duration)
        log_event("callback_failed", request_id=request_id, target="service-a",
                  error=str(e), status=500, duration_ms=round(duration * 1000, 2))
        return jsonify({"error": str(e)}), 500


@app.errorhandler(404)
def not_found(e):
    request_id = request.headers.get("X-Request-ID", str(uuid.uuid4()))
    REQUEST_COUNT.labels(service=SERVICE_NAME, method=request.method, route=request.path, status_code="404").inc()
    log_event("route_not_found", request_id=request_id, path=request.path, status=404)
    return jsonify({"error": "Not found"}), 404


if __name__ == "__main__":
    log_event("service_starting", port=PORT)
    bind_host = "127.0.0.1" if "--loopback" in sys.argv else "0.0.0.0"
    app.run(host=bind_host, port=PORT, debug=False)
