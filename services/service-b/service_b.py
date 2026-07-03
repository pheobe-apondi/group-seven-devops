from flask import Flask, request, jsonify
import json
import uuid
from datetime import datetime
import requests
import sys

app = Flask(__name__)

SERVICE_NAME = "service-b"
PORT = 3002


def build_service_url(base_url, path):
    base = base_url.rstrip("/")
    normalized_path = path.lstrip("/")
    return f"{base}/{normalized_path}" if normalized_path else base


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

@app.route('/greet', methods=['GET'])
def greet():
    request_id = request.headers.get('X-Request-ID', str(uuid.uuid4()))
    
    log_event("request_received",
              request_id=request_id,
              method="GET",
              path="/greet",
              status=200)
    
    try:
        # Forward to Service C
        response = requests.get(
            build_service_url('http://service-c:3003', '/greet-c'),
            headers={'X-Request-ID': request_id},
            timeout=5
        )
        
        log_event("request_forwarded",
                  request_id=request_id,
                  target="service-c",
                  status=response.status_code)
        
        return jsonify({
            "request_id": request_id,
            "status": "forwarded",
            "target": "service-c"
        }), 200
        
    except Exception as e:
        log_event("downstream_call_failed",
                  request_id=request_id,
                  target="service-c",
                  error=str(e),
                  status=500)
        return jsonify({"error": str(e)}), 500

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
    bind_host = '127.0.0.1' if '--loopback' in sys.argv else '0.0.0.0'
    app.run(host=bind_host, port=PORT, debug=False)