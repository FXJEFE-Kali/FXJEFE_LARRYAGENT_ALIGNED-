#!/bin/bash

# Quick device scanner
# Usage: sudo ./scan_device.sh 192.168.1.20

if [ -z "$1" ]; then
    echo "Usage: sudo $0 <target_ip>"
    echo "Example: sudo $0 192.168.1.20"
    exit 1
fi

TARGET="$1"
OUTPUT_DIR="$HOME/device_scans"
DATE=$(date +%Y%m%d_%H%M%S)

mkdir -p "$OUTPUT_DIR"

echo "=========================================="
echo "Deep Scan of $TARGET"
echo "=========================================="

# Verify target is on local network
if [[ ! $TARGET =~ ^(192\.168\.|10\.|172\.(1[6-9]|2[0-9]|3[0-1])\.) ]]; then
    echo "WARNING: $TARGET does not appear to be a local IP"
    read -p "Continue anyway? (y/n): " CONFIRM
    if [ "$CONFIRM" != "y" ]; then
        exit 1
    fi
fi

# Check VPN status
PUBLIC_IP=$(curl -s ifconfig.me)
echo "Your public IP: $PUBLIC_IP"
echo "Scanning local device: $TARGET (traffic stays local)"
echo ""

# Comprehensive scan
echo "[1/5] Host discovery..."
sudo nmap -sn "$TARGET"

echo ""
echo "[2/5] Full TCP port scan..."
sudo nmap -sS -p- -T4 "$TARGET" -oN "$OUTPUT_DIR/${TARGET}_ports_$DATE.txt"

echo ""
echo "[3/5] Service version detection..."
sudo nmap -sV -sC "$TARGET" -oN "$OUTPUT_DIR/${TARGET}_services_$DATE.txt"

echo ""
echo "[4/5] OS detection..."
sudo nmap -O "$TARGET" -oN "$OUTPUT_DIR/${TARGET}_os_$DATE.txt"

echo ""
echo "[5/5] Vulnerability scan..."
sudo nmap --script vuln "$TARGET" -oN "$OUTPUT_DIR/${TARGET}_vulns_$DATE.txt"

echo ""
echo "=========================================="
echo "Scan Complete"
echo "Results saved to: $OUTPUT_DIR"
echo "=========================================="
