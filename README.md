# Production-Style Service Architecture

## Overview

This project demonstrates a production-ready microservices environment with three internal HTTP services orchestrated through systemd, exposed via Nginx reverse proxy, with structured JSON logging and distributed request tracing.

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

- All services listen on `127.0.0.1` (localhost only)
- Only Nginx listens on `0.0.0.0:80` (public)
- Services B and C are unreachable from outside the VM
- Verification: `curl http://<vm-ip>:3002` → Connection refused

### Service Discovery

Services communicate using DNS names in `/etc/hosts`:
```
127.0.0.1 service-a.internal
127.0.0.1 service-b.internal
127.0.0.1 service-c.internal
```

**How to troubleshoot discovery:**
```bash
nslookup service-a.internal
cat /etc/hosts | grep service
```

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

### Setup

```bash
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

# 3. Install systemd service files
sudo cp systemd/service-a.service /etc/systemd/system/
sudo cp systemd/service-b.service /etc/systemd/system/
sudo cp systemd/service-c.service /etc/systemd/system/
sudo systemctl daemon-reload

# 4. Configure Nginx
sudo cp nginx/default.conf /etc/nginx/sites-available/default
sudo nginx -t
sudo systemctl restart nginx

# 5. Enable and start services
sudo systemctl enable service-a service-b service-c
sudo systemctl start service-b service-c service-a
```

## Operation

### Start Services

```bash
sudo systemctl start service-a service-b service-c
```

### Stop Services

```bash
sudo systemctl stop service-a service-b service-c
```

### Restart Services

```bash
sudo systemctl restart service-a service-b service-c
```

### Check Status

```bash
systemctl status service-a service-b service-c
```

### View Logs

```bash
# Service A logs
journalctl -u service-a -f

# All services
journalctl -u "service-*" -f
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
  "request_id": "...",
  "status": "success",
  "message": "Request completed successfully"
}
```

### Verify Request Tracing

```bash
# Trigger request
REQUEST_ID=$(curl -s http://localhost/service-a/greet-service-b | jq -r .request_id)

# Check all services logged it
journalctl -u service-a | grep $REQUEST_ID
journalctl -u service-b | grep $REQUEST_ID
journalctl -u service-c | grep $REQUEST_ID
```

## Logging

All services produce structured JSON logs with:
- `timestamp`: ISO 8601 UTC
- `service`: service name
- `event`: event type
- `request_id`: distributed trace ID
- `status`: HTTP status code
- Additional context fields per event type

**Log locations:**
```bash
journalctl -u service-a
journalctl -u service-b
journalctl -u service-c
```

## Troubleshooting

### Service fails to start

```bash
# Check systemd status
systemctl status service-a

# Check logs
journalctl -u service-a -n 50

# Verify port is available
netstat -tlnp | grep 3001
```

### Service discovery fails

```bash
# Verify /etc/hosts entries
cat /etc/hosts | grep service

# Test DNS resolution
nslookup service-b.internal

# Manual test
curl http://service-a.internal:3001/health
```

### Reverse proxy fails

```bash
# Test Nginx config
sudo nginx -t

# Check Nginx logs
sudo tail -f /var/log/nginx/access.log

# Verify upstream is reachable
curl http://127.0.0.1:3001/health
```

### Services can't communicate

```bash
# Check if target service is running
systemctl status service-b

# Verify request reaches target
journalctl -u service-b -f

# Test direct connection
curl http://service-b.internal:3002/health
```

### Missing logs

```bash
# Check if service is running
systemctl status service-a

# Check systemd journal
journalctl -u service-a -n 100

# Restart and monitor
sudo systemctl restart service-a
journalctl -u service-a -f
```

### Network isolation issues

```bash
# Services should NOT be accessible from outside
curl http://<vm-ip>:3002  # Should fail

# But localhost access should work
curl http://127.0.0.1:3002/health  # Should work

# Verify listen address
netstat -tlnp | grep 3002
# Should show 127.0.0.1:3002, NOT 0.0.0.0:3002
```

### Request doesn't flow through all services

```bash
# Check service dependency order in systemd
systemctl cat service-a | grep After

# Start services in correct order
sudo systemctl stop service-a service-b service-c
sudo systemctl start service-b service-c service-a

# Trigger request and trace
curl http://localhost/service-a/greet-service-b
journalctl -u "service-*" -n 50
```

## Verification Checklist

- [ ] All three services start on boot
- [ ] Services restart on failure
- [ ] Service A depends on B and C
- [ ] Nginx exposes only Service A
- [ ] Services B and C are not externally accessible
- [ ] Full request flow works: A → B → C → A
- [ ] Request ID propagates through all logs
- [ ] All logs are valid JSON
- [ ] Service discovery works (`service-b.internal` resolves)

## Deployment Notes

- Services run as the `ubuntu` user
- Working directory: `/home/ubuntu/devops-lab/group-seven-devops`
- Logs accessible via `journalctl` (systemd journal)
- Configuration is code: all settings in `.service` files and `nginx/default.conf`
- No databases or external dependencies required
```
