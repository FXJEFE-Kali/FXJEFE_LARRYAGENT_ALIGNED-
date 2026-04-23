#!/bin/bash

# Homelab Security Scanner
# Scans LOCAL network only - VPN does not affect local scanning

# Configuration
SCAN_DIR="$HOME/homelab_scans"
DATE=$(date +%Y%m%d_%H%M%S)
LOGFILE="$SCAN_DIR/scan_$DATE.log"

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# Create scan directory
mkdir -p "$SCAN_DIR"

# Logging function
log() {
    echo -e "${GREEN}[$(date +%H:%M:%S)]${NC} $1" | tee -a "$LOGFILE"
}

warn() {
    echo -e "${YELLOW}[$(date +%H:%M:%S)]${NC} $1" | tee -a "$LOGFILE"
}

error() {
    echo -e "${RED}[$(date +%H:%M:%S)]${NC} $1" | tee -a "$LOGFILE"
}

# Check if running as root/sudo
if [ "$EUID" -ne 0 ]; then
    error "Please run with sudo for full scanning capabilities"
    exit 1
fi

log "=========================================="
log "Homelab Security Scan Started"
log "=========================================="

# Auto-detect local network
LOCAL_NETWORK=$(ip route | grep -v default | grep -E "192.168|10\.|172\.(1[6-9]|2[0-9]|3[0-1])\." | head -1 | awk '{print $1}')

if [ -z "$LOCAL_NETWORK" ]; then
    error "Could not auto-detect local network. Please specify manually."
    read -p "Enter your network range (e.g., 192.168.1.0/24): " LOCAL_NETWORK
fi

log "Target Network: $LOCAL_NETWORK"
log "Scan Directory: $SCAN_DIR"

# Verify VPN status (informational only)
PUBLIC_IP=$(curl -s ifconfig.me)
if [ "$PUBLIC_IP" = "151.245.80.158" ]; then
    log "VPN Status: ✓ NordVPN Active ($PUBLIC_IP)"
else
    warn "VPN Status: Different IP detected ($PUBLIC_IP)"
fi

log "Note: Local network scans do NOT traverse VPN tunnel"
log ""

# Phase 1: Host Discovery
log "[Phase 1/4] Discovering active hosts on $LOCAL_NETWORK..."
nmap -sn "$LOCAL_NETWORK" -oG "$SCAN_DIR/hosts_$DATE.gnmap" | tee -a "$LOGFILE"
LIVE_HOSTS=$(grep "Up" "$SCAN_DIR/hosts_$DATE.gnmap" | wc -l)
log "Found $LIVE_HOSTS live hosts"
log ""

# Extract live host IPs for targeted scanning
grep "Up" "$SCAN_DIR/hosts_$DATE.gnmap" | awk '{print $2}' > "$SCAN_DIR/live_hosts_$DATE.txt"

# Phase 2: Port Scanning
log "[Phase 2/4] Scanning common ports on discovered hosts..."
nmap -sS -sV -T4 -p- --open -iL "$SCAN_DIR/live_hosts_$DATE.txt" \
    -oN "$SCAN_DIR/ports_$DATE.txt" \
    -oX "$SCAN_DIR/ports_$DATE.xml" | tee -a "$LOGFILE"
log ""

# Phase 3: Service Detection
log "[Phase 3/4] Detailed service enumeration..."
nmap -sV -sC -iL "$SCAN_DIR/live_hosts_$DATE.txt" \
    -oN "$SCAN_DIR/services_$DATE.txt" | tee -a "$LOGFILE"
log ""

# Phase 4: Basic Vulnerability Check
log "[Phase 4/4] Running vulnerability scripts (safe checks only)..."
nmap --script=vuln --script-args=unsafe=0 -iL "$SCAN_DIR/live_hosts_$DATE.txt" \
    -oN "$SCAN_DIR/vulns_$DATE.txt" | tee -a "$LOGFILE"
log ""

# Generate Summary Report
log "=========================================="
log "Scan Summary"
log "=========================================="
log "Live Hosts: $LIVE_HOSTS"
log "Open Ports Found:"
grep "open" "$SCAN_DIR/ports_$DATE.txt" | wc -l | xargs echo "  " | tee -a "$LOGFILE"

log ""
log "Results saved to: $SCAN_DIR"
log "Main report: $SCAN_DIR/ports_$DATE.txt"
log "Vulnerability report: $SCAN_DIR/vulns_$DATE.txt"
log "=========================================="
log "Scan completed at $(date)"
