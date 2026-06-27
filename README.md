# Production-Style Service Architecture

## Overview

This project demonstrates a production-ready microservices environment with three internal HTTP services orchestrated through systemd, exposed via Nginx reverse proxy, with structured JSON logging and distributed request tracing.

## Environment

This project runs on **Ubuntu 24.04 LTS** inside a dedicated VM. Do not run it on a shared or existing VM — `install.sh` writes to `/etc/hosts`, installs systemd units, and modifies Nginx config.

The original development environment was a fresh Ubuntu 24.04 LTS instance with no prior services installed. Replicate that baseline before running the installer.

**Pick your host OS to get started:**

| Host OS | Setup Guide |
|---|---|
| macOS | [docs/setup-macos.md](docs/setup-macos.md) |
| Linux | [docs/setup-linux.md](docs/setup-linux.md) |
| Windows | [docs/setup-windows.md](docs/setup-windows.md) |

## Quick Start

### Clone and Deploy (5 minutes)

```bash
# 1. Clone the repository
git clone https://github.com/pheobe-apondi/group-seven-devops.git
cd group-seven-devops

# 2. Run the automated installer
sudo ./install.sh

# 3. Verify it's working
curl http://localhost/service-a/greet-service-b

# 4. View logs
journalctl -u "service-*" -f
```

The installer will:
- Install system dependencies (Python, Nginx, etc.)
- Remove conflicting packages (if any)
- Configure service discovery
- Set up systemd services
- Configure Nginx reverse proxy
- Start all services

### Troubleshooting Installation

**If installation fails or you want a clean slate:**

```bash
# Complete reset (stops all services and removes configs)
./reset.sh

# Then reinstall fresh
sudo ./install.sh
```

The `reset.sh` script:
- Stops all services
- Removes systemd service files
- Clears Nginx configuration
- Leaves the codebase intact

**Use this if:**
- Installation fails midway
- You're running install.sh multiple times
- Services are in a bad state
- You want to start completely fresh

### Manual Deployment (if you prefer)

See [Installation](#installation) section below.

## Architecture

```
Internet Client
    ↓
Nginx (port 80) ← PUBLIC
    ↓
Service A (port 3001) ← INTERNAL
    ↓
Service B (port 3002) ← INTERNAL
    ↓
Service C (port 3003) ← INTERNAL
    ↓
Service A (callback)
```

### Services

- **Service A**: Entry point. Receives requests, initiates flow to B, receives callbacks from C
- **Service B**: Middleware. Receives from A, forwards to C
- **Service C**: Terminal service. Processes requests, sends callback to A

### Network Security

Services B and C are protected from external access by two independent layers:

1. **Loopback binding** — all three services bind to `127.0.0.1` only (`host='127.0.0.1'` in each service). The OS refuses connections from any non-loopback interface before they even reach the application.
2. **Firewall (UFW)** — ports 3001, 3002, and 3003 are not open in UFW. Only port 80 (Nginx) is exposed externally.

These two protections are independent. Even if Nginx were misconfigured to proxy to B or C, direct external access on ports 3002/3003 would still be blocked by the firewall.

**Verify loopback binding:**
```bash
ss -tlnp | grep -E '3001|3002|3003'
# All three should show 127.0.0.1:PORT, not 0.0.0.0:PORT
```

**Verify firewall rules:**
```bash
sudo ufw status
# Should show port 80 ALLOW, no entry for 3001/3002/3003
```

**Verify external access is blocked (run from outside the VM):**
```bash
curl http://<vm-ip>:3002  # Connection refused
curl http://<vm-ip>:3003  # Connection refused
curl http://<vm-ip>/service-a/health  # Works (via Nginx on port 80)
```

### Service Discovery

Services communicate using DNS names in `/etc/hosts`:
```
127.0.0.1 service-a.internal
127.0.0.1 service-b.internal
127.0.0.1 service-c.internal
```

**How it works:** Services use hostnames instead of hardcoded IPs. The kernel resolves names via `/etc/hosts`. This decouples application logic from infrastructure.

**Troubleshooting:** `nslookup service-b.internal` or `cat /etc/hosts | grep service`

### Request Tracing

Every request receives a unique `X-Request-ID` header that propagates through the entire flow. The same ID appears in logs from all services, enabling end-to-end tracing.

**Example trace:**
```bash
curl http://localhost/service-a/greet-service-b
journalctl -u service-a | grep <request-id>
journalctl -u service-b | grep <request-id>
journalctl -u service-c | grep <request-id>
```

## Installation

### Prerequisites

- Ubuntu 24.04 LTS
- Python 3.12+
- Nginx
- systemd

### Automated Setup

```bash
# Clone to any directory — install.sh auto-detects its own path
git clone https://github.com/pheobe-apondi/group-seven-devops.git
cd group-seven-devops
sudo ./install.sh
```

### Manual Setup

> **Note:** Replace `PROJECT_DIR` below with the absolute path to where you cloned the repo (e.g. `/home/youruser/group-seven-devops`).

```bash
export PROJECT_DIR=$(pwd)

# 1. Install dependencies
sudo apt update
sudo apt install -y python3 python3-pip nginx
pip3 install --break-system-packages flask requests

# 2. Add service discovery entries
sudo bash -c 'cat >> /etc/hosts << EOF
127.0.0.1 service-a.internal
127.0.0.1 service-b.internal
127.0.0.1 service-c.internal
EOF'

# 3. Install systemd service files (paths are injected by install.sh)
sudo ./install.sh   # recommended — handles path injection automatically
# OR manually edit WorkingDirectory and ExecStart in each .service file
# before copying them to /etc/systemd/system/

# 4. Configure Nginx
sudo cp nginx/default.conf /etc/nginx/sites-available/default
sudo nginx -t
sudo systemctl restart nginx

# 5. Enable and start services (order matters!)
sudo systemctl enable service-a service-b service-c
sudo systemctl start service-b service-c service-a
```

## Operation

### All Services

```bash
sudo systemctl start service-a service-b service-c
sudo systemctl stop service-a service-b service-c
sudo systemctl restart service-a service-b service-c
systemctl status service-a service-b service-c
```

### Individual Service Commands

```bash
# Service A
sudo systemctl start service-a
sudo systemctl stop service-a
sudo systemctl restart service-a
systemctl status service-a

# Service B
sudo systemctl start service-b
sudo systemctl stop service-b
sudo systemctl restart service-b
systemctl status service-b

# Service C
sudo systemctl start service-c
sudo systemctl stop service-c
sudo systemctl restart service-c
systemctl status service-c
```

### Demonstrate Automatic Restart

```bash
# Kill Service B's process directly — systemd should restart it automatically
sudo kill $(pgrep -f service_b.py)
sleep 6
systemctl status service-b  # should show active (running) again
```

### View Logs

```bash
# Service A logs (live)
journalctl -u service-a -f

# All services (live)
journalctl -u "service-*" -f

# Last 50 lines
journalctl -u service-a -n 50

# Nginx access log (JSON, includes request_id)
sudo tail -f /var/log/nginx/access.log
```

## Validation

### Health Checks

```bash
# Via Nginx (public)
curl http://localhost/service-a/health

# Internal (direct)
curl http://service-b.internal:3002/health
curl http://service-c.internal:3003/health
```

### Full Request Flow

```bash
curl http://localhost/service-a/greet-service-b
```

Expected response:
```json
{
  "request_id": "ae9eab31-a249-4803-bae4-a136cd98c2a8",
  "status": "success",
  "message": "Request completed successfully"
}
```

### Verify Request Tracing

```bash
# Trigger request
REQUEST_ID=$(curl -s http://localhost/service-a/greet-service-b | jq -r .request_id)

# Check all services logged it (including Nginx entry point)
sudo grep $REQUEST_ID /var/log/nginx/access.log
journalctl -u service-a | grep $REQUEST_ID
journalctl -u service-b | grep $REQUEST_ID
journalctl -u service-c | grep $REQUEST_ID
```

All four (Nginx + three services) should show the same request_id, tracing the full path from public entry to final callback.

## Logging

All services produce structured JSON logs with:
- `timestamp`: ISO 8601 UTC
- `service`: service name
- `event`: event type (request_received, downstream_call, callback_sent, etc.)
- `request_id`: distributed trace ID
- `status`: HTTP status code
- Additional context fields per event type

**Example log entry:**
```json
{
  "timestamp": "2026-06-19T17:06:06.969532Z",
  "service": "service-a",
  "event": "callback_received",
  "request_id": "ae9eab31-a249-4803-bae4-a136cd98c2a8",
  "source_service": "service-c",
  "status": 200
}
```

**Log locations:**
```bash
journalctl -u service-a
journalctl -u service-b
journalctl -u service-c
```

## Troubleshooting

### Scenario 1: Service B is Unavailable

**What happens:** Service A will fail to forward requests. Requests to `/greet-service-b` will timeout or return 500.

**Investigation steps:**

```bash
# 1. Check if Service B is running
systemctl status service-b

# 2. If it's not running, check why it crashed
journalctl -u service-b -n 50

# 3. Check for errors
journalctl -u service-b --no-pager | tail -30

# 4. Restart Service B
sudo systemctl restart service-b

# 5. Verify it's running
systemctl status service-b

# 6. Test the flow again
curl http://localhost/service-a/greet-service-b
```

**Expected logs if B is down:**
Service A logs will show:
```json
{
  "event": "downstream_call_failed",
  "target": "service-b",
  "error": "Connection refused",
  "status": 500
}
```

---

### Scenario 2: 502 Error from Nginx

**Symptoms:** `curl http://localhost/service-a/health` returns 502 or connection error

**Investigation steps:**

```bash
# 1. Check if Service A is running
systemctl status service-a

# 2. Check Service A logs for startup errors
journalctl -u service-a -n 20

# 3. Verify Service A is listening on the right port
netstat -tlnp | grep 3001

# 4. Test Service A directly (bypassing Nginx)
curl http://127.0.0.1:3001/health

# 5. Check Nginx logs
sudo tail -f /var/log/nginx/error.log

# 6. Verify Nginx config is valid
sudo nginx -t

# 7. Restart Nginx if config is valid
sudo systemctl restart nginx

# 8. Test again
curl http://localhost/service-a/health
```

**Common causes and fixes:**

| Symptom | Cause | Fix |
|---------|-------|-----|
| `curl http://127.0.0.1:3001/health` works but `curl http://localhost/service-a/health` fails | Nginx not running or misconfigured | `sudo systemctl restart nginx && sudo nginx -t` |
| `systemctl status service-a` shows failed | Service crashed on startup | `journalctl -u service-a -n 30` to see error |
| Port 3001 already in use | Another process using the port | `sudo lsof -i :3001` to find it |
| Python/Flask not installed | Missing dependencies | `pip3 install --break-system-packages flask requests` |

---

### Scenario 3: Service Discovery Failure

**Symptoms:** Service A logs show `Failed to resolve 'service-b.internal'`

**Investigation steps:**

```bash
# 1. Check /etc/hosts entries
cat /etc/hosts | grep service

# 2. Test DNS resolution manually
nslookup service-b.internal

# 3. Try ping (another test)
ping -c 1 service-b.internal

# 4. Check what should be there
cat /etc/hosts
# Should show:
# 127.0.0.1 service-a.internal
# 127.0.0.1 service-b.internal
# 127.0.0.1 service-c.internal

# 5. If missing, add them
sudo bash -c 'cat >> /etc/hosts << EOF
127.0.0.1 service-a.internal
127.0.0.1 service-b.internal
127.0.0.1 service-c.internal
EOF'

# 6. Verify they were added
cat /etc/hosts | tail -3

# 7. Test resolution again
nslookup service-b.internal

# 8. Restart services to pick up changes
sudo systemctl restart service-a service-b service-c
```

**Verify the fix:**
```bash
curl http://localhost/service-a/greet-service-b
journalctl -u service-a | tail -20
```

---

### Scenario 4: Failed Service A Startup

**Symptoms:** `systemctl status service-a` shows `failed (Result: exit-code)`

**Investigation steps:**

```bash
# 1. Check service status
systemctl status service-a

# 2. Get detailed startup logs
journalctl -u service-a -n 50 --no-pager

# 3. Check if dependencies are available
systemctl status service-b
systemctl status service-c

# 4. Check if port 3001 is in use
netstat -tlnp | grep 3001
# If something else uses it: sudo lsof -i :3001

# 5. Verify working directory exists
ls -la $(systemctl cat service-a | grep WorkingDirectory | cut -d= -f2)

# 6. Verify Python and Flask are installed
python3 --version
pip3 list | grep flask

# 7. Try running the service manually to see the real error
python3 $(systemctl cat service-a | grep ExecStart | cut -d= -f2 | awk '{print $2}')

# 8. If manual run works but systemd fails, check service file
systemctl cat service-a
```

**Common causes and fixes:**

| Cause | Fix |
|-------|-----|
| Dependencies (B, C) not started | `sudo systemctl start service-b service-c` |
| Python not installed | `sudo apt install python3 python3-pip` |
| Flask/requests not installed | `pip3 install --break-system-packages flask requests` |
| Port 3001 already in use | `sudo lsof -i :3001` and kill the process |
| Service file syntax error | `systemctl cat service-a` and fix any issues |
| Permission denied | Ensure file ownership is correct |

---

### Request Tracing Example

To troubleshoot a specific request that failed:

```bash
# 1. Trigger a request and capture the ID
RESPONSE=$(curl -s http://localhost/service-a/greet-service-b)
REQUEST_ID=$(echo $RESPONSE | jq -r .request_id)
echo "Request ID: $REQUEST_ID"

# 2. Search all service logs for this ID
echo ""
echo "=== Service A logs ==="
journalctl -u service-a | grep $REQUEST_ID

echo ""
echo "=== Service B logs ==="
journalctl -u service-b | grep $REQUEST_ID

echo ""
echo "=== Service C logs ==="
journalctl -u service-c | grep $REQUEST_ID

# 3. Analyze the flow
# Expected order:
# - A: request_received
# - B: request_received
# - C: request_received
# - C: callback_sent
# - A: callback_received
# - A: downstream_call_success

# If any service is missing logs for this ID, the request didn't reach it
```

---

### Health Check Procedure

Run this to verify everything is working:

```bash
#!/bin/bash
echo "=== System Health Check ==="

echo "Checking services..."
systemctl status service-a service-b service-c | grep -E "Active|Loaded"

echo ""
echo "Testing service health endpoints..."
echo -n "Service A: "
curl -s http://127.0.0.1:3001/health | jq .status

echo -n "Service B: "
curl -s http://127.0.0.1:3002/health | jq .status

echo -n "Service C: "
curl -s http://127.0.0.1:3003/health | jq .status

echo ""
echo "Testing full request flow..."
RESPONSE=$(curl -s http://localhost/service-a/greet-service-b)
REQUEST_ID=$(echo $RESPONSE | jq -r .request_id)
STATUS=$(echo $RESPONSE | jq -r .status)

echo "Request ID: $REQUEST_ID"
echo "Status: $STATUS"

if [ "$STATUS" == "success" ]; then
    echo "✓ Full flow works"
else
    echo "✗ Full flow failed"
    exit 1
fi

echo ""
echo "Checking service discovery..."
for SERVICE in service-a.internal service-b.internal service-c.internal; do
    if nslookup $SERVICE > /dev/null 2>&1; then
        echo "✓ $SERVICE resolves"
    else
        echo "✗ $SERVICE does not resolve"
    fi
done

echo ""
echo "Checking network isolation..."
echo -n "Service B internal access: "
curl -s http://127.0.0.1:3002/health > /dev/null && echo "✓ Works"

echo -n "Service C internal access: "
curl -s http://127.0.0.1:3003/health > /dev/null && echo "✓ Works"

echo ""
echo "=== Health check complete ==="
```

## Verification Checklist

- [ ] All three services start on boot: `sudo reboot && systemctl status service-*`
- [ ] Services restart on failure: `sudo systemctl stop service-b && sleep 5 && systemctl status service-b`
- [ ] Service A depends on B and C: `systemctl cat service-a | grep After`
- [ ] Nginx exposes only Service A: `curl http://localhost/service-a/health` works
- [ ] Services B and C not externally accessible: `curl http://<vm-ip>:3002` fails
- [ ] Full request flow works: `curl http://localhost/service-a/greet-service-b` returns success
- [ ] Request ID in all logs: Trace a request through all three services
- [ ] All logs are valid JSON: `journalctl -u service-a | head -5 | jq .`
- [ ] Service discovery works: `nslookup service-b.internal` resolves

## Deployment Notes

- Designed for **Ubuntu 24.04 LTS** on a dedicated VM
- `install.sh` auto-detects the project path — works regardless of where you clone it
- Logs accessible via `journalctl` (systemd journal) and `/var/log/nginx/access.log`
- Configuration is code: all settings in `.service` files and `nginx/default.conf`
- No databases or external dependencies required
- Services start in order: B → C → A (A requires B and C)

## Quick Commands

```bash
# Deploy
./install.sh

# Reset and redeploy
./reset.sh && sudo ./install.sh

# Check status
systemctl status service-a service-b service-c

# View logs
journalctl -u "service-*" -f

# Test flow
curl http://localhost/service-a/greet-service-b

# Restart all
sudo systemctl restart service-a service-b service-c

# Run health check
bash health-check.sh
```

---

## Running with Docker Compose

The same production flow runs in Docker Compose without any VM or systemd setup required.

### Prerequisites

- Docker Engine
- Docker Compose v2 (`docker compose` not `docker-compose`)

**Install Docker on Ubuntu:**
```bash
sudo apt install docker-compose-v2 docker.io
```

> If `docker.io` installs `podman-docker` instead of real Docker, see [Troubleshooting Docker Compose](#troubleshooting-docker-compose) below.

After install, add your user to the docker group so you don't need sudo:
```bash
sudo usermod -aG docker $USER
newgrp docker
```

Verify Docker is running:
```bash
sudo systemctl start docker
docker --version
```

**Install Docker on macOS:**
```bash
brew install --cask docker
open /Applications/Docker.app
```

**Install Docker on Windows:**

Download and install Docker Desktop from https://www.docker.com/products/docker-desktop

### Start the system

```bash
docker compose up --build -d
```

This builds all service images and starts Nginx, Service A, Service B, and Service C.

### Test the public route

```bash
curl http://localhost:8080/service-a/health
curl http://localhost:8080/service-a/greet-service-b
```

Nginx listens on port 8080 and is the only public entry point.

### Prove B and C are internal

```bash
curl --connect-timeout 3 http://localhost:3002/health   # connection refused
curl --connect-timeout 3 http://localhost:3003/health   # connection refused
```

Services B and C publish no host ports — they are reachable only inside the Docker network.

### View logs

```bash
docker compose logs -f
docker compose logs service-a
docker compose logs service-b
docker compose logs service-c
docker compose logs nginx
```

### Stop and restart a single service

```bash
docker compose stop service-b
docker compose start service-b
```

### Shut everything down

```bash
docker compose down
```

### Troubleshooting Docker Compose

**`docker compose` not found / routes to Podman**

Symptom: `Error: unrecognized command 'podman compose'`

Cause: `docker.io` installed `podman-docker` (a shim) instead of real Docker.

Fix:
```bash
sudo apt install docker-compose-v2 docker.io
```
This removes `podman-docker` and installs the real Docker engine with the Compose plugin.

---

**Docker daemon fails to start after install**

Symptom: `Job for docker.service failed` / `failed to load listeners: no sockets found via socket activation`

Cause: Leftover Podman socket state prevents Docker's socket activation from working.

Fix — start the socket unit first, then the service:
```bash
sudo systemctl stop docker.socket docker.service
sudo systemctl reset-failed docker.service docker.socket
sudo systemctl start docker.socket
sudo systemctl start docker.service
sudo systemctl status docker.service
```

---

**Permission denied on Docker socket**

Symptom: `permission denied while trying to connect to the Docker daemon socket at unix:///var/run/docker.sock`

Cause: Your user is not in the `docker` group.

Fix:
```bash
sudo usermod -aG docker $USER
newgrp docker
```

`newgrp docker` applies the group in the current shell without logging out. You only need to do this once — future shells will have it automatically.

---

### Key differences from the VM version

| VM (systemd) | Docker Compose |
|---|---|
| systemd manages services | Compose manages containers |
| `/etc/hosts` for service discovery | Compose DNS (service names) |
| `journalctl` for logs | `docker compose logs` |
| UFW + loopback binding | Docker networks + no published ports |
| Port 80 public | Port 8080 public |

See [docs/CONTAINER_VALIDATION.md](docs/CONTAINER_VALIDATION.md) for full validation evidence.


