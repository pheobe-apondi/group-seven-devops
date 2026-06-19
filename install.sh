#!/bin/bash
set -Eeuo pipefail

echo "[*] Installing production service environment..."

# 1. Install system dependencies
echo "[*] Installing system packages..."
sudo apt update
sudo apt install -y python3 python3-pip nginx

# 2. Install Python dependencies
echo "[*] Installing Python packages..."
pip3 install --break-system-packages flask requests

# 3. Setup service discovery
echo "[*] Configuring service discovery (/etc/hosts)..."
if ! grep -q "service-a.internal" /etc/hosts; then
    sudo bash -c 'cat >> /etc/hosts << EOFHOSTS
127.0.0.1 service-a.internal
127.0.0.1 service-b.internal
127.0.0.1 service-c.internal
EOFHOSTS'
    echo "[+] Service discovery entries added"
fi

# 4. Install systemd services
echo "[*] Installing systemd service files..."
sudo cp systemd/service-a.service /etc/systemd/system/
sudo cp systemd/service-b.service /etc/systemd/system/
sudo cp systemd/service-c.service /etc/systemd/system/
sudo systemctl daemon-reload

# 5. Configure Nginx
echo "[*] Configuring Nginx..."
sudo cp nginx/default.conf /etc/nginx/sites-available/default
sudo nginx -t > /dev/null && echo "[+] Nginx config valid"
sudo systemctl restart nginx

# 6. Enable services
echo "[*] Enabling services..."
sudo systemctl enable service-a service-b service-c

# 7. Start services
echo "[*] Starting services..."
sudo systemctl start service-b service-c service-a

# 8. Wait for startup
sleep 3

# 9. Verify
echo "[*] Verifying installation..."
if curl -s http://127.0.0.1:3001/health > /dev/null; then
    echo "[+] Service A: OK"
else
    echo "[-] Service A: FAILED"
    exit 1
fi

if curl -s http://127.0.0.1:3002/health > /dev/null; then
    echo "[+] Service B: OK"
else
    echo "[-] Service B: FAILED"
    exit 1
fi

if curl -s http://127.0.0.1:3003/health > /dev/null; then
    echo "[+] Service C: OK"
else
    echo "[-] Service C: FAILED"
    exit 1
fi

echo ""
echo "[+] Installation complete!"
echo ""
echo "Next steps:"
echo "  Test full flow: curl http://localhost/service-a/greet-service-b"
echo "  View logs: journalctl -u service-a -f"
echo "  Check status: systemctl status service-a service-b service-c"
