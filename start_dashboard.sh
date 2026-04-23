#!/bin/bash
# ════════════════════════════════════════════════════════════════════════════
# LARRY G-FORCE DASHBOARD HUB LAUNCHER
# ════════════════════════════════════════════════════════════════════════════
# Starts the interactive dashboard on localhost:3777

set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$SCRIPT_DIR"

echo "╔═══════════════════════════════════════════════════════════════╗"
echo "║     LARRY G-FORCE DASHBOARD HUB LAUNCHER                      ║"
echo "╚═══════════════════════════════════════════════════════════════╝"
echo ""

# Create venv if needed
if [ ! -d "venv313" ]; then
    echo "🔧 Setting up Python 3.13 environment..."
    python3.13 -m venv venv313
    source venv313/bin/activate
    pip install --upgrade pip setuptools wheel -q
    echo "📦 Installing dependencies..."
    pip install flask flask-cors -q
    echo "✅ Setup complete!"
else
    source venv313/bin/activate
fi

# Ensure flask and flask-cors are installed
pip install flask flask-cors -q 2>/dev/null || true

echo ""
echo "🚀 Starting Dashboard Hub..."
echo ""
echo "┌─────────────────────────────────────────────────────────────────┐"
echo "│ 🌐 Dashboard URL: http://localhost:3777                         │"
echo "│                                                                 │"
echo "│ The web browser will open automatically.                        │"
echo "│                                                                 │"
echo "│ Press Ctrl+C to stop the server                                │"
echo "└─────────────────────────────────────────────────────────────────┘"
echo ""

python dashboard_hub.py
