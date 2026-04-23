#!/bin/bash

# ============================================================================
# LOOTING LARRY - ULTIMATE EDITION
# Self-installing, crash-proof, persistent network security suite
# ============================================================================

set -euo pipefail  # Exit on error, undefined vars, pipe failures
trap 'handle_error $? $LINENO' ERR

# ============================================================================
# ERROR HANDLING - PREVENTS CRASHES
# ============================================================================

handle_error() {
    local exit_code=$1
    local line_number=$2
    echo "[ERROR] Script error at line $line_number (exit code: $exit_code)"
    echo "[ERROR] Continuing execution..."
    # Don't exit, just log and continue
}

# Trap to prevent Ctrl+C from killing during scans
trap 'echo -e "\n[!] Scan in progress - please wait for completion..."; return' INT

# ============================================================================
# PRIVILEGE ESCALATION & OS DETECTION
# ============================================================================

detect_os() {
    if [[ "$OSTYPE" == "linux-gnu"* ]]; then
        if grep -qi microsoft /proc/version 2>/dev/null; then
            OS="WSL"
        else
            OS="Linux"
        fi
       
        # Detect specific Linux distribution
        if [ -f /etc/os-release ]; then
            . /etc/os-release
            DISTRO=$ID
        elif command -v lsb_release &> /dev/null; then
            DISTRO=$(lsb_release -si | tr '[:upper:]' '[:lower:]')
        else
            DISTRO="unknown"
        fi
    elif [[ "$OSTYPE" == "darwin"* ]]; then
        OS="macOS"
        DISTRO="macos"
    elif [[ "$OSTYPE" == "cygwin" ]] || [[ "$OSTYPE" == "msys" ]]; then
        OS="Windows"
        DISTRO="windows"
    else
        OS="Unknown"
        DISTRO="unknown"
    fi
}

auto_elevate() {
    detect_os
   
    if [ "$EUID" -eq 0 ] 2>/dev/null || [ "$(id -u)" -eq 0 ] 2>/dev/null; then
        return 0
    fi
   
    case "$OS" in
        "Linux"|"WSL")
            if command -v sudo &> /dev/null; then
                echo "[*] Requesting root privileges for $OS..."
                exec sudo bash "$0" "$@"
            else
                echo "[!] ERROR: sudo not available. Installing sudo..."
                if command -v apt-get &> /dev/null; then
                    su -c "apt-get update && apt-get install -y sudo" || {
                        echo "[!] Please run as root: su -c 'bash $0'"
                        exit 1
                    }
                fi
                exec sudo bash "$0" "$@"
            fi
            ;;
        "macOS")
            if command -v sudo &> /dev/null; then
                echo "[*] Requesting administrator privileges for macOS..."
                if command -v osascript &> /dev/null && [ -z "$SUDO_USER" ]; then
                    osascript -e 'do shell script "sudo bash '"$0"' '$*'" with administrator privileges' 2>/dev/null && exit 0
                fi
                exec sudo bash "$0" "$@"
            fi
            ;;
        "Windows")
            echo "[!] Please run terminal as Administrator"
            read -p "Continue anyway? (y/n): " choice
            [ "$choice" != "y" ] && exit 1
            ;;
    esac
}

auto_elevate "$@"

# ============================================================================
# GLOBAL CONFIGURATION
# ============================================================================

SUITE_DIR="$HOME/looting_larry"
SCANS_DIR="$SUITE_DIR/scans"
LOGS_DIR="$SUITE_DIR/logs"
DB_DIR="$SUITE_DIR/database"
CONFIG_FILE="$SUITE_DIR/config.conf"
DB_FILE="$DB_DIR/scans.db"
DAEMON_PID_FILE="$SUITE_DIR/daemon.pid"
INSTALL_LOG="$SUITE_DIR/install.log"

# Create directory structure
mkdir -p "$SUITE_DIR" "$SCANS_DIR" "$LOGS_DIR" "$DB_DIR"

# Colors
RED='\033[1;31m'
ORANGE='\033[1;33m'
PURPLE='\033[1;35m'
GREEN='\033[1;32m'
CYAN='\033[1;36m'
WHITE='\033[1;37m'
BOLD='\033[1m'
DIM='\033[2m'
NC='\033[0m'

# ============================================================================
# DEPENDENCY INSTALLATION - AUTO-INSTALLS EVERYTHING
# ============================================================================

install_dependencies() {
    echo -e "${CYAN}╔═══════════════════════════════════════════════════════════════════════╗${NC}"
    echo -e "${CYAN}║${WHITE}                   DEPENDENCY INSTALLATION CHECK                       ${CYAN}║${NC}"
    echo -e "${CYAN}╚═══════════════════════════════════════════════════════════════════════╝${NC}\n"
   
    detect_os
   
    case "$DISTRO" in
        ubuntu|debian|kali|linuxmint|pop)
            install_debian_deps
            ;;
        fedora|rhel|centos|rocky|almalinux)
            install_redhat_deps
            ;;
        arch|manjaro)
            install_arch_deps
            ;;
        macos)
            install_macos_deps
            ;;
        *)
            echo -e "${ORANGE}[!] Unknown distribution. Attempting generic installation...${NC}"
            install_generic_deps
            ;;
    esac
   
    # Install Python dependencies for database
    install_python_deps
   
    echo -e "\n${GREEN}[✓] All dependencies installed successfully${NC}\n"
}

install_debian_deps() {
    echo -e "${ORANGE}[*] Detected Debian-based system ($DISTRO)${NC}\n"
   
    # Update package lists
    echo -e "${WHITE}Updating package lists...${NC}"
    apt-get update >> "$INSTALL_LOG" 2>&1 || {
        echo -e "${ORANGE}[!] Update failed, continuing...${NC}"
    }
   
    # Essential packages
    PACKAGES=(
        "nmap"
        "netcat-traditional"
        "net-tools"
        "iproute2"
        "curl"
        "wget"
        "sqlite3"
        "python3"
        "python3-pip"
        "cron"
        "dnsutils"
        "traceroute"
        "tcpdump"
        "iptables"
        "masscan"
    )
   
    for package in "${PACKAGES[@]}"; do
        if ! dpkg -l | grep -q "^ii  $package"; then
            echo -e "${ORANGE}[*] Installing $package...${NC}"
            DEBIAN_FRONTEND=noninteractive apt-get install -y "$package" >> "$INSTALL_LOG" 2>&1 || {
                echo -e "${YELLOW}[!] Failed to install $package (non-critical)${NC}"
            }
        else
            echo -e "${GREEN}[✓] $package already installed${NC}"
        fi
    done
}

install_redhat_deps() {
    echo -e "${ORANGE}[*] Detected RedHat-based system ($DISTRO)${NC}\n"
   
    PACKAGES=(
        "nmap"
        "nc"
        "net-tools"
        "iproute"
        "curl"
        "wget"
        "sqlite"
        "python3"
        "python3-pip"
        "cronie"
        "bind-utils"
        "traceroute"
        "tcpdump"
        "iptables"
    )
   
    for package in "${PACKAGES[@]}"; do
        echo -e "${ORANGE}[*] Installing $package...${NC}"
        yum install -y "$package" >> "$INSTALL_LOG" 2>&1 || dnf install -y "$package" >> "$INSTALL_LOG" 2>&1 || {
            echo -e "${YELLOW}[!] Failed to install $package${NC}"
        }
    done
}

install_arch_deps() {
    echo -e "${ORANGE}[*] Detected Arch-based system${NC}\n"
   
    pacman -Sy --noconfirm nmap netcat net-tools iproute2 curl wget sqlite python python-pip cronie bind-tools traceroute tcpdump iptables masscan >> "$INSTALL_LOG" 2>&1 || {
        echo -e "${YELLOW}[!] Some packages failed to install${NC}"
    }
}

install_macos_deps() {
    echo -e "${ORANGE}[*] Detected macOS system${NC}\n"
   
    # Check for Homebrew
    if ! command -v brew &> /dev/null; then
        echo -e "${ORANGE}[*] Installing Homebrew...${NC}"
        /bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)" || {
            echo -e "${RED}[!] Failed to install Homebrew${NC}"
            return 1
        }
    else
        echo -e "${GREEN}[✓] Homebrew already installed${NC}"
    fi
   
    # Install packages
    PACKAGES=("nmap" "netcat" "sqlite" "python3" "masscan")
   
    for package in "${PACKAGES[@]}"; do
        if ! brew list "$package" &> /dev/null; then
            echo -e "${ORANGE}[*] Installing $package...${NC}"
            brew install "$package" >> "$INSTALL_LOG" 2>&1 || {
                echo -e "${YELLOW}[!] Failed to install $package${NC}"
            }
        else
            echo -e "${GREEN}[✓] $package already installed${NC}"
        fi
    done
}

install_generic_deps() {
    echo -e "${ORANGE}[*] Attempting generic installation...${NC}\n"
   
    # Try common package managers
    if command -v apt-get &> /dev/null; then
        install_debian_deps
    elif command -v yum &> /dev/null || command -v dnf &> /dev/null; then
        install_redhat_deps
    elif command -v pacman &> /dev/null; then
        install_arch_deps
    else
        echo -e "${RED}[!] No supported package manager found${NC}"
        echo -e "${YELLOW}[!] Please install nmap, sqlite3, python3 manually${NC}"
    fi
}

install_python_deps() {
    echo -e "\n${ORANGE}[*] Installing Python dependencies...${NC}"
   
    # Ensure pip is available
    if ! command -v pip3 &> /dev/null; then
        echo -e "${ORANGE}[*] Installing pip...${NC}"
        if command -v python3 &> /dev/null; then
            python3 -m ensurepip --upgrade 2>/dev/null || {
                curl -sS https://bootstrap.pypa.io/get-pip.py | python3
            }
        fi
    fi
   
    # Install Python packages
    pip3 install --user --upgrade pip >> "$INSTALL_LOG" 2>&1 || true
    pip3 install --user python-crontab >> "$INSTALL_LOG" 2>&1 || {
        echo -e "${YELLOW}[!] Failed to install python-crontab${NC}"
    }
}

# ============================================================================
# SQLITE DATABASE SETUP
# ============================================================================

init_database() {
    if [ ! -f "$DB_FILE" ]; then
        echo -e "${ORANGE}[*] Initializing database...${NC}"
       
        sqlite3 "$DB_FILE" << 'EOF'
CREATE TABLE IF NOT EXISTS scans (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    scan_id TEXT UNIQUE NOT NULL,
    scan_type TEXT NOT NULL,
    start_time DATETIME NOT NULL,
    end_time DATETIME,
    status TEXT DEFAULT 'running',
    network_range TEXT,
    hosts_found INTEGER DEFAULT 0,
    ports_found INTEGER DEFAULT 0,
    vulnerabilities INTEGER DEFAULT 0,
    output_path TEXT,
    error_log TEXT
);

CREATE TABLE IF NOT EXISTS hosts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    scan_id TEXT NOT NULL,
    ip_address TEXT NOT NULL,
    hostname TEXT,
    mac_address TEXT,
    os_guess TEXT,
    status TEXT DEFAULT 'up',
    first_seen DATETIME NOT NULL,
    last_seen DATETIME NOT NULL,
    FOREIGN KEY (scan_id) REFERENCES scans(scan_id),
    UNIQUE(scan_id, ip_address)
);

CREATE TABLE IF NOT EXISTS ports (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    host_id INTEGER NOT NULL,
    port_number INTEGER NOT NULL,
    protocol TEXT NOT NULL,
    state TEXT NOT NULL,
    service TEXT,
    version TEXT,
    first_seen DATETIME NOT NULL,
    last_seen DATETIME NOT NULL,
    FOREIGN KEY (host_id) REFERENCES hosts(id),
    UNIQUE(host_id, port_number, protocol)
);

CREATE TABLE IF NOT EXISTS vulnerabilities (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    host_id INTEGER NOT NULL,
    port_id INTEGER,
    cve_id TEXT,
    vulnerability_name TEXT NOT NULL,
    severity TEXT,
    description TEXT,
    discovered_date DATETIME NOT NULL,
    FOREIGN KEY (host_id) REFERENCES hosts(id),
    FOREIGN KEY (port_id) REFERENCES ports(id)
);

CREATE TABLE IF NOT EXISTS scan_schedule (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    enabled INTEGER DEFAULT 1,
    interval_minutes INTEGER DEFAULT 60,
    scan_type TEXT DEFAULT 'discovery',
    last_run DATETIME,
    next_run DATETIME
);

-- Insert default schedule
INSERT OR IGNORE INTO scan_schedule (id, enabled, interval_minutes, scan_type)
VALUES (1, 1, 60, 'discovery');

CREATE INDEX IF NOT EXISTS idx_scans_date ON scans(start_time);
CREATE INDEX IF NOT EXISTS idx_hosts_ip ON hosts(ip_address);
CREATE INDEX IF NOT EXISTS idx_ports_number ON ports(port_number);
CREATE INDEX IF NOT EXISTS idx_vulns_severity ON vulnerabilities(severity);
EOF
       
        echo -e "${GREEN}[✓] Database initialized${NC}"
    else
        echo -e "${GREEN}[✓] Database already exists${NC}"
    fi
}

# Save scan to database
save_scan_to_db() {
    local scan_id=$1
    local scan_type=$2
    local status=$3
    local network_range=$4
    local output_path=$5
   
    sqlite3 "$DB_FILE" << EOF
INSERT OR REPLACE INTO scans (scan_id, scan_type, start_time, end_time, status, network_range, output_path)
VALUES (
    '$scan_id',
    '$scan_type',
    datetime('now'),
    datetime('now'),
    '$status',
    '$network_range',
    '$output_path'
);
EOF
}

# Update scan statistics
update_scan_stats() {
    local scan_id=$1
    local hosts=$2
    local ports=$3
    local vulns=$4
   
    sqlite3 "$DB_FILE" << EOF
UPDATE scans SET
    hosts_found = $hosts,
    ports_found = $ports,
    vulnerabilities = $vulns,
    end_time = datetime('now'),
    status = 'completed'
WHERE scan_id = '$scan_id';
EOF
}

# Save discovered host
save_host_to_db() {
    local scan_id=$1
    local ip=$2
    local hostname=${3:-""}
    local mac=${4:-""}
    local os=${5:-""}
   
    sqlite3 "$DB_FILE" << EOF
INSERT OR REPLACE INTO hosts (scan_id, ip_address, hostname, mac_address, os_guess, first_seen, last_seen, status)
VALUES (
    '$scan_id',
    '$ip',
    '$hostname',
    '$mac',
    '$os',
    datetime('now'),
    datetime('now'),
    'up'
);
EOF
}

# ============================================================================
# AUTO-START ON BOOT CONFIGURATION
# ============================================================================

setup_autostart() {
    echo -e "\n${CYAN}╔═══════════════════════════════════════════════════════════════════════╗${NC}"
    echo -e "${CYAN}║${WHITE}                    AUTO-START CONFIGURATION                          ${CYAN}║${NC}"
    echo -e "${CYAN}╚═══════════════════════════════════════════════════════════════════════╝${NC}\n"
   
    detect_os
   
    case "$OS" in
        "Linux"|"WSL")
            setup_systemd_service
            setup_cron_job
            ;;
        "macOS")
            setup_launchd_service
            ;;
        "Windows")
            echo -e "${ORANGE}[!] Windows autostart requires manual configuration${NC}"
            echo -e "${WHITE}Add to Task Scheduler: bash $0 --daemon${NC}"
            ;;
    esac
}

setup_systemd_service() {
    if command -v systemctl &> /dev/null; then
        echo -e "${ORANGE}[*] Setting up systemd service...${NC}"
       
        cat > /etc/systemd/system/looting-larry.service << EOF
[Unit]
Description=Looting Larry Network Security Scanner
After=network.target

[Service]
Type=forking
User=root
ExecStart=$0 --daemon
Restart=always
RestartSec=10
PIDFile=$DAEMON_PID_FILE

[Install]
WantedBy=multi-user.target
EOF
       
        systemctl daemon-reload
        systemctl enable looting-larry.service
       
        echo -e "${GREEN}[✓] Systemd service created and enabled${NC}"
    else
        echo -e "${YELLOW}[!] Systemd not available${NC}"
    fi
}

setup_cron_job() {
    echo -e "${ORANGE}[*] Setting up cron job for hourly scans...${NC}"
   
    # Remove existing cron job
    (crontab -l 2>/dev/null | grep -v "looting_larry") | crontab - 2>/dev/null || true
   
    # Add new cron job - runs every hour
    (crontab -l 2>/dev/null; echo "0 * * * * $0 --scan-once >> $LOGS_DIR/cron.log 2>&1") | crontab -
   
    # Also add @reboot
    (crontab -l 2>/dev/null; echo "@reboot $0 --daemon >> $LOGS_DIR/daemon.log 2>&1") | crontab -
   
    echo -e "${GREEN}[✓] Cron jobs configured${NC}"
    echo -e "${DIM}   - Hourly scans enabled${NC}"
    echo -e "${DIM}   - Auto-start on boot enabled${NC}"
}

setup_launchd_service() {
    echo -e "${ORANGE}[*] Setting up macOS LaunchDaemon...${NC}"
   
    PLIST_FILE="/Library/LaunchDaemons/com.lootinglarry.scanner.plist"
   
    cat > "$PLIST_FILE" << EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>com.lootinglarry.scanner</string>
    <key>ProgramArguments</key>
    <array>
        <string>/bin/bash</string>
        <string>$0</string>
        <string>--daemon</string>
    </array>
    <key>RunAtLoad</key>
    <true/>
    <key>KeepAlive</key>
    <true/>
    <key>StandardOutPath</key>
    <string>$LOGS_DIR/daemon.log</string>
    <key>StandardErrorPath</key>
    <string>$LOGS_DIR/daemon_error.log</string>
</dict>
</plist>
EOF
   
    chmod 644 "$PLIST_FILE"
    launchctl load "$PLIST_FILE" 2>/dev/null || true
   
    echo -e "${GREEN}[✓] LaunchDaemon configured${NC}"
}

# ============================================================================
# BACKGROUND DAEMON - RUNS PERSISTENT SCANS
# ============================================================================

run_daemon() {
    echo "$$" > "$DAEMON_PID_FILE"
   
    echo -e "${GREEN}[✓] Daemon started (PID: $$)${NC}"
    echo -e "${WHITE}Running hourly scans in background...${NC}\n"
   
    # Log daemon start
    echo "[$(date)] Daemon started" >> "$LOGS_DIR/daemon.log"
   
    while true; do
        # Check if system is in use (optional - skip if no user logged in)
        if who | grep -q .; then
            echo "[$(date)] Running scheduled scan..." >> "$LOGS_DIR/daemon.log"
           
            # Run discovery scan
            run_automated_scan "discovery"
           
            # Update last run time
            sqlite3 "$DB_FILE" "UPDATE scan_schedule SET last_run = datetime('now'), next_run = datetime('now', '+1 hour') WHERE id = 1;"
        else
            echo "[$(date)] System idle, skipping scan" >> "$LOGS_DIR/daemon.log"
        fi
       
        # Sleep for 1 hour
        sleep 3600
    done
}

run_automated_scan() {
    local scan_type=$1
    local scan_id="auto_$(date +%Y%m%d_%H%M%S)"
   
    # Get network range
    LOCAL_NETWORK=$(get_network_range)
   
    if [ -z "$LOCAL_NETWORK" ]; then
        echo "[ERROR] Could not detect network range" >> "$LOGS_DIR/daemon.log"
        return 1
    fi
   
    # Create output directory
    local output_dir="$SCANS_DIR/$scan_id"
    mkdir -p "$output_dir"
   
    # Save to database
    save_scan_to_db "$scan_id" "$scan_type" "running" "$LOCAL_NETWORK" "$output_dir"
   
    # Run scan
    case "$scan_type" in
        "discovery")
            nmap -sn "$LOCAL_NETWORK" -oN "$output_dir/hosts.txt" -oG "$output_dir/hosts.gnmap" >> "$LOGS_DIR/daemon.log" 2>&1
           
            # Parse results
            local hosts_found=$(grep -c "Host is up" "$output_dir/hosts.txt" 2>/dev/null || echo "0")
           
            # Save hosts to database
            grep "Host is up" "$output_dir/hosts.gnmap" 2>/dev/null | while read -r line; do
                local ip=$(echo "$line" | grep -oE '([0-9]{1,3}\.){3}[0-9]{1,3}')
                [ -n "$ip" ] && save_host_to_db "$scan_id" "$ip"
            done
           
            # Update stats
            update_scan_stats "$scan_id" "$hosts_found" "0" "0"
            ;;
        *)
            echo "[ERROR] Unknown scan type: $scan_type" >> "$LOGS_DIR/daemon.log"
            ;;
    esac
   
    echo "[$(date)] Scan $scan_id completed: $hosts_found hosts found" >> "$LOGS_DIR/daemon.log"
}

# ============================================================================
# NETWORK UTILITY FUNCTIONS
# ============================================================================

get_network_range() {
    case "$OS" in
        "Linux"|"WSL")
            if command -v ip &> /dev/null; then
                ip route | grep -v default | grep -E "192.168|10\.|172\.(1[6-9]|2[0-9]|3[0-1])\." | head -1 | awk '{print $1}'
            else
                route -n | grep -E "192.168|10\.|172\.(1[6-9]|2[0-9]|3[0-1])\." | head -1 | awk '{print $1}'
            fi
            ;;
        "macOS")
            netstat -rn | grep -E "192.168|10\.|172\.(1[6-9]|2[0-9]|3[0-1])\." | head -1 | awk '{print $1}'
            ;;
        "Windows")
            local local_ip=$(ipconfig.exe 2>/dev/null | grep "IPv4" | head -1 | awk '{print $NF}' | tr -d '\r')
            if [[ $local_ip =~ ^([0-9]+\.[0-9]+\.[0-9]+)\. ]]; then
                echo "${BASH_REMATCH[1]}.0/24"
            fi
            ;;
    esac
}

get_local_ip() {
    case "$OS" in
        "Linux"|"WSL")
            ip addr show 2>/dev/null | grep "inet " | grep -v "127.0.0.1" | head -1 | awk '{print $2}' | cut -d'/' -f1 || \
            ifconfig 2>/dev/null | grep "inet " | grep -v "127.0.0.1" | head -1 | awk '{print $2}'
            ;;
        "macOS")
            ifconfig | grep "inet " | grep -v "127.0.0.1" | head -1 | awk '{print $2}'
            ;;
        "Windows")
            ipconfig.exe 2>/dev/null | grep "IPv4" | head -1 | awk '{print $NF}' | tr -d '\r'
            ;;
    esac
}

get_gateway() {
    case "$OS" in
        "Linux"|"WSL")
            ip route 2>/dev/null | grep default | awk '{print $3}' | head -1 || \
            route -n 2>/dev/null | grep "^0.0.0.0" | awk '{print $2}' | head -1
            ;;
        "macOS")
            route -n get default 2>/dev/null | grep gateway | awk '{print $2}'
            ;;
        "Windows")
            ipconfig.exe 2>/dev/null | grep "Default Gateway" | head -1 | awk '{print $NF}' | tr -d '\r'
            ;;
    esac
}

# ============================================================================
# ASCII BANNER
# ============================================================================

show_banner() {
    clear
    echo -e "${RED}"
    cat << "EOF"
    ╔═══════════════════════════════════════════════════════════════════════╗
    ║                                                                       ║
    ║           ██╗      ██████╗  ██████╗ ████████╗██╗███╗   ██╗ ██████╗  ║
    ║           ██║     ██╔═══██╗██╔═══██╗╚══██╔══╝██║████╗  ██║██╔════╝  ║
    ║           ██║     ██║   ██║██║   ██║   ██║   ██║██╔██╗ ██║██║  ███╗ ║
    ║           ██║     ██║   ██║██║   ██║   ██║   ██║██║╚██╗██║██║   ██║ ║
    ║           ███████╗╚██████╔╝╚██████╔╝   ██║   ██║██║ ╚████║╚██████╔╝ ║
    ║           ╚══════╝ ╚═════╝  ╚═════╝    ╚═╝   ╚═╝╚═╝  ╚═══╝ ╚═════╝  ║
    ║                                                                       ║
EOF
    echo -e "${ORANGE}"
    cat << "EOF"
    ║              ██╗      █████╗ ██████╗ ██████╗ ██╗   ██╗               ║
    ║              ██║     ██╔══██╗██╔══██╗██╔══██╗╚██╗ ██╔╝               ║
    ║              ██║     ███████║██████╔╝██████╔╝ ╚████╔╝                ║
    ║              ██║     ██╔══██║██╔══██╗██╔══██╗  ╚██╔╝                 ║
    ║              ███████╗██║  ██║██║  ██║██║  ██║   ██║                  ║
    ║              ╚══════╝╚═╝  ╚═╝╚═╝  ╚═╝╚═╝  ╚═╝   ╚═╝                  ║
    ║                                                                       ║
EOF
    echo -e "${RED}"
    cat << "EOF"
    ║                        ___                                            ║
    ║                      .'   '.         _____                            ║
    ║                     /       \    _.-'     '-.                         ║
    ║                    |  O   O  | .'             '.                      ║
    ║                    |    >    |/                 \                     ║
    ║                    |  \___/  |      NETWORK      |                    ║
    ║                     \       /|     SECURITY      |                    ║
    ║                      '.___.' |      SCANNER      |                    ║
    ║                    _____|_____|_________________/                     ║
    ║                   /     |     |                                       ║
    ║                  /      |     |    "Arr! Plunderin' yer ports"       ║
    ║                 |_______|_____|                                       ║
    ║                         |                                             ║
    ║                        / \                                            ║
    ║                       /   \                                           ║
    ║                      /     \                                          ║
    ║                     /_______\                                         ║
    ║                                                                       ║
    ║              Enterprise Network Security Suite - ULTIMATE             ║
    ║                Self-Installing • Auto-Running • Persistent            ║
    ╚═══════════════════════════════════════════════════════════════════════╝
EOF
    echo -e "${NC}"
}

# ============================================================================
# INTERACTIVE MENU FUNCTIONS
# ============================================================================

show_network_info() {
    echo -e "${CYAN}╔═══════════════════════════════════════════════════════════════════════╗${NC}"
    echo -e "${CYAN}║${WHITE}                     NETWORK CONFIGURATION STATUS                      ${CYAN}║${NC}"
    echo -e "${CYAN}╚═══════════════════════════════════════════════════════════════════════╝${NC}\n"
   
    LOCAL_IP=$(get_local_ip)
    GATEWAY=$(get_gateway)
    LOCAL_NETWORK=$(get_network_range)
   
    echo -e "${WHITE}Local IP Address:${NC}      ${PURPLE}${LOCAL_IP:-Unable to detect}${NC}"
    echo -e "${WHITE}Default Gateway:${NC}       ${PURPLE}${GATEWAY:-Unable to detect}${NC}"
    echo -e "${WHITE}Local Network Range:${NC}   ${PURPLE}${LOCAL_NETWORK:-Unable to detect}${NC}"
   
    if command -v curl &> /dev/null; then
        PUBLIC_IP=$(curl -s --max-time 5 ifconfig.me 2>/dev/null || echo "Unable to fetch")
        echo -e "${WHITE}Public IP Address:${NC}     ${PURPLE}$PUBLIC_IP${NC}"
       
        if [ "$PUBLIC_IP" = "151.245.80.158" ]; then
            echo -e "${WHITE}VPN Status:${NC}            ${GREEN}✓ NordVPN ACTIVE${NC}"
        elif [ "$PUBLIC_IP" != "Unable to fetch" ]; then
            echo -e "${WHITE}VPN Status:${NC}            ${ORANGE}⚠ Different IP or No VPN${NC}"
        fi
    fi
   
    echo ""
}

show_daemon_status() {
    echo -e "${CYAN}╔═══════════════════════════════════════════════════════════════════════╗${NC}"
    echo -e "${CYAN}║${WHITE}                        DAEMON STATUS                                  ${CYAN}║${NC}"
    echo -e "${CYAN}╚═══════════════════════════════════════════════════════════════════════╝${NC}\n"
   
    if [ -f "$DAEMON_PID_FILE" ]; then
        DAEMON_PID=$(cat "$DAEMON_PID_FILE")
        if ps -p "$DAEMON_PID" > /dev/null 2>&1; then
            echo -e "${WHITE}Daemon Status:${NC}         ${GREEN}✓ RUNNING${NC} ${DIM}(PID: $DAEMON_PID)${NC}"
        else
            echo -e "${WHITE}Daemon Status:${NC}         ${RED}✗ STOPPED${NC}"
        fi
    else
        echo -e "${WHITE}Daemon Status:${NC}         ${RED}✗ NOT STARTED${NC}"
    fi
   
    # Get last scan from database
    if [ -f "$DB_FILE" ]; then
        LAST_SCAN=$(sqlite3 "$DB_FILE" "SELECT start_time FROM scans ORDER BY start_time DESC LIMIT 1;" 2>/dev/null)
        TOTAL_SCANS=$(sqlite3 "$DB_FILE" "SELECT COUNT(*) FROM scans;" 2>/dev/null)
        TOTAL_HOSTS=$(sqlite3 "$DB_FILE" "SELECT COUNT(DISTINCT ip_address) FROM hosts;" 2>/dev/null)
       
        echo -e "${WHITE}Last Scan:${NC}             ${PURPLE}${LAST_SCAN:-Never}${NC}"
        echo -e "${WHITE}Total Scans:${NC}           ${GREEN}${TOTAL_SCANS:-0}${NC}"
        echo -e "${WHITE}Unique Hosts Found:${NC}    ${GREEN}${TOTAL_HOSTS:-0}${NC}"
    fi
   
    echo ""
}

show_menu() {
    echo -e "${CYAN}╔═══════════════════════════════════════════════════════════════════════╗${NC}"
    echo -e "${CYAN}║${WHITE}                         OPERATION MENU                                ${CYAN}║${NC}"
    echo -e "${CYAN}╚═══════════════════════════════════════════════════════════════════════╝${NC}\n"
   
    echo -e "${WHITE}[${RED}1${WHITE}]${NC} Run Network Discovery Now   ${DIM}(Immediate scan)${NC}"
    echo -e "${WHITE}[${RED}2${WHITE}]${NC} View Scan History           ${DIM}(Database records)${NC}"
    echo -e "${WHITE}[${RED}3${WHITE}]${NC} View Discovered Hosts       ${DIM}(All found devices)${NC}"
    echo -e "${WHITE}[${RED}4${WHITE}]${NC} Start Background Daemon     ${DIM}(Hourly auto-scans)${NC}"
    echo -e "${WHITE}[${RED}5${WHITE}]${NC} Stop Background Daemon      ${DIM}(Disable auto-scans)${NC}"
    echo -e "${WHITE}[${RED}6${WHITE}]${NC} Configure Auto-Start        ${DIM}(Run on boot)${NC}"
    echo -e "${WHITE}[${RED}7${WHITE}]${NC} System Diagnostics          ${DIM}(Check installation)${NC}"
    echo -e "${WHITE}[${RED}8${WHITE}]${NC} Database Statistics         ${DIM}(View all data)${NC}"
    echo -e "${WHITE}[${RED}0${WHITE}]${NC} Exit\n"
   
    echo -e -n "${ORANGE}looting-larry@$OS>${NC} "
}

# Manual scan function
run_manual_scan() {
    clear
    show_banner
    echo -e "\n${RED}╔═══════════════════════════════════════════════════════════════════════╗${NC}"
    echo -e "${RED}║${WHITE}                    MANUAL NETWORK DISCOVERY                           ${RED}║${NC}"
    echo -e "${RED}╚═══════════════════════════════════════════════════════════════════════╝${NC}\n"
   
    LOCAL_NETWORK=$(get_network_range)
   
    if [ -z "$LOCAL_NETWORK" ]; then
        echo -e "${ORANGE}[!] Could not auto-detect network${NC}"
        echo -e -n "${WHITE}Enter network range (e.g., 192.168.1.0/24):${NC} "
        read LOCAL_NETWORK
    fi
   
    SCAN_ID="manual_$(date +%Y%m%d_%H%M%S)"
    OUTPUT_DIR="$SCANS_DIR/$SCAN_ID"
    mkdir -p "$OUTPUT_DIR"
   
    echo -e "${WHITE}Target Network:${NC}    ${PURPLE}$LOCAL_NETWORK${NC}"
    echo -e "${WHITE}Scan ID:${NC}           ${PURPLE}$SCAN_ID${NC}\n"
   
    echo -e "${ORANGE}[*] Starting discovery scan...${NC}\n"
   
    save_scan_to_db "$SCAN_ID" "manual_discovery" "running" "$LOCAL_NETWORK" "$OUTPUT_DIR"
   
    nmap -sn "$LOCAL_NETWORK" -oN "$OUTPUT_DIR/hosts.txt" -oG "$OUTPUT_DIR/hosts.gnmap" 2>&1 | while IFS= read -r line; do
        if [[ $line =~ ([0-9]{1,3}\.){3}[0-9]{1,3} ]]; then
            IP=$(echo "$line" | grep -oE '([0-9]{1,3}\.){3}[0-9]{1,3}')
            echo -e "${GREEN}[+]${NC} Host discovered: ${PURPLE}$IP${NC}"
            save_host_to_db "$SCAN_ID" "$IP"
        fi
    done
   
    HOSTS_FOUND=$(grep -c "Host is up" "$OUTPUT_DIR/hosts.txt" 2>/dev/null || echo "0")
    update_scan_stats "$SCAN_ID" "$HOSTS_FOUND" "0" "0"
   
    echo -e "\n${GREEN}╔═══════════════════════════════════════════════════════════════════════╗${NC}"
    echo -e "${GREEN}║${WHITE}                        SCAN COMPLETE                                  ${GREEN}║${NC}"
    echo -e "${GREEN}╚═══════════════════════════════════════════════════════════════════════╝${NC}\n"
   
    echo -e "${WHITE}Hosts Found:${NC}       ${GREEN}$HOSTS_FOUND${NC}"
    echo -e "${WHITE}Results:${NC}           ${PURPLE}$OUTPUT_DIR${NC}\n"
   
    read -p "Press ENTER to continue..."
}

# View scan history
view_scan_history() {
    clear
    show_banner
    echo -e "\n${CYAN}╔═══════════════════════════════════════════════════════════════════════╗${NC}"
    echo -e "${CYAN}║${WHITE}                        SCAN HISTORY                                   ${CYAN}║${NC}"
    echo -e "${CYAN}╚═══════════════════════════════════════════════════════════════════════╝${NC}\n"
   
    if [ ! -f "$DB_FILE" ]; then
        echo -e "${ORANGE}[!] No scan history found${NC}\n"
        read -p "Press ENTER to continue..."
        return
    fi
   
    sqlite3 -header -column "$DB_FILE" "SELECT scan_id, scan_type, start_time, hosts_found, status FROM scans ORDER BY start_time DESC LIMIT 20;"
   
    echo ""
    read -p "Press ENTER to continue..."
}

# View all discovered hosts
view_discovered_hosts() {
    clear
    show_banner
    echo -e "\n${CYAN}╔═══════════════════════════════════════════════════════════════════════╗${NC}"
    echo -e "${CYAN}║${WHITE}                      DISCOVERED HOSTS                                 ${CYAN}║${NC}"
    echo -e "${CYAN}╚═══════════════════════════════════════════════════════════════════════╝${NC}\n"
   
    if [ ! -f "$DB_FILE" ]; then
        echo -e "${ORANGE}[!] No hosts in database${NC}\n"
        read -p "Press ENTER to continue..."
        return
    fi
   
    sqlite3 -header -column "$DB_FILE" "SELECT DISTINCT ip_address, hostname, first_seen, last_seen FROM hosts ORDER BY last_seen DESC LIMIT 50;"
   
    echo ""
    read -p "Press ENTER to continue..."
}

# Start daemon
start_daemon() {
    if [ -f "$DAEMON_PID_FILE" ]; then
        DAEMON_PID=$(cat "$DAEMON_PID_FILE")
        if ps -p "$DAEMON_PID" > /dev/null 2>&1; then
            echo -e "${ORANGE}[!] Daemon already running (PID: $DAEMON_PID)${NC}\n"
            read -p "Press ENTER to continue..."
            return
        fi
    fi
   
    echo -e "${ORANGE}[*] Starting background daemon...${NC}\n"
   
    # Start daemon in background
    nohup bash "$0" --daemon > "$LOGS_DIR/daemon.log" 2>&1 &
   
    sleep 2
   
    if [ -f "$DAEMON_PID_FILE" ]; then
        echo -e "${GREEN}[✓] Daemon started successfully${NC}\n"
    else
        echo -e "${RED}[!] Failed to start daemon${NC}\n"
    fi
   
    read -p "Press ENTER to continue..."
}

# Stop daemon
stop_daemon() {
    if [ ! -f "$DAEMON_PID_FILE" ]; then
        echo -e "${ORANGE}[!] Daemon not running${NC}\n"
        read -p "Press ENTER to continue..."
        return
    fi
   
    DAEMON_PID=$(cat "$DAEMON_PID_FILE")
   
    if ps -p "$DAEMON_PID" > /dev/null 2>&1; then
        echo -e "${ORANGE}[*] Stopping daemon (PID: $DAEMON_PID)...${NC}"
        kill "$DAEMON_PID"
        rm -f "$DAEMON_PID_FILE"
        echo -e "${GREEN}[✓] Daemon stopped${NC}\n"
    else
        echo -e "${ORANGE}[!] Daemon not running${NC}"
        rm -f "$DAEMON_PID_FILE"
    fi
   
    read -p "Press ENTER to continue..."
}

# Database statistics
show_db_stats() {
    clear
    show_banner
    echo -e "\n${CYAN}╔═══════════════════════════════════════════════════════════════════════╗${NC}"
    echo -e "${CYAN}║${WHITE}                     DATABASE STATISTICS                               ${CYAN}║${NC}"
    echo -e "${CYAN}╚═══════════════════════════════════════════════════════════════════════╝${NC}\n"
   
    if [ ! -f "$DB_FILE" ]; then
        echo -e "${ORANGE}[!] Database not initialized${NC}\n"
        read -p "Press ENTER to continue..."
        return
    fi
   
    TOTAL_SCANS=$(sqlite3 "$DB_FILE" "SELECT COUNT(*) FROM scans;" 2>/dev/null)
    TOTAL_HOSTS=$(sqlite3 "$DB_FILE" "SELECT COUNT(DISTINCT ip_address) FROM hosts;" 2>/dev/null)
    TOTAL_PORTS=$(sqlite3 "$DB_FILE" "SELECT COUNT(*) FROM ports;" 2>/dev/null)
    TOTAL_VULNS=$(sqlite3 "$DB_FILE" "SELECT COUNT(*) FROM vulnerabilities;" 2>/dev/null)
   
    echo -e "${WHITE}Total Scans:${NC}           ${GREEN}${TOTAL_SCANS:-0}${NC}"
    echo -e "${WHITE}Unique Hosts:${NC}          ${GREEN}${TOTAL_HOSTS:-0}${NC}"
    echo -e "${WHITE}Open Ports:${NC}            ${GREEN}${TOTAL_PORTS:-0}${NC}"
    echo -e "${WHITE}Vulnerabilities:${NC}       ${ORANGE}${TOTAL_VULNS:-0}${NC}"
   
    echo -e "\n${WHITE}Most Recent Scans:${NC}\n"
    sqlite3 -header -column "$DB_FILE" "SELECT scan_type, start_time, hosts_found FROM scans ORDER BY start_time DESC LIMIT 5;"
   
    echo -e "\n${WHITE}Most Active Hosts:${NC}\n"
    sqlite3 -header -column "$DB_FILE" "SELECT ip_address, COUNT(*) as seen_count FROM hosts GROUP BY ip_address ORDER BY seen_count DESC LIMIT 5;"
   
    echo ""
    read -p "Press ENTER to continue..."
}

# System diagnostics
system_diagnostics() {
    clear
    show_banner
    echo -e "\n${CYAN}╔═══════════════════════════════════════════════════════════════════════╗${NC}"
    echo -e "${CYAN}║${WHITE}                        SYSTEM DIAGNOSTICS                             ${CYAN}║${NC}"
    echo -e "${CYAN}╚═══════════════════════════════════════════════════════════════════════╝${NC}\n"
   
    echo -e "${WHITE}Operating System:${NC}      $OS ($DISTRO)"
    echo -e "${WHITE}Hostname:${NC}              $(hostname)"
    echo -e "${WHITE}User:${NC}                  $(whoami)"
   
    if [ "$EUID" -eq 0 ]; then
        echo -e "${WHITE}Privileges:${NC}            ${GREEN}ROOT${NC}"
    else
        echo -e "${WHITE}Privileges:${NC}            ${ORANGE}USER${NC}"
    fi
   
    echo -e "\n${WHITE}Tool Status:${NC}\n"
   
    command -v nmap &> /dev/null && echo -e "${GREEN}[✓]${NC} nmap" || echo -e "${RED}[✗]${NC} nmap"
    command -v sqlite3 &> /dev/null && echo -e "${GREEN}[✓]${NC} sqlite3" || echo -e "${RED}[✗]${NC} sqlite3"
    command -v python3 &> /dev/null && echo -e "${GREEN}[✓]${NC} python3" || echo -e "${RED}[✗]${NC} python3"
    command -v curl &> /dev/null && echo -e "${GREEN}[✓]${NC} curl" || echo -e "${RED}[✗]${NC} curl"
   
    echo -e "\n${WHITE}Installation Status:${NC}\n"
   
    [ -d "$SUITE_DIR" ] && echo -e "${GREEN}[✓]${NC} Suite directory" || echo -e "${RED}[✗]${NC} Suite directory"
    [ -f "$DB_FILE" ] && echo -e "${GREEN}[✓]${NC} Database" || echo -e "${RED}[✗]${NC} Database"
    [ -f "$DAEMON_PID_FILE" ] && echo -e "${GREEN}[✓]${NC} Daemon running" || echo -e "${ORANGE}[!]${NC} Daemon not running"
   
    # Check cron
    if crontab -l 2>/dev/null | grep -q "looting_larry"; then
        echo -e "${GREEN}[✓]${NC} Cron job configured"
    else
        echo -e "${ORANGE}[!]${NC} Cron job not configured"
    fi
   
    echo ""
    read -p "Press ENTER to continue..."
}

# ============================================================================
# MAIN PROGRAM
# ============================================================================

main_menu() {
    while true; do
        show_banner
        show_network_info
        show_daemon_status
        show_menu
       
        read -r choice
       
        case $choice in
            1) run_manual_scan ;;
            2) view_scan_history ;;
            3) view_discovered_hosts ;;
            4) start_daemon ;;
            5) stop_daemon ;;
            6) setup_autostart ;;
            7) system_diagnostics ;;
            8) show_db_stats ;;
            0)
                clear
                show_banner
                echo -e "\n${GREEN}╔═══════════════════════════════════════════════════════════════════════╗${NC}"
                echo -e "${GREEN}║${WHITE}             Thank you for using Looting Larry Security Suite           ${GREEN}║${NC}"
                echo -e "${GREEN}║${WHITE}                       Stay secure, matey!                             ${GREEN}║${NC}"
                echo -e "${GREEN}╚═══════════════════════════════════════════════════════════════════════╝${NC}\n"
                exit 0
                ;;
            *)
                echo -e "\n${RED}[!] Invalid selection${NC}"
                sleep 1
                ;;
        esac
    done
}

# ============================================================================
# ENTRY POINT
# ============================================================================

# Parse command line arguments
case "${1:-}" in
    --install)
        show_banner
        install_dependencies
        init_database
        setup_autostart
        echo -e "\n${GREEN}[✓] Installation complete!${NC}\n"
        exit 0
        ;;
    --daemon)
        init_database
        run_daemon
        ;;
    --scan-once)
        init_database
        run_automated_scan "discovery"
        exit 0
        ;;
    --help)
        echo "Looting Larry - Ultimate Security Suite"
        echo ""
        echo "Usage:"
        echo "  $0              Start interactive menu"
        echo "  $0 --install    Install all dependencies"
        echo "  $0 --daemon     Run background daemon"
        echo "  $0 --scan-once  Run single scan"
        exit 0
        ;;
    *)
        # First run setup
        if [ ! -f "$DB_FILE" ] || ! command -v nmap &> /dev/null; then
            show_banner
            echo -e "${ORANGE}[*] First-time setup detected${NC}\n"
            install_dependencies
            init_database
           
            echo -e "\n${CYAN}Would you like to enable auto-start on boot?${NC}"
            read -p "(y/n): " choice
            if [ "$choice" = "y" ]; then
                setup_autostart
            fi
           
            echo ""
            read -p "Press ENTER to continue to main menu..."
        else
            init_database
        fi
       
        # Start interactive menu
        main_menu
        ;;
esac
