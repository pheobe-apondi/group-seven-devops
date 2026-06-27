from flask import Flask, request, jsonify
import json
import uuid
from datetime import datetime
import requests
import sys
import threading

app = Flask(__name__)

SERVICE_NAME = "service-a"
PORT = 3001

def log_event(event, **kwargs):
    """Structured JSON logging"""
    log_entry = {
        "timestamp": datetime.utcnow().isoformat() + "Z",
        "service": SERVICE_NAME,
        "event": event,
        **kwargs
    }
    print(json.dumps(log_entry), file=sys.stdout)
    sys.stdout.flush()

@app.route('/health', methods=['GET'])
def health():
    log_event("health_check", status=200)
    return jsonify({
        "service": SERVICE_NAME,
        "status": "healthy",
        "port": PORT,
        "message": f"Hello {SERVICE_NAME} listening on {PORT}"
    }), 200

# Holds per-request callback events so /greet-service-b can wait for C's callback
_pending_callbacks = {}

@app.route('/greet-service-b', methods=['GET'])
def greet_service_b():
    request_id = request.headers.get('X-Request-ID', str(uuid.uuid4()))

    log_event("request_received",
              request_id=request_id,
              method="GET",
              path="/greet-service-b",
              status=200)

    # Register a slot for the callback before calling B
    event = threading.Event()
    _pending_callbacks[request_id] = event

    try:
        response = requests.get(
            'http://service-b:3002/greet',
            headers={'X-Request-ID': request_id},
            timeout=5
        )

        log_event("downstream_call_success",
                  request_id=request_id,
                  target="service-b",
                  status=response.status_code)

        # Wait up to 5 s for Service C's callback to arrive
        callback_received = event.wait(timeout=5)
        _pending_callbacks.pop(request_id, None)

        if callback_received:
            log_event("request_complete",
                      request_id=request_id,
                      status=200)
            return jsonify({
                "request_id": request_id,
                "status": "success",
                "message": "Request completed successfully"
            }), 200
        else:
            log_event("callback_timeout",
                      request_id=request_id,
                      status=504)
            return jsonify({"error": "Callback from service-c timed out"}), 504

    except Exception as e:
        _pending_callbacks.pop(request_id, None)
        log_event("downstream_call_failed",
                  request_id=request_id,
                  target="service-b",
                  error=str(e),
                  status=500)
        return jsonify({"error": str(e)}), 500

@app.route('/greeting-rcvd', methods=['POST'])
def greeting_rcvd():
    data = request.json
    request_id = data.get('request_id', 'unknown')

    log_event("callback_received",
              request_id=request_id,
              source_service=data.get('source_service'),
              status=200)

    # Signal the waiting /greet-service-b handler
    event = _pending_callbacks.get(request_id)
    if event:
        event.set()

    return jsonify({"status": "received"}), 200

@app.errorhandler(404)
def not_found(e):
    request_id = request.headers.get('X-Request-ID', str(uuid.uuid4()))
    log_event("route_not_found",
              request_id=request_id,
              path=request.path,
              status=404)
    return jsonify({"error": "Not found"}), 404

if __name__ == '__main__':
    log_event("service_starting", port=PORT)
    app.run(host='0.0.0.0', port=PORT, debug=False, threaded=True)