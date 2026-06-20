#!/bin/bash
set -Eeuo pipefail

echo "[*] Resetting environment..."

# Stop all services
echo "[*] Stopping services..."
sudo systemctl stop service-a service-b service-c 2>/dev/null || true
sleep 2

# Disable services
echo "[*] Disabling services..."
sudo systemctl disable service-a service-b service-c 2>/dev/null || true

# Remove service files
echo "[*] Removing service files..."
sudo rm -f /etc/systemd/system/service-a.service
sudo rm -f /etc/systemd/system/service-b.service
sudo rm -f /etc/systemd/system/service-c.service
sudo systemctl daemon-reload

# Stop Nginx
echo "[*] Stopping Nginx..."
sudo systemctl stop nginx 2>/dev/null || true

# Remove Nginx config
echo "[*] Removing Nginx config..."
sudo rm -f /etc/nginx/sites-available/default

echo ""
echo "[+] Reset complete!"
echo ""
echo "Next step:"
echo "  Run: sudo ./install.sh"
