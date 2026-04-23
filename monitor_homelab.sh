#!/bin/bash

# Continuous Homelab Monitor
# Runs periodic scans and alerts on changes

MONITOR_DIR="$HOME/homelab_monitor"
BASELINE="$MONITOR_DIR/baseline.txt"
INTERVAL=3600  # Scan every hour (3600 seconds)

mkdir -p "$MONITOR_DIR"

# Auto-detect network
LOCAL_NETWORK=$(ip route | grep -v default | grep -E "192.168|10\.|172\.(1[6-9]|2[0-9]|3[0-1])\." | head -1 | awk '{print $1}')

echo "Monitoring $LOCAL_NETWORK every $((INTERVAL/60)) minutes"
echo "Baseline: $BASELINE"
echo "Press Ctrl+C to stop"
echo ""

# Create baseline if it doesn't exist
if [ ! -f "$BASELINE" ]; then
    echo "Creating baseline scan..."
    sudo nmap -sn "$LOCAL_NETWORK" -oG - | grep "Up" | sort > "$BASELINE"
    echo "Baseline created with $(wc -l < $BASELINE) hosts"
fi

while true; do
    DATE=$(date +%Y%m%d_%H%M%S)
    CURRENT_SCAN="$MONITOR_DIR/current_$DATE.txt"
   
    echo "[$(date)] Running scan..."
    sudo nmap -sn "$LOCAL_NETWORK" -oG - | grep "Up" | sort > "$CURRENT_SCAN"
   
    # Compare with baseline
    DIFF=$(diff "$BASELINE" "$CURRENT_SCAN")
   
    if [ -n "$DIFF" ]; then
        echo "⚠️  CHANGES DETECTED! ⚠️"
        echo "$DIFF"
        echo ""
        echo "New scan saved to: $CURRENT_SCAN"
       
        # Optionally update baseline
        read -t 30 -p "Update baseline? (y/n): " UPDATE
        if [ "$UPDATE" = "y" ]; then
            cp "$CURRENT_SCAN" "$BASELINE"
            echo "Baseline updated"
        fi
    else
        echo "✓ No changes detected"
        rm "$CURRENT_SCAN"  # Clean up if no changes
    fi
   
    echo "Next scan in $((INTERVAL/60)) minutes..."
    echo ""
    sleep "$INTERVAL"
done

