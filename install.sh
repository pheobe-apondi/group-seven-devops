#!/bin/bash
set -Eeuo pipefail

echo "[*] Installing production service environment..."

# Auto-detect the project directory (where install.sh is running from)
PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
echo "[*] Project directory: $PROJECT_DIR"

# 0. Stop any existing services first
echo "[*] Cleaning up any existing services..."
sudo systemctl stop service-a service-b service-c nginx 2>/dev/null || true
sleep 2

# 1. Install system dependencies
echo "[*] Installing system packages..."
sudo apt update
sudo apt install -y ufw >/dev/null 2>&1 || true

# Remove any conflicting Debian-managed Python packages
echo "[*] Cleaning up conflicting packages..."
sudo apt remove -y python3-blinker python3-flask python3-requests 2>/dev/null || true

sudo apt install -y python3 python3-pip nginx

# 2. Install Python dependencies (fresh from pip, not Debian)
echo "[*] Installing Python packages..."
pip3 install --break-system-packages --upgrade flask requests

echo "[+] Python dependencies installed"

# 3. Setup service discovery
echo "[*] Configuring service discovery (/etc/hosts)..."
if ! grep -q "service-a.internal" /etc/hosts; then
    sudo bash -c 'cat >> /etc/hosts << EOFHOSTS
127.0.0.1 service-a.internal
127.0.0.1 service-b.internal
127.0.0.1 service-c.internal
EOFHOSTS'
    echo "[+] Service discovery entries added"
else
    echo "[+] Service discovery entries already exist"
fi

# 4. Install systemd services (with auto-detected path)
echo "[*] Installing systemd service files..."

# Create service-a.service with correct PROJECT_DIR
sudo bash -c "cat > /etc/systemd/system/service-a.service << 'EOF'
[Unit]
Description=Service A
After=network.target
Wants=service-b.service service-c.service
After=service-b.service service-c.service

[Service]
Type=simple
WorkingDirectory=$PROJECT_DIR
ExecStart=/usr/bin/python3 $PROJECT_DIR/services/service-a/service_a.py --loopback
Restart=on-failure
RestartSec=5s
StandardOutput=journal
StandardError=journal

[Install]
WantedBy=multi-user.target
EOF"

# Create service-b.service with correct PROJECT_DIR
sudo bash -c "cat > /etc/systemd/system/service-b.service << 'EOF'
[Unit]
Description=Service B
After=network.target

[Service]
Type=simple
WorkingDirectory=$PROJECT_DIR
ExecStart=/usr/bin/python3 $PROJECT_DIR/services/service-b/service_b.py --loopback
Restart=on-failure
RestartSec=5s
StandardOutput=journal
StandardError=journal

[Install]
WantedBy=multi-user.target
EOF"

# Create service-c.service with correct PROJECT_DIR
sudo bash -c "cat > /etc/systemd/system/service-c.service << 'EOF'
[Unit]
Description=Service C
After=network.target

[Service]
Type=simple
WorkingDirectory=$PROJECT_DIR
ExecStart=/usr/bin/python3 $PROJECT_DIR/services/service-c/service_c.py --loopback
Restart=on-failure
RestartSec=5s
StandardOutput=journal
StandardError=journal

[Install]
WantedBy=multi-user.target
EOF"

sudo systemctl daemon-reload
echo "[+] Systemd services installed"

# 5. Configure Nginx
echo "[*] Configuring Nginx..."

# Ensure log directories exist with proper permissions
sudo mkdir -p /var/log/nginx
sudo chmod 755 /var/log/nginx

# Copy Nginx configuration
sudo cp nginx/default.conf /etc/nginx/sites-available/default

# Validate configuration
sudo nginx -t > /dev/null && echo "[+] Nginx config valid"

# Set up log rotation for JSON trace logs
sudo bash -c 'cat > /etc/logrotate.d/nginx-json << EOF
/var/log/nginx/access.json
/var/log/nginx/error.json
{
  daily
  rotate 7
  compress
  delaycompress
  notifempty
  create 0640 www-data adm
  sharedscripts
  postrotate
    if [ -f /var/run/nginx.pid ]; then
      kill -USR1 \`cat /var/run/nginx.pid\`
    fi
  endscript
}
EOF'

# Restart Nginx
sudo systemctl restart nginx
echo "[+] Nginx configured with structured JSON trace logging"

# 6. Configure firewall for network security
echo "[*] Configuring host firewall..."
sudo ufw --force reset >/dev/null 2>&1 || true
sudo ufw default deny incoming >/dev/null 2>&1 || true
sudo ufw default allow outgoing >/dev/null 2>&1 || true
sudo ufw allow 80/tcp >/dev/null 2>&1 || true
sudo ufw --force enable >/dev/null 2>&1 || true
echo "[+] Firewall configured"

# 7. Enable services
echo "[*] Enabling services..."
sudo systemctl enable service-a service-b service-c
echo "[+] Services enabled"

# 8. Start services (order matters!)
echo "[*] Starting services..."
sudo systemctl start service-b service-c service-a
echo "[+] Services started"

# 9. Wait for startup
sleep 3

# 10. Verify
echo "[*] Verifying installation..."

if curl -s http://127.0.0.1:3001/health > /dev/null; then
    echo "[+] Service A: OK"
else
    echo "[-] Service A: FAILED"
    echo "    Logs:"
    journalctl -u service-a -n 10
    exit 1
fi

if curl -s http://127.0.0.1:3002/health > /dev/null; then
    echo "[+] Service B: OK"
else
    echo "[-] Service B: FAILED"
    echo "    Logs:"
    journalctl -u service-b -n 10
    exit 1
fi

if curl -s http://127.0.0.1:3003/health > /dev/null; then
    echo "[+] Service C: OK"
else
    echo "[-] Service C: FAILED"
    echo "    Logs:"
    journalctl -u service-c -n 10
    exit 1
fi

if [ -f /var/log/nginx/access.json ]; then
    echo "[+] Nginx trace logging: OK"
else
    echo "[-] Nginx trace logging: Not yet active (will activate on first request)"
fi

echo "Next steps:"
echo "  Test full flow: curl http://localhost/service-a/greet-service-b"
echo ""
echo "View structured logs for request tracing:"
echo "  Service A logs: journalctl -u service-a -f"
echo "  Service B logs: journalctl -u service-b -f"
echo "  Service C logs: journalctl -u service-c -f"
echo "  Nginx trace logs: tail -f /var/log/nginx/access.json"
echo "  Nginx errors: tail -f /var/log/nginx/error.json"
echo ""
echo "Trace a request through the system:"
echo "  1. Make a request: curl http://localhost/service-a/greet-service-b"
echo "  2. Copy the request_id from the response"
echo "  3. Find it in logs: grep 'request_id' /var/log/nginx/access.json"
echo ""
echo "System status: systemctl status service-a service-b service-c nginx"
