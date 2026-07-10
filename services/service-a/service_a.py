from flask import Flask, request, jsonify
from prometheus_client import Counter, Histogram, Gauge, generate_latest, CONTENT_TYPE_LATEST
import json
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


# Holds per-request callback events so /greet-service-b can wait for C's callback
_pending_callbacks = {}


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
            log_event("request_complete", request_id=request_id, status=200,
                      duration_ms=round(duration * 1000, 2))
            return jsonify({
                "request_id": request_id,
                "status": "success",
                "message": "Request completed successfully"
            }), 200
        else:
            REQUEST_COUNT.labels(service=SERVICE_NAME, method="GET", route=route, status_code="504").inc()
            ERROR_COUNT.labels(service=SERVICE_NAME, route=route).inc()
            log_event("callback_timeout", request_id=request_id, status=504,
                      duration_ms=round(duration * 1000, 2))
            return jsonify({"error": "Callback from service-c timed out"}), 504

    except Exception as e:
        _pending_callbacks.pop(request_id, None)
        duration = time.time() - start
        REQUEST_COUNT.labels(service=SERVICE_NAME, method="GET", route=route, status_code="500").inc()
        ERROR_COUNT.labels(service=SERVICE_NAME, route=route).inc()
        REQUEST_DURATION.labels(service=SERVICE_NAME, method="GET", route=route).observe(duration)
        log_event("downstream_call_failed", request_id=request_id, target="service-b",
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


@app.errorhandler(404)
def not_found(e):
    request_id = request.headers.get("X-Request-ID", str(uuid.uuid4()))
    REQUEST_COUNT.labels(service=SERVICE_NAME, method=request.method, route=request.path, status_code="404").inc()
    log_event("route_not_found", request_id=request_id, path=request.path, status=404)
    return jsonify({"error": "Not found"}), 404


if __name__ == "__main__":
    log_event("service_starting", port=PORT)
    bind_host = "127.0.0.1" if "--loopback" in sys.argv else "0.0.0.0"
    app.run(host=bind_host, port=PORT, debug=False, threaded=True)
