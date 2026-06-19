#!/bin/bash
echo " System Health Check "

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
echo "=== Health check complete ==="
