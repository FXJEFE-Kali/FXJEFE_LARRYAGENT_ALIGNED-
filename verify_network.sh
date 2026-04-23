#!/bin/bash

echo "======================================"
echo "Network Configuration Verification"
echo "======================================"
echo ""

# Check local IP address
echo "[1] Your Local IP Addresses:"
ip addr show | grep "inet " | grep -v "127.0.0.1" | awk '{print "    " $2}'
echo ""

# Check default gateway (your router)
echo "[2] Your Local Gateway (Router):"
GATEWAY=$(ip route | grep default | awk '{print $3}')
echo "    $GATEWAY"
echo ""

# Determine local network range
LOCAL_NETWORK=$(ip route | grep -v default | grep -E "192.168|10\.|172\.(1[6-9]|2[0-9]|3[0-1])\." | head -1 | awk '{print $1}')
echo "[3] Your Local Network Range:"
echo "    $LOCAL_NETWORK"
echo ""

# Check public IP (will show VPN IP if connected)
echo "[4] Your Public IP (Internet-facing):"
PUBLIC_IP=$(curl -s ifconfig.me)
echo "    $PUBLIC_IP"
echo ""

# Verify VPN status
if [ "$PUBLIC_IP" = "151.245.80.158" ]; then
    echo "[✓] VPN is ACTIVE - Traffic routes through NordVPN"
else
    echo "[!] VPN Status: Using different IP ($PUBLIC_IP)"
fi
echo ""

# Check DNS servers
echo "[5] DNS Servers in use:"
cat /etc/resolv.conf | grep nameserver | awk '{print "    " $2}'
echo ""

echo "======================================"
echo "Local Network Scan Configuration"
echo "======================================"
echo "You should scan: $LOCAL_NETWORK"
echo "This scanning happens LOCALLY and does NOT go through VPN"
echo "======================================"
