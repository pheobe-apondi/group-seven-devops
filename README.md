# Production-Style Microservices Architecture

A complete, production-ready example of three HTTP microservices running on Linux with systemd lifecycle management, Nginx reverse proxy, structured JSON logging, distributed request tracing, and network security hardening.

---

## Table of Contents

### Quick Start
- [Overview](#overview)
- [Before You Start — Choose Your OS Setup Guide](#before-you-start--choose-your-os-setup-guide)
- [Quick Start (5 minutes)](#quick-start-5-minutes)
- [Environment Requirements](#environment-requirements)

### Architecture & Design
- [System Architecture](#system-architecture)
- [Service Responsibilities](#service-responsibilities)
- [Data Flow](#data-flow)
- [Network Security](#network-security)
- [Service Discovery](#service-discovery)
- [Request Tracing](#request-tracing)

### Deployment
- [Host Deployment (Systemd)](#host-deployment-systemd)
- [Container Deployment (Docker)](#container-deployment-docker)
- [Manual Installation Steps](#manual-installation-steps)

### Operations
- [Service Management](#service-management)
- [Viewing Logs](#viewing-logs)
- [Health Checks](#health-checks)
- [Verification Steps](#verification-steps)

### Development & API
- [API Endpoints](#api-endpoints)
- [Request Flow Example](#request-flow-example)
- [Structured Logging Format](#structured-logging-format)

### Troubleshooting
- [Common Issues](#common-issues)
- [Troubleshooting Guide](#troubleshooting-guide)
- [Service Recovery](#service-recovery)

### CI/CD
- [GitHub Actions Pipeline](#github-actions-pipeline)
- [Docker Image Publishing](#docker-image-publishing)
- [Container CI/CD Deployment](#container-cicd-deployment)
- [How to Test This Deployment](#how-to-test-this-deployment)

---

## Overview

This project demonstrates a production-ready microservices system with:

- **Three independent HTTP services** (A, B, C) communicating via internal networks
- **Nginx reverse proxy** as the sole public entry point (port 80)
- **Linux systemd** for service lifecycle management and automatic restart
- **Structured JSON logging** for production-grade observability
- **Distributed request tracing** via unique request IDs propagated across all services
- **Network security hardening** with loopback binding and firewall rules
- **Service discovery** via DNS names instead of hardcoded IPs
- **CI/CD automation** with GitHub Actions, Docker image publishing, and deployment scripts

**Use this project to learn:**
- How microservices communicate in a controlled network
- Why request tracing is essential for debugging distributed systems
- How to secure internal services from external access
- How systemd manages long-running services
- How to implement production-grade logging

---

<details>
<summary><strong>Before You Start — Choose Your OS Setup Guide</strong> (click to expand)</summary>

## Before You Start — Choose Your OS Setup Guide

**⚠️ Important:** This project runs on **Ubuntu 24.04 LTS** inside a dedicated VM. Do not run it on a shared or existing VM — `install.sh` writes to `/etc/hosts`, installs systemd units, and modifies Nginx config.

The original development environment was a fresh Ubuntu 24.04 LTS instance with no prior services installed. Replicate that baseline before running the installer.

**Pick your host OS to get started:**

| Host OS | Setup Guide |
|---|---|
| macOS | [docs/setup-macos.md](docs/setup-macos.md) |
| Linux | [docs/setup-linux.md](docs/setup-linux.md) |
| Windows | [docs/setup-windows.md](docs/setup-windows.md) |

These guides walk through creating a fresh Ubuntu 24.04 LTS VM (or WSL) with the correct baseline.

---

</details>

<details>
<summary><strong>Quick Start (5 minutes)</strong> (click to expand)</summary>

## Quick Start (5 minutes)

### Prerequisites
- **Ubuntu 24.04 LTS** (fresh install, dedicated VM recommended)
- SSH access to the VM
- Internet connectivity

### Clone and Deploy

```bash
# 1. Clone the repository
git clone https://github.com/pheobe-apondi/group-seven-devops.git
cd group-seven-devops

# 2. Run the automated installer
sudo ./install.sh

# 3. Verify all services are running
systemctl status service-a service-b service-c

# 4. Make a test request (triggers full flow)
curl http://localhost/service-a/greet-service-b

# 5. View the request trace
tail -f /var/log/nginx/access.json &
journalctl -u service-a -f &
```

**Expected output:**
- Nginx trace log shows incoming request with a `request_id`
- Service A receives the request and forwards to B
- Service B forwards to C
- Service C sends a callback to A
- All logs show the same `request_id` for traceability

### Reset to Clean State

If anything goes wrong:

```bash
# Complete reset
./reset.sh

# Reinstall fresh
sudo ./install.sh
```

---

</details>

<details>
<summary><strong>Environment Requirements</strong> (click to expand)</summary>

## Environment Requirements

### Host OS
- **Ubuntu 24.04 LTS** (tested and verified)
- A dedicated VM (do not run on a shared system)
- `install.sh` modifies `/etc/hosts`, installs systemd units, and configures Nginx

### Minimum System Resources
- 1 GB RAM
- 1 CPU
- 5 GB disk space

### Required Packages (auto-installed by install.sh)
- `python3` (3.12+)
- `python3-pip`
- `nginx`
- `ufw` (firewall)

### Python Dependencies
- `flask` (web framework)
- `requests` (HTTP client)

See [requirements.txt](requirements.txt) for pinned versions.

---

</details>

<details>
<summary><strong>System Architecture</strong> (click to expand)</summary>

## System Architecture

### High-Level Diagram

```
┌─────────────────┐
│ Internet Client │
└────────┬────────┘
         │ HTTP request (port 80)
         ▼
    ┌─────────────────────┐
    │  Nginx (port 80)    │
    │  Reverse Proxy      │
    │  Request Tracer     │
    │  (PUBLIC)           │
    └──────────┬──────────┘
               │ Forward to Service A
               ▼
         ┌──────────────────┐
         │  Service A:3001  │
         │  Entry point     │
         │  (INTERNAL)      │
         └────────┬─────────┘
                  │ Call Service B
                  ▼
         ┌──────────────────┐
         │  Service B:3002  │
         │  Middleware      │
         │  (INTERNAL)      │
         └────────┬─────────┘
                  │ Call Service C
                  ▼
         ┌──────────────────┐
         │  Service C:3003  │
         │  Terminal service│
         │  (INTERNAL)      │
         └────────┬─────────┘
                  │ Callback to A
                  ▼
         ┌──────────────────┐
         │  Service A:3001  │
         │  /greeting-rcvd  │
         └──────────────────┘
```

### Service Topology

```
Network Isolation:
┌─────────────────────────────────────────────┐
│ Host firewall (UFW)                         │
│ ✓ Port 80/tcp (Nginx) — ALLOWED            │
│ ✗ Port 3001 — BLOCKED                      │
│ ✗ Port 3002 — BLOCKED                      │
│ ✗ Port 3003 — BLOCKED                      │
└──────────────────┬──────────────────────────┘
                   │
          ┌────────┴─────────┐
          │ Loopback Network │
          │ 127.0.0.1 only   │
          └────────┬─────────┘
                   │
    ┌──────────────┼──────────────┐
    │              │              │
Service A       Service B      Service C
:3001           :3002          :3003
(External      (Internal      (Internal
 via Nginx)     only)          only)
```

### Service Responsibilities

#### Service A (port 3001) — Entry Point
- **Exposes HTTP endpoints:**
  - `GET /health` — Health check
  - `GET /greet-service-b` — Trigger full flow
  - `POST /greeting-rcvd` — Receive callback from Service C
- **Initiates the flow:** Receives requests from Nginx, calls Service B
- **Receives callbacks:** Service C sends completion status back to A
- **Request tracking:** Generates or propagates X-Request-ID
- **Logging:** Structured JSON logs of all events

#### Service B (port 3002) — Middleware
- **Exposes HTTP endpoints:**
  - `GET /health` — Health check
  - `GET /greet` — Receive request from Service A
- **Forwards requests:** Accepts incoming from A, calls Service C
- **No persistence:** Does not store state between requests
- **Logging:** Structured JSON logs including request_id

#### Service C (port 3003) — Terminal Service
- **Exposes HTTP endpoints:**
  - `GET /health` — Health check
  - `GET /greet-c` — Receive request from Service B
- **Sends callbacks:** Posts completion status back to Service A
- **Logging:** Structured JSON logs including request_id and callback status

---

</details>

<details>
<summary><strong>Data Flow</strong> (click to expand)</summary>

## Data Flow

### Example: Request Lifecycle

```
1. Client makes HTTP request
   → GET /service-a/greet-service-b

2. Nginx receives the request (port 80)
   → Generates/propagates X-Request-ID
   → Logs to /var/log/nginx/access.json
   → Forwards to Service A (127.0.0.1:3001)

3. Service A processes the request
   → Receives X-Request-ID from Nginx headers
   → Logs "request_received" event
   → Calls Service B on http://service-b.internal:3002/greet
   → Propagates X-Request-ID to Service B
   → Logs "downstream_call_success"
   → Waits for callback from Service C (with timeout)

4. Service B processes the request
   → Receives X-Request-ID from Service A
   → Logs "request_received" event
   → Calls Service C on http://service-c.internal:3003/greet-c
   → Propagates X-Request-ID to Service C
   → Logs "request_forwarded"
   → Returns immediately to Service A

5. Service C processes the request
   → Receives X-Request-ID from Service B
   → Logs "request_received" event
   → Sends callback POST to Service A:/greeting-rcvd
   → Includes X-Request-ID in callback
   → Logs "callback_sent"
   → Returns response to Service B

6. Service A receives callback
   → Receives POST to /greeting-rcvd with X-Request-ID
   → Logs "callback_received"
   → Signals waiting handler
   → Returns 200 OK to original client
   → Logs "request_complete"

7. Client receives response
   → HTTP 200 OK with request_id in body
   → Can use request_id to trace through all logs
```

### Request ID Flow

Every request has a unique `X-Request-ID` header:

```
Nginx generates or propagates:
    X-Request-ID: a3b9d61f-22f2-48f1-91f8-bcb6d7b91b21

The same ID flows through:
    Nginx access log
    Service A logs
    Service B logs
    Service C logs
    Service A callback logs
    Nginx error logs (if applicable)

Allows complete tracing via:
    grep "a3b9d61f-22f2-48f1-91f8-bcb6d7b91b21" /var/log/nginx/access.json
    journalctl | grep "a3b9d61f-22f2-48f1-91f8-bcb6d7b91b21"
```

---

</details>

<details>
<summary><strong>Network Security</strong> (click to expand)</summary>

## Network Security

### Security Layers

**Layer 1: Host Firewall (UFW)**
- Only port 80 (Nginx) is exposed to the public internet
- Ports 3001, 3002, 3003 are blocked by firewall
- Even if a service misconfigures and listens on 0.0.0.0, the firewall prevents external access

**Layer 2: Loopback Binding**
- Each service binds to `127.0.0.1` only (loopback interface)
- The OS kernel prevents non-loopback connections from reaching the service
- Service B and C cannot receive connections from external IPs even if firewall fails

**Layer 3: Application Logic**
- Nginx is the only public entry point
- Nginx only forwards traffic to Service A
- Services B and C are not mentioned in Nginx config

**Why Multiple Layers?**
These protections are independent. Even if one layer fails:
- Firewall fails? → Loopback binding still protects
- Loopback binding misconfigured? → Firewall still blocks
- Nginx misconfigured? → Firewall + loopback still block direct access

### Verify Security

```bash
# 1. Check firewall status
sudo ufw status

# Expected output:
#   Port 80                    ALLOW
#   3001                       (not listed)
#   3002                       (not listed)
#   3003                       (not listed)

# 2. Check loopback binding
ss -tlnp | grep -E ':(3001|3002|3003)'

# Expected output:
#   LISTEN 127.0.0.1:3001
#   LISTEN 127.0.0.1:3002
#   LISTEN 127.0.0.1:3003
#
# Should NOT show 0.0.0.0 or :::

# 3. Verify external access is blocked (from outside the VM)
curl http://<vm-ip>:3002      # Connection refused
curl http://<vm-ip>:3003      # Connection refused
curl http://<vm-ip>/service-a/health  # Works (via Nginx)
```

---

</details>

<details>
<summary><strong>Service Discovery</strong> (click to expand)</summary>

## Service Discovery

### How Services Find Each Other

Services communicate using hostnames instead of hardcoded IPs:

```python
# ✓ Good — uses hostname
requests.get('http://service-b.internal:3002/greet')

# ✗ Bad — hardcoded IP (breaks if IP changes)
requests.get('http://192.168.1.100:3002/greet')
```

### DNS Resolution Method

Services resolve names via `/etc/hosts`:

```bash
# View service discovery entries
cat /etc/hosts | grep service

# Output:
# 127.0.0.1 service-a.internal
# 127.0.0.1 service-b.internal
# 127.0.0.1 service-c.internal
```

The kernel resolver reads `/etc/hosts` before querying DNS, so all services immediately know about each other.

### Testing Service Discovery

```bash
# From any service or host:
nslookup service-b.internal
# Should resolve to 127.0.0.1

curl http://service-b.internal:3002/health
# Should return 200 OK with health status

# If resolution fails:
cat /etc/hosts | grep service  # Check entries exist
sudo systemctl restart service-a service-b service-c  # Restart may be needed
```

---

</details>

<details>
<summary><strong>Request Tracing</strong> (click to expand)</summary>

## Request Tracing

### Structured Logging Format

All services produce structured JSON logs:

```json
{
  "timestamp": "2025-01-01T10:00:00Z",
  "service": "service-a",
  "event": "request_received",
  "request_id": "abc-123-def-456",
  "method": "GET",
  "path": "/greet-service-b",
  "status": 200
}
```

### Nginx Trace Logs

Nginx access logs in JSON format to `/var/log/nginx/access.json`:

```json
{
  "timestamp": "2025-01-01T10:00:00Z",
  "service": "nginx",
  "request_id": "abc-123-def-456",
  "event": "request_received",
  "method": "GET",
  "path": "/service-a/greet-service-b",
  "status": 200,
  "bytes_sent": 1234,
  "remote_addr": "203.0.113.45",
  "upstream": "127.0.0.1:3001",
  "request_time": 0.045,
  "upstream_time": "0.042",
  "upstream_status": "200"
}
```

### Tracing a Single Request

```bash
# 1. Make a request and capture the response
RESPONSE=$(curl http://localhost/service-a/greet-service-b)
REQUEST_ID=$(echo "$RESPONSE" | jq -r '.request_id')
echo "Request ID: $REQUEST_ID"

# 2. Find request in Nginx logs
echo "=== Nginx ==="
grep "$REQUEST_ID" /var/log/nginx/access.json | jq .

# 3. Find request in Service A logs
echo "=== Service A ==="
journalctl -u service-a -e | grep "$REQUEST_ID"

# 4. Find request in Service B logs
echo "=== Service B ==="
journalctl -u service-b -e | grep "$REQUEST_ID"

# 5. Find request in Service C logs
echo "=== Service C ==="
journalctl -u service-c -e | grep "$REQUEST_ID"
```

---

</details>

<details>
<summary><strong>Host Deployment (Systemd)</strong> (click to expand)</summary>

## Host Deployment (Systemd)

### Automated Installation

```bash
git clone https://github.com/pheobe-apondi/group-seven-devops.git
cd group-seven-devops
sudo ./install.sh
```

The `install.sh` script handles:
- ✓ System dependency installation (Python, Nginx, UFW)
- ✓ Service discovery setup (/etc/hosts)
- ✓ Systemd service file creation with proper paths
- ✓ Nginx configuration
- ✓ Firewall setup
- ✓ Service startup (in correct dependency order)
- ✓ Verification of all services

### Manual Installation Steps

If you prefer to install manually:

```bash
export PROJECT_DIR=$(pwd)

# 1. Install system packages
sudo apt update
sudo apt install -y python3 python3-pip nginx ufw

# 2. Install Python dependencies
pip3 install --break-system-packages flask requests

# 3. Add service discovery entries
sudo bash -c 'cat >> /etc/hosts << EOF
127.0.0.1 service-a.internal
127.0.0.1 service-b.internal
127.0.0.1 service-c.internal
EOF'

# 4. Create systemd service files
# (See .service files in systemd/ directory and update PROJECT_DIR)

sudo cp systemd/service-a.service /etc/systemd/system/
sudo cp systemd/service-b.service /etc/systemd/system/
sudo cp systemd/service-c.service /etc/systemd/system/

# 5. Configure Nginx
sudo cp nginx/default.conf /etc/nginx/sites-available/default
sudo nginx -t
sudo systemctl restart nginx

# 6. Configure firewall
sudo ufw default deny incoming
sudo ufw default allow outgoing
sudo ufw allow 80/tcp
sudo ufw --force enable

# 7. Start services (order matters!)
sudo systemctl daemon-reload
sudo systemctl enable service-a service-b service-c
sudo systemctl start service-b service-c service-a

# 8. Verify
curl http://localhost/service-a/health
```

---

</details>

## Container Deployment (Docker)

### Installing Docker

**Ubuntu:**
```bash
sudo apt install docker-compose-v2 docker.io
sudo usermod -aG docker $USER
newgrp docker
sudo systemctl start docker
docker --version
```
> If `docker.io` installs `podman-docker` instead of real Docker, see [Troubleshooting Docker Compose](#troubleshooting-guide) below.

**macOS:**
```bash
brew install --cask docker
open /Applications/Docker.app
```

**Windows:** Download and install [Docker Desktop](https://www.docker.com/products/docker-desktop).

### Using Docker Compose (Development)

```bash
# Build all services
docker compose build

# Start the stack
docker compose up -d

# Verify
docker compose ps
curl http://localhost:8080/service-a/health

# View logs
docker compose logs -f service-a
docker compose logs -f service-b
docker compose logs -f service-c

# Stop
docker compose down -v
```

Nginx listens on port 8080 and is the only public entry point. Confirm B and C stay internal:

```bash
curl --connect-timeout 3 http://localhost:3002/health   # connection refused
curl --connect-timeout 3 http://localhost:3003/health   # connection refused
```

### Using Docker Compose (Production)

Production deployment uses pre-built images from Docker Hub:

```bash
# Set environment variables
export DOCKERHUB_USERNAME=<your-username>
export APP_NAME=group-seven-devops
export IMAGE_TAG=sha-a1b2c3d  # Use specific commit hash

# Create .env file
cp .env.example .env
cat > .env << EOF
DOCKERHUB_USERNAME=$DOCKERHUB_USERNAME
APP_NAME=$APP_NAME
IMAGE_TAG=$IMAGE_TAG
EOF

# Deploy
./scripts/deploy.sh $IMAGE_TAG

# Verify
docker compose -f docker-compose.prod.yml ps
curl http://localhost:8080/service-a/health

# View logs
docker compose -f docker-compose.prod.yml logs -f
```

### Building and Publishing Images

Images are automatically built and published by GitHub Actions on push to main:

```bash
# Latest image tags (from CI/CD):
# docker.io/your-username/group-seven-devops-service-a:sha-a1b2c3d
# docker.io/your-username/group-seven-devops-service-b:sha-a1b2c3d
# docker.io/your-username/group-seven-devops-service-c:sha-a1b2c3d

# Pull and run a specific version
docker pull your-username/group-seven-devops-service-a:sha-a1b2c3d
docker run -p 3001:3001 your-username/group-seven-devops-service-a:sha-a1b2c3d
```

### Key Differences from the Systemd Host Deployment

| VM (systemd) | Docker Compose |
|---|---|
| systemd manages services | Compose manages containers |
| `/etc/hosts` for service discovery | Compose DNS (service names) |
| `journalctl` for logs | `docker compose logs` |
| UFW + loopback binding | Docker networks + no published ports |
| Port 80 public | Port 8080 public |

See [docs/CONTAINER_VALIDATION.md](docs/CONTAINER_VALIDATION.md) for full validation evidence.

---

## Container CI/CD Deployment

### Latest deployed version

Commit:
`9ff648faedc5b00aaa536f32c358613c1b4bf033`

Image tag:
`sha-9ff648f`

Images:
- `pheobeapondi/group-seven-devops-service-a:sha-9ff648f`
- `pheobeapondi/group-seven-devops-service-b:sha-9ff648f`
- `pheobeapondi/group-seven-devops-service-c:sha-9ff648f`

Published by GitHub Actions run: https://github.com/pheobe-apondi/group-seven-devops/actions/runs/28684908600

### Deploy

```bash
cp .env.example .env
export DOCKERHUB_USERNAME=pheobeapondi
export APP_NAME=group-seven-devops
./scripts/deploy.sh sha-9ff648f
```

### Verify

```bash
docker compose -f docker-compose.prod.yml ps
curl http://localhost:8080/service-a/health
```

### How to Test This Deployment

These are the exact commands to independently verify the published images and the deployment, using the current version above.

**1. Pull the images directly (proves they're on Docker Hub, no local build needed):**
```bash
docker pull pheobeapondi/group-seven-devops-service-a:sha-9ff648f
docker pull pheobeapondi/group-seven-devops-service-b:sha-9ff648f
docker pull pheobeapondi/group-seven-devops-service-c:sha-9ff648f
```

**2. Inspect image metadata (proves commit traceability via labels):**
```bash
docker image inspect pheobeapondi/group-seven-devops-service-a:sha-9ff648f \
  | jq '.[] | {Labels: .Config.Labels}'
# Expect org.opencontainers.image.revision == 9ff648faedc5b00aaa536f32c358613c1b4bf033
```

**3. Validate the production Compose file (proves it uses `image:`, not `build:`):**
```bash
git clone https://github.com/pheobe-apondi/group-seven-devops.git
cd group-seven-devops
cp .env.example .env
export DOCKERHUB_USERNAME=pheobeapondi
export APP_NAME=group-seven-devops
export IMAGE_TAG=sha-9ff648f
docker compose -f docker-compose.prod.yml config
```

**4. Deploy and verify the running stack:**
```bash
./scripts/deploy.sh sha-9ff648f
docker compose -f docker-compose.prod.yml ps
curl http://localhost:8080/service-a/health
```

**5. Confirm only Nginx is reachable from the host (network isolation):**
```bash
curl --connect-timeout 3 http://localhost:3002/health   # should refuse
curl --connect-timeout 3 http://localhost:3003/health   # should refuse
```

**6. Confirm the deploy script rejects a missing tag:**
```bash
./scripts/deploy.sh            # should exit 1 with a usage message
```

**7. Tear down:**
```bash
docker compose -f docker-compose.prod.yml down -v
```

---

<details>
<summary><strong>Service Management</strong> (click to expand)</summary>

## Service Management

### Start Services

```bash
# Start all services
sudo systemctl start service-a service-b service-c

# Start individually
sudo systemctl start service-a
sudo systemctl start service-b
sudo systemctl start service-c

# Start and enable for boot
sudo systemctl enable service-a service-b service-c
sudo systemctl start service-a service-b service-c
```

### Stop Services

```bash
# Stop all services
sudo systemctl stop service-a service-b service-c

# Stop individually
sudo systemctl stop service-b
```

### Restart Services

```bash
# Restart all services
sudo systemctl restart service-a service-b service-c

# Restart individually
sudo systemctl restart service-a
```

### Check Status

```bash
# Status of all services
systemctl status service-a service-b service-c

# Detailed status
sudo systemctl status service-a -l

# Enabled status (for boot)
sudo systemctl is-enabled service-a
```

### Automatic Restart on Failure

All services are configured with `Restart=on-failure` in their systemd units. If a service crashes:

```bash
# Kill a service to trigger automatic restart
sudo kill $(pgrep -f service_b.py)

# Wait a few seconds
sleep 5

# Check status (should show active again)
systemctl status service-b
```

---

</details>

<details>
<summary><strong>Viewing Logs</strong> (click to expand)</summary>

## Viewing Logs

### Service Logs (Systemd Journal)

```bash
# View logs for Service A (live, follow mode)
journalctl -u service-a -f

# View logs for all services
journalctl -u "service-*" -f

# View last N lines
journalctl -u service-a -n 50

# View logs from last hour
journalctl -u service-a --since "1 hour ago"

# View logs for a specific time range
journalctl -u service-a --since "2025-01-01 10:00:00" --until "2025-01-01 11:00:00"

# Search logs for a specific request_id
journalctl | grep "abc-123-def-456"
```

### Nginx Logs

```bash
# Nginx access log (JSON, includes request tracing)
tail -f /var/log/nginx/access.json

# Pretty-print JSON logs
tail -f /var/log/nginx/access.json | jq .

# Find specific request_id in Nginx logs
grep "request_id" /var/log/nginx/access.json | jq 'select(.request_id == "abc-123")'

# Nginx error log
tail -f /var/log/nginx/error.json | jq .

# Check log rotation status
sudo logrotate -d /etc/logrotate.d/nginx-json
```

---

</details>

<details>
<summary><strong>Health Checks</strong> (click to expand)</summary>

## Health Checks

### Public Health Check (via Nginx)

```bash
curl http://localhost/service-a/health

# Expected response:
# {
#   "service": "service-a",
#   "status": "healthy",
#   "port": 3001,
#   "message": "Hello service-a listening on 3001"
# }
```

### Internal Health Checks (direct)

```bash
# Service A
curl http://service-a.internal:3001/health

# Service B
curl http://service-b.internal:3002/health

# Service C
curl http://service-c.internal:3003/health
```

### Monitor Health in Real-Time

```bash
# Monitor all three services
while true; do
  echo "=== Service A ==="
  curl -s http://localhost/service-a/health | jq .
  
  echo "=== Service B ==="
  curl -s http://service-b.internal:3002/health | jq .
  
  echo "=== Service C ==="
  curl -s http://service-c.internal:3003/health | jq .
  
  sleep 5
done
```

---

</details>

<details>
<summary><strong>Verification Steps</strong> (click to expand)</summary>

## Verification Steps

### Complete System Verification

```bash
# 1. Check all services are running
echo "=== Service Status ==="
systemctl status service-a service-b service-c

# 2. Check health endpoints
echo "=== Health Checks ==="
curl -s http://localhost/service-a/health | jq .
curl -s http://service-b.internal:3002/health | jq .
curl -s http://service-c.internal:3003/health | jq .

# 3. Check port bindings
echo "=== Port Bindings ==="
ss -tlnp | grep -E ':(3001|3002|3003|80)'

# 4. Check firewall rules
echo "=== Firewall Rules ==="
sudo ufw status

# 5. Check service discovery
echo "=== Service Discovery ==="
cat /etc/hosts | grep service

# 6. Make a test request
echo "=== Test Request ==="
curl -s http://localhost/service-a/greet-service-b | jq .

# 7. Trace request through logs
echo "=== Request Trace ==="
REQUEST_ID=$(curl -s http://localhost/service-a/greet-service-b | jq -r '.request_id')
echo "Request ID: $REQUEST_ID"
echo "Nginx logs:"
grep "$REQUEST_ID" /var/log/nginx/access.json | jq .
echo "Service A logs:"
journalctl -u service-a -e | grep "$REQUEST_ID"
```

---

</details>

<details>
<summary><strong>API Endpoints</strong> (click to expand)</summary>

## API Endpoints

### Service A — Entry Point

**`GET /health`** — Health check
```bash
curl http://localhost/service-a/health
```

**`GET /greet-service-b`** — Trigger full request flow
```bash
curl http://localhost/service-a/greet-service-b
```

**`POST /greeting-rcvd`** — Receive callback from Service C (internal)
```bash
curl -X POST http://localhost/service-a/greeting-rcvd \
  -H "Content-Type: application/json" \
  -d '{
    "request_id": "abc-123",
    "source_service": "service-c",
    "message": "Greeting processed",
    "timestamp": "2025-01-01T10:00:00Z"
  }'
```

### Service B — Middleware

**`GET /health`** — Health check (internal only)
```bash
curl http://service-b.internal:3002/health
```

**`GET /greet`** — Receive request from Service A (internal only)
```bash
curl -H "X-Request-ID: abc-123" http://service-b.internal:3002/greet
```

### Service C — Terminal Service

**`GET /health`** — Health check (internal only)
```bash
curl http://service-c.internal:3003/health
```

**`GET /greet-c`** — Receive request from Service B (internal only)
```bash
curl -H "X-Request-ID: abc-123" http://service-c.internal:3003/greet-c
```

---

</details>

<details>
<summary><strong>Request Flow Example</strong> (click to expand)</summary>

## Request Flow Example

### Step-by-Step Walkthrough

```bash
# 1. Make the request
REQUEST=$(curl http://localhost/service-a/greet-service-b)
echo "$REQUEST" | jq .

# Output:
# {
#   "request_id": "a3b9d61f-22f2-48f1-91f8-bcb6d7b91b21",
#   "status": "success",
#   "message": "Request completed successfully"
# }

# 2. Extract the request_id
REQUEST_ID="a3b9d61f-22f2-48f1-91f8-bcb6d7b91b21"

# 3. Find in Nginx logs (where Nginx received it)
echo "=== Nginx received ==="
grep "$REQUEST_ID" /var/log/nginx/access.json | jq .

# 4. Find in Service A logs (where it handled the request)
echo "=== Service A processed ==="
journalctl -u service-a -e | grep "$REQUEST_ID" | head -2

# 5. Find in Service B logs (where it forwarded)
echo "=== Service B forwarded ==="
journalctl -u service-b -e | grep "$REQUEST_ID"

# 6. Find in Service C logs (where it processed)
echo "=== Service C processed ==="
journalctl -u service-c -e | grep "$REQUEST_ID"

# 7. Find callback in Service A (where it received response)
echo "=== Service A received callback ==="
journalctl -u service-a -e | grep "$REQUEST_ID" | tail -1
```

---

</details>

<details>
<summary><strong>Structured Logging Format</strong> (click to expand)</summary>

## Structured Logging Format

### Standard Log Entry Fields

All structured logs include:

| Field | Type | Purpose |
|-------|------|---------|
| `timestamp` | ISO 8601 | When the event occurred |
| `service` | string | Which service logged this ("nginx", "service-a", "service-b", "service-c") |
| `event` | string | Type of event ("request_received", "request_forwarded", "callback_sent", etc.) |
| `request_id` | string | Unique ID for tracing (propagated through entire flow) |
| `method` | string | HTTP method (GET, POST) |
| `path` | string | Request path ("/greet", "/greeting-rcvd") |
| `status` | integer | HTTP status code (200, 404, 500) |
| `upstream` | string | (Nginx only) Upstream service that handled the request |
| `request_time` | float | (Nginx only) Total time spent (seconds) |

### Example Log Entries

**Nginx receiving request:**
```json
{
  "timestamp": "2025-01-01T10:00:00.123Z",
  "service": "nginx",
  "request_id": "a3b9d61f-22f2-48f1-91f8-bcb6d7b91b21",
  "event": "request_received",
  "method": "GET",
  "path": "/service-a/greet-service-b",
  "status": 200,
  "bytes_sent": 156,
  "remote_addr": "203.0.113.45",
  "upstream": "127.0.0.1:3001",
  "request_time": 0.045,
  "upstream_time": "0.042"
}
```

**Service A processing request:**
```json
{
  "timestamp": "2025-01-01T10:00:00.125Z",
  "service": "service-a",
  "event": "request_received",
  "request_id": "a3b9d61f-22f2-48f1-91f8-bcb6d7b91b21",
  "method": "GET",
  "path": "/greet-service-b",
  "status": 200
}
```

**Service C sending callback:**
```json
{
  "timestamp": "2025-01-01T10:00:00.168Z",
  "service": "service-c",
  "event": "callback_sent",
  "request_id": "a3b9d61f-22f2-48f1-91f8-bcb6d7b91b21",
  "target": "service-a",
  "status": 200
}
```

---

</details>

<details>
<summary><strong>Common Issues</strong> (click to expand)</summary>

## Common Issues

### Services Don't Start

**Problem:** `systemctl status service-a` shows `failed` or `inactive`

**Solutions:**
```bash
# 1. Check if Python is installed
python3 --version

# 2. Check if dependencies are installed
pip3 list | grep -E "flask|requests"

# 3. Check service file syntax
sudo systemctl status service-a -l

# 4. View the actual error
journalctl -u service-a -n 20

# 5. Try starting manually to see the error
cd ~/group-seven-devops
python3 services/service-a/service_a.py --loopback

# 6. Check if ports are already in use
ss -tlnp | grep -E ':(3001|3002|3003)'

# 7. Reset and reinstall
./reset.sh
sudo ./install.sh
```

### Requests Timeout or Fail

**Problem:** `curl http://localhost/service-a/greet-service-b` times out

**Solutions:**
```bash
# 1. Check if Nginx is running
systemctl status nginx

# 2. Check if Service A is running
systemctl status service-a

# 3. Check Nginx configuration
sudo nginx -t

# 4. Check Nginx logs for errors
tail -f /var/log/nginx/error.json

# 5. Test Service A directly
curl http://service-a.internal:3001/health

# 6. Check if all services are running
systemctl status service-a service-b service-c

# 7. Check service discovery
nslookup service-b.internal
```

### Can Access Service B or C from Outside

**Problem:** Can reach ports 3001, 3002, 3003 from external IP

**Solutions:**
```bash
# 1. Check firewall status
sudo ufw status
# Should show port 80 ALLOW, not 3001/3002/3003

# 2. Enable firewall if disabled
sudo ufw --force enable

# 3. Check loopback binding
ss -tlnp | grep -E ':(3001|3002|3003)'
# Should show 127.0.0.1, not 0.0.0.0

# 4. Restart services with loopback flag
sudo systemctl restart service-a service-b service-c

# 5. Verify from outside (should fail)
curl http://<vm-ip>:3002  # Should say "Connection refused"
```

### Logs Don't Show Request ID

**Problem:** Logs don't have `request_id` field

**Solutions:**
```bash
# 1. Check service code includes X-Request-ID handling
grep -n "X-Request-ID" services/service-a/service_a.py

# 2. Check Nginx is propagating the header
grep -n "X-Request-ID" nginx/default.conf

# 3. Check logs are actually structured JSON
tail -1 /var/log/nginx/access.json | jq .

# 4. Make sure you're looking at new requests (old logs won't have it)
# Clear old logs and make a fresh request
sudo rm /var/log/nginx/access.json
curl http://localhost/service-a/greet-service-b
cat /var/log/nginx/access.json | jq .
```

---

</details>

<details>
<summary><strong>Troubleshooting Guide</strong> (click to expand)</summary>

## Troubleshooting Guide

### Issue: One Service Crashes

**Steps to Diagnose:**

```bash
# 1. Check which service crashed
systemctl status service-a service-b service-c

# 2. View the recent logs
journalctl -u service-b -n 50

# 3. Look for Python exceptions
journalctl -u service-b | tail -20 | grep -i "error\|exception\|traceback"
```

**Steps to Recover:**

```bash
# 1. Restart the failed service
sudo systemctl restart service-b

# 2. Verify it's running
systemctl status service-b

# 3. Verify the full flow works
curl http://localhost/service-a/greet-service-b
```

### Issue: Service Discovery Fails

**Steps to Diagnose:**

```bash
# 1. Check /etc/hosts
cat /etc/hosts | grep service

# 2. Test DNS resolution
nslookup service-b.internal
dig service-b.internal

# 3. Try accessing by IP
curl http://127.0.0.1:3002/health

# 4. Check service is listening
ss -tlnp | grep 3002
```

**Steps to Recover:**

```bash
# 1. Verify /etc/hosts is correct
sudo cat /etc/hosts | grep service

# 2. If missing, add entries
sudo bash -c 'cat >> /etc/hosts << EOF
127.0.0.1 service-a.internal
127.0.0.1 service-b.internal
127.0.0.1 service-c.internal
EOF'

# 3. Clear DNS cache (if using systemd-resolved)
sudo systemctl restart systemd-resolved

# 4. Test again
nslookup service-b.internal
```

### Issue: Network Security Concerns

**Verify No External Access:**

```bash
# From an external machine:
curl http://<vm-ip>:3002  # Should fail with "Connection refused"
curl http://<vm-ip>:3003  # Should fail with "Connection refused"
curl http://<vm-ip>/service-a/health  # Should work

# From the VM itself:
curl http://localhost:3002/health  # Works (loopback)
curl http://localhost:3003/health  # Works (loopback)
```

**If External Access Works (Security Issue):**

```bash
# 1. Check firewall is enabled
sudo ufw status

# 2. If disabled, enable it
sudo ufw --force enable

# 3. Check firewall rules
sudo ufw status verbose

# 4. Check service bindings (should be 127.0.0.1)
ss -tlnp | grep -E ':(3001|3002|3003)'

# If showing 0.0.0.0, restart services:
sudo systemctl restart service-a service-b service-c
```

### Issue: `docker compose` Not Found / Routes to Podman

Symptom: `Error: unrecognized command 'podman compose'`

Cause: `docker.io` installed `podman-docker` (a shim) instead of real Docker.

Fix:
```bash
sudo apt install docker-compose-v2 docker.io
```
This removes `podman-docker` and installs the real Docker engine with the Compose plugin.

### Issue: Docker Daemon Fails to Start After Install

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

### Issue: Permission Denied on Docker Socket

Symptom: `permission denied while trying to connect to the Docker daemon socket at unix:///var/run/docker.sock`

Cause: Your user is not in the `docker` group.

Fix:
```bash
sudo usermod -aG docker $USER
newgrp docker
```

`newgrp docker` applies the group in the current shell without logging out — you only need to do this once.

---

</details>

<details>
<summary><strong>Service Recovery</strong> (click to expand)</summary>

## Service Recovery

### Automatic Recovery

All services are configured with systemd's `Restart=on-failure` policy. If a service crashes:

1. Systemd detects the crash
2. Waits 5 seconds (`RestartSec=5s`)
3. Automatically restarts the service
4. Repeats if necessary

### Manual Recovery

```bash
# Option 1: Restart the service
sudo systemctl restart service-a

# Option 2: Stop and start (cleaner)
sudo systemctl stop service-a
sleep 2
sudo systemctl start service-a

# Option 3: Restart all services
sudo systemctl restart service-a service-b service-c

# Option 4: Complete reset
./reset.sh
sudo ./install.sh
```

### Verify Recovery

```bash
# Check status
systemctl status service-a

# Make a test request
curl http://localhost/service-a/greet-service-b

# View recent logs
journalctl -u service-a -n 10
```

---

</details>

## GitHub Actions Pipeline

### Overview

The CI/CD pipeline ([.github/workflows/container-ci-cd.yml](.github/workflows/container-ci-cd.yml)) automates testing, building, and publishing of Docker images. It runs on:
- Every **pull request** to main (validation only)
- Every **push** to main (validation + publish)
- Manual triggers via **workflow_dispatch**

### Pipeline Architecture

```
GitHub Event
    ↓
1. Verify Job (Matrix: 3 services in parallel)
   ├─ Checkout code
   ├─ Set up Python 3.12
   ├─ Install dependencies
   ├─ Run unit tests
   ├─ Compile Python (syntax check)
   └─ Build Docker image locally
    ↓ (all services succeed)
2. Verify-Compose Job (Sequential)
   ├─ Validate docker-compose.yml
   ├─ Build full stack
   ├─ Start services
   ├─ Wait 10 seconds
   ├─ Health check (curl http://localhost:8080/service-a/health)
   └─ Cleanup
    ↓ (only on push to main)
3. Publish Job (Matrix: 3 services in parallel)
   ├─ Checkout code
   ├─ Login to Docker Hub
   ├─ Compute short commit hash
   └─ Build and push image with sha-<hash> tag
```

### Job Details

#### Job 1: Verify (Parallel Matrix - 3 Services)

Runs for every PR and push. Uses matrix strategy to test all three services in parallel.

**What it does:**

```yaml
strategy:
  matrix:
    - service: service-a, path: ./services/service-a
    - service: service-b, path: ./services/service-b
    - service: service-c, path: ./services/service-c
```

Each matrix run:
1. **Checkout repository** — Fetch code from the branch
2. **Set up Python 3.12** — Install exact Python version with pip caching
3. **Install dependencies** — `pip install -r requirements.txt pytest`
4. **Run tests** — Execute `python -m pytest` (falls back to `unittest` if no pytest)
   - Tests located in `services/service-x/tests/test_service_x.py`
   - Must pass before Docker build
5. **Compile Python** — Run `python -m compileall .`
   - Validates Python syntax without executing code
   - Catches indentation, import, and syntax errors early
   - Prevents building Docker images with broken Python
6. **Build Docker image** — `docker build . -f services/service-x/Dockerfile -t service-x:sha`
   - Uses repo root as build context (`.`)
   - This allows Dockerfile to access `requirements.txt` at repo root
   - Tags with full commit SHA for traceability

**Failure behavior:**
- If any step fails, the job fails
- If any matrix run fails, all remaining services still build (fail-fast: false)
- Full logs available in GitHub Actions UI

#### Job 2: Verify-Compose (Sequential)

Runs only after **all three Verify jobs succeed**. Tests the full stack together.

**What it does:**

1. **Validate Compose file** — `docker compose config`
   - Checks YAML syntax and service definitions
   - Fails if docker-compose.yml or docker-compose.prod.yml is invalid

2. **Build Compose stack** — `docker compose build --pull`
   - Builds all three services as defined in docker-compose.yml
   - `--pull` ensures base images are up-to-date

3. **Start Compose stack** — `docker compose up -d`
   - Starts all services in detached mode
   - Creates networks, volumes, and service containers

4. **Show running services** — `docker compose ps`
   - Displays container status (useful for debugging)

5. **Check gateway health** — `curl --fail http://localhost:8080/service-a/health`
   - Waits 10 seconds for services to be ready
   - Calls Nginx on port 8080 (mapped from container port 80)
   - Expects 200 OK response
   - `--fail` causes curl to exit non-zero on error

6. **Cleanup** — `docker compose down -v` (even if steps fail)
   - Removes containers, networks, and volumes
   - Ensures each run starts fresh

**Failure behavior:**
- If any step fails, the workflow fails
- Health check failures indicate a real problem with the stack
- Common causes: port conflicts, services not starting, Nginx misconfiguration

#### Job 3: Publish (Parallel Matrix - 3 Services)

Runs **only** on push to main, **only after Verify-Compose succeeds**. Publishes images to Docker Hub.

```yaml
if: github.event_name == 'push' && github.ref == 'refs/heads/main'
```

**What it does:**

1. **Checkout repository** — Fetch code from main branch

2. **Login to Docker Hub** — Uses GitHub Actions secrets
   - `${{ vars.DOCKERHUB_USERNAME }}` — Public variable (set in repo settings)
   - `${{ secrets.DOCKERHUB_TOKEN }}` — Private token (set in repo secrets)

3. **Compute short commit hash** — `SHORT_SHA=${GITHUB_SHA::7}`
   - Takes first 7 characters of commit SHA
   - Example: `a1b2c3d4e5f...` → `a1b2c3d`

4. **Build and push image** — Docker BuildX action
   - Context: `.` (repo root, needed for requirements.txt)
   - Dockerfile: `./services/service-x/Dockerfile`
   - Push: `true` (publishes to Docker Hub)
   - Tags:
     ```
     your-username/group-seven-devops-service-a:sha-a1b2c3d
     ```
   - Labels: Commit SHA and repo URL (for image tracking)

5. **Write deployment summary** — `$GITHUB_STEP_SUMMARY`
   - Markdown output visible at top of workflow run
   - Shows which images were published
   - Example:
     ```
     ### Published Image
     Service: service-a
     Image: your-username/group-seven-devops-service-a:sha-a1b2c3d
     ```

### Setup Instructions

#### 1. Create Docker Hub Token

Required for publishing images to Docker Hub.

**Steps:**
1. Go to [Docker Hub](https://hub.docker.com)
2. Click your profile → Settings → Security → Personal Access Tokens
3. Create new token (name: `github-actions`)
4. Copy the token (you won't see it again)

#### 2. Configure GitHub Repo Settings

**Add public variable (Settings → Variables):**
- Name: `DOCKERHUB_USERNAME`
- Value: Your Docker Hub username (e.g., `your-username`)
- Scope: Repository

**Add private secret (Settings → Secrets):**
- Name: `DOCKERHUB_TOKEN`
- Value: Paste the token from Docker Hub
- Scope: Repository

After setup, the workflow will automatically publish images.

### Running the Workflow

#### Manual Trigger

```bash
# From GitHub web UI:
# 1. Go to Actions tab
# 2. Select "Container CI/CD"
# 3. Click "Run workflow" → "Run workflow"
# 4. Specify branch (main, or your feature branch)
# 5. Click "Run"
```

#### Automatic Triggers

- **Pull Request** — Every PR to main runs Verify and Verify-Compose
- **Push to main** — Runs all three jobs (Verify, Verify-Compose, Publish)
- **Push to other branches** — Runs Verify and Verify-Compose only (no publish)

### Viewing Workflow Results

**From GitHub Web UI:**
1. Go to your repository
2. Click "Actions" tab
3. Select "Container CI/CD" workflow
4. Click on a run to see details

**For specific jobs:**
- Click a job to expand and see step-by-step output
- Click a step to see full log

**Get images after successful publish:**
```bash
# View published images
curl https://hub.docker.com/v2/repositories/your-username/group-seven-devops-service-a/tags \
  | jq '.results[].name'

# Pull and test a published image
docker pull your-username/group-seven-devops-service-a:sha-a1b2c3d
docker run your-username/group-seven-devops-service-a:sha-a1b2c3d python services/service-a/service_a.py
```

### Key Features

**1. Matrix Strategy (Parallel Testing)**
- Tests all three services at the same time
- Reduces workflow time from ~30s per service to ~30s total
- If one service fails, others still complete (fail-fast: false)

**2. Python Compilation Check**
- `python -m compileall .` runs before Docker build
- Catches syntax errors early and cheaply
- Prevents building broken Docker images

**3. Build Context Fix**
- Builds from repo root (`.`) instead of service directory
- Allows services to access `requirements.txt` at build time
- Dockerfile uses: `COPY services/service-a/ /app/`

**4. Docker Compose Validation**
- Tests full stack before publishing images
- Catches configuration errors early
- Health check ensures services actually work together

**5. Commit-Based Image Tags**
- Every image tagged with commit hash: `sha-a1b2c3d`
- Fully traceable: image → commit → code
- Can revert to any previous version

**6. Deployment Summary**
- GitHub Actions automatically shows published image names
- No need to dig through logs to find image tags

### Troubleshooting Failed Workflows

#### Verify Job Fails (Tests)

**Symptom:** "Run tests" step fails

**Diagnosis:**
```bash
# Run locally to reproduce
cd services/service-a
python -m pytest tests
```

**Solutions:**
- Fix failing test logic
- Ensure dependencies are in `requirements.txt`
- Check Python version matches (3.12)

#### Verify Job Fails (Compile)

**Symptom:** "Build Python code" step fails with syntax error

**Diagnosis:**
```bash
# Run locally
python -m compileall services/service-a
```

**Solutions:**
- Check for indentation errors
- Verify all imports are available
- Syntax errors will show line number

#### Verify Job Fails (Docker Build)

**Symptom:** "Build Docker image locally" fails

**Common causes:**
1. **"COPY requirements.txt: file not found"**
   - Build context issue
   - Solution: Verify Dockerfile uses `COPY services/service-a/ /app/`

2. **"Base image not found"**
   - Docker can't pull base image (network issue)
   - Solution: Check Docker registries are reachable

3. **Build step fails in container**
   - Python syntax error, pip install fails
   - Solution: Fix the issue and rebuild locally

#### Verify-Compose Job Fails (Docker Start)

**Symptom:** "Start Compose stack" or "Check gateway health" fails

**Diagnosis:**
- Check if services are actually running
- Common causes: port conflicts, service crashes

**Solutions:**
```bash
# Reproduce locally
docker compose up -d
docker compose ps  # Check status
docker compose logs service-a  # View service logs
docker compose down  # Cleanup
```

#### Publish Job Fails (Docker Hub Login)

**Symptom:** "Login to Docker Hub" fails

**Causes:**
- `DOCKERHUB_USERNAME` or `DOCKERHUB_TOKEN` not set
- Token is expired or revoked
- Token has wrong permissions

**Solutions:**
1. Check Settings → Variables → `DOCKERHUB_USERNAME` exists
2. Check Settings → Secrets → `DOCKERHUB_TOKEN` exists
3. Recreate token if expired (token has expiration date)

#### Publish Job Fails (Build and Push)

**Symptom:** "Build and push image" fails

**Causes:**
- Docker build fails (same as Verify job)
- Docker Hub registry unreachable
- Disk space on runner

**Solutions:**
- Check build errors (same as Verify job)
- Retry (might be temporary network issue)
- Contact Docker Hub status page

### Image Traceability Example

**Scenario:** Production is broken after deploying a new image

```bash
# 1. Find which image is currently running
docker inspect <running-container> | grep -i image

# Output: your-username/group-seven-devops-service-a:sha-a1b2c3d

# 2. Find the commit this image was built from
# From the workflow run summary or:
git log --grep="a1b2c3d"
git show a1b2c3d

# 3. Review what changed in that commit
git diff a1b2c3d~1 a1b2c3d

# 4. If needed, rollback to previous version
git log --oneline group-seven-devops-service-a:sha-*
# Deploy the previous sha-xxxxx
```

### Performance Notes

- **Verify job:** ~30 seconds total (all three services in parallel)
- **Verify-Compose job:** ~20 seconds (start, health check, stop)
- **Publish job:** ~1-2 minutes (build + upload to Docker Hub)
- **Total workflow:** ~3-4 minutes from push to published images

Parallel matrix strategy is what enables fast feedback.

---

## Docker Image Publishing

### How Images Are Built and Published

1. **Development Phase:**
   - Create feature branch
   - Make changes to code or Dockerfile
   - Push to feature branch

2. **Code Review Phase:**
   - Create pull request
   - CI/CD automatically tests and builds
   - Review code and images
   - Peer review images for security and best practices

3. **Merge to Main:**
   - Approve and merge pull request
   - GitHub Actions automatically:
     - Tests all code
     - Builds Docker images
     - Tags with commit hash
     - Publishes to Docker Hub

4. **Deployment Phase:**
   - Use `./scripts/deploy.sh sha-<hash>` to deploy specific version
   - Never use `latest` tag in production

### Verify Published Images

```bash
# List available tags for a service
curl https://hub.docker.com/v2/repositories/your-username/group-seven-devops-service-a/tags \
  | jq '.results[].name'

# Pull a specific version
docker pull your-username/group-seven-devops-service-a:sha-a1b2c3d

# Inspect image metadata
docker image inspect your-username/group-seven-devops-service-a:sha-a1b2c3d \
  | jq '.[] | {Labels: .Config.Labels, CreatedAt: .Created}'
```

---

## Project Structure

```
group-seven-devops/
├── services/                    # Three microservices
│   ├── service-a/
│   │   ├── service_a.py         # Main application code
│   │   ├── Dockerfile           # Container image definition
│   │   └── tests/
│   │       └── test_service_a.py # Unit tests
│   ├── service-b/
│   │   ├── service_b.py
│   │   ├── Dockerfile
│   │   └── tests/
│   │       └── test_service_b.py
│   └── service-c/
│       ├── service_c.py
│       ├── Dockerfile
│       └── tests/
│           └── test_service_c.py
├── nginx/                       # Nginx reverse proxy config
│   ├── default.conf             # Host deployment config
│   └── nginx-docker.conf        # Container deployment config
├── systemd/                     # Systemd service definitions
│   ├── service-a.service
│   ├── service-b.service
│   └── service-c.service
├── scripts/                     # Deployment scripts
│   └── deploy.sh                # Deploy specific image version
├── .github/workflows/           # CI/CD pipeline
│   └── container-ci-cd.yml      # GitHub Actions workflow
├── docker-compose.yml           # Development stack (local build)
├── docker-compose.prod.yml      # Production stack (pre-built images)
├── requirements.txt             # Python dependencies
├── .dockerignore                # Files to exclude from Docker image
├── .env.example                 # Environment variables template
├── install.sh                   # Automated installation script
├── reset.sh                     # Clean up script
└── README.md                    # This file
```

---

<details>
<summary><strong>Contributing</strong> (click to expand)</summary>

## Contributing

When working on this project:

1. **Create a feature branch**
   ```bash
   git checkout -b feature/your-feature-name
   ```

2. **Make changes and test locally**
   ```bash
   # Host deployment
   sudo ./install.sh
   curl http://localhost/service-a/greet-service-b
   
   # Container deployment
   docker compose up -d
   curl http://localhost:8080/service-a/health
   ```

3. **Run tests**
   ```bash
   cd services/service-a && python -m pytest tests
   cd services/service-b && python -m pytest tests
   cd services/service-c && python -m pytest tests
   ```

4. **Push and create pull request**
   - CI/CD will automatically test your changes
   - Ensure all checks pass
   - Request peer review

5. **After merge to main**
   - Images are automatically published to Docker Hub
   - Use `./scripts/deploy.sh sha-<hash>` to deploy

---

</details>

## License

This project is for educational purposes as part of the DevOps program.

---

<details>
<summary><strong>Questions?</strong> (click to expand)</summary>

## Questions?

For troubleshooting, see the [Troubleshooting Guide](#troubleshooting-guide) section above.
For architecture questions, refer to [System Architecture](#system-architecture).
For deployment questions, see [Host Deployment](#host-deployment-systemd) or [Container Deployment](#container-deployment-docker).

</details>

<details>
<summary><strong>Verification Checklist</strong> (click to expand)</summary>

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

</details>

<details>
<summary><strong>Deployment Notes</strong> (click to expand)</summary>

## Deployment Notes

- Designed for **Ubuntu 24.04 LTS** on a dedicated VM
- `install.sh` auto-detects the project path — works regardless of where you clone it
- Logs accessible via `journalctl` (systemd journal) and `/var/log/nginx/access.log`
- Configuration is code: all settings in `.service` files and `nginx/default.conf`
- No databases or external dependencies required
- Services start in order: B → C → A (A requires B and C)

</details>

<details>
<summary><strong>Quick Commands</strong> (click to expand)</summary>

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

</details>

