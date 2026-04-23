#!/usr/bin/env python3
"""
Security Sentinel — "ROBIN" — Local Larry's Sidekick
====================================================================
Batman (you) and Robin (Local Larry / the Sentinel) keep Gotham safe.
Runs on a 15-minute cycle using dolphin-mistral (tiny VRAM footprint).
Robin monitors the Batcave for threats, remembers past conversations,
and reports to Batman via Telegram with personality.

Checks:
  - New listening ports (unexpected services)
  - Failed SSH login attempts
  - Suspicious processes (high CPU/memory, unknown binaries)
  - Network connection anomalies (new outbound connections)
  - File integrity (critical config changes)
  - Disk/memory pressure
  - VPN status changes

Resource budget: <200MB VRAM, <2% CPU average
"""

import os
import sys
import json
import time
import socket
import hashlib
import logging
import subprocess
from pathlib import Path
from datetime import datetime, timedelta
from typing import Optional

import psutil

try:
    from activity_stream import ActivityStream
    _activity = ActivityStream("sentinel")
except ImportError:
    _activity = None

# SecurityCommandCenter + BashScriptRunner integration
try:
    from security_command_center import SecurityCommandCenter
    from bash_script_runner import BashScriptRunner
    _sec = SecurityCommandCenter()
    _bash = BashScriptRunner()
    SCC_AVAILABLE = True
except Exception as _scc_err:
    _sec = None
    _bash = None
    SCC_AVAILABLE = False

# ── Config ─────────────────────────────────────────────────────────
SCRIPT_DIR = Path(__file__).parent.resolve()
STATE_FILE = SCRIPT_DIR / "logs" / "sentinel_state.json"
LOG_FILE = SCRIPT_DIR / "logs" / "sentinel.log"
(SCRIPT_DIR / "logs").mkdir(exist_ok=True)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [ROBIN] %(message)s",
    handlers=[logging.FileHandler(LOG_FILE, encoding="utf-8")],
)
log = logging.getLogger(__name__)

# Telegram config from .env
ENV_FILE = SCRIPT_DIR / ".env"
def load_env():
    env = {}
    if ENV_FILE.exists():
        for line in ENV_FILE.read_text().splitlines():
            if "=" in line and not line.startswith("#"):
                k, v = line.split("=", 1)
                env[k.strip()] = v.strip()
    return env

env = load_env()
TELEGRAM_TOKEN = env.get("TELEGRAM_BOT_TOKEN", os.environ.get("TELEGRAM_BOT_TOKEN", ""))
TELEGRAM_CHAT_ID = env.get("TELEGRAM_ALLOWED_CHAT_IDS", os.environ.get("TELEGRAM_ALLOWED_CHAT_IDS", ""))
OLLAMA_URL = "http://localhost:11434"
SENTINEL_MODEL = "dolphin-mistral:latest"

# Check interval (seconds)
CHECK_INTERVAL = 900   # 15 minutes (was 5m — reduced Telegram noise)
AI_ANALYSIS_INTERVAL = 3600  # 60 minutes — only call AI every 60 min to save resources
SCC_SCAN_INTERVAL = 3600  # 60 minutes — run SCC tool scans (was 30m)

# Thresholds
CPU_ALERT_PCT = 90
MEM_ALERT_PCT = 92
DISK_ALERT_PCT = 95
MAX_UNEXPECTED_PORTS = 3

# Trusted ports (won't trigger alerts)
TRUSTED_PORTS = {
    22, 80, 443, 631, 5000, 5562, 8000, 8080, 8081,
    11434,  # Ollama
    53,     # DNS
}

# Trusted process names
TRUSTED_PROCS = {
    "systemd", "gnome-shell", "Xwayland", "gnome-terminal", "bash", "python3",
    "python", "node", "ollama", "brave", "code", "claude", "nautilus",
    "pipewire", "wireplumber", "dbus-daemon", "gdm-session-worker",
}


# ── Alert Deduplication (suppress repeated Telegram spam) ────────
# Only send Telegram when alert state CHANGES, not every cycle
_prev_alert_state: str = "clear"       # "clear" or "alert"
_prev_alert_fingerprint: str = ""      # hash of sorted alert strings
_consecutive_clear: int = 0            # count of consecutive clear cycles

def _alert_fingerprint(alerts: list) -> str:
    """Hash the sorted alert set so we can detect duplicates."""
    return hashlib.md5("|".join(sorted(alerts)).encode()).hexdigest()

def should_telegram(alerts: list) -> bool:
    """Decide whether this cycle warrants a Telegram notification.
    Rules:
      - alert→clear transition: Telegram once ("all clear")
      - clear→alert transition: Telegram immediately
      - alert→alert with SAME alerts: suppress (already notified)
      - alert→alert with DIFFERENT alerts: Telegram (new problem)
      - clear→clear: never Telegram (dashboard + log only)
    """
    global _prev_alert_state, _prev_alert_fingerprint, _consecutive_clear

    if alerts:
        fp = _alert_fingerprint(alerts)
        new_state = "alert"
    else:
        fp = ""
        new_state = "clear"

    # Determine if we should notify
    notify = False

    if new_state == "alert":
        if _prev_alert_state == "clear":
            # Transition: clear → alert → always notify
            notify = True
        elif fp != _prev_alert_fingerprint:
            # Same state but different alerts → notify
            notify = True
        # else: same alerts as last cycle → suppress
        _consecutive_clear = 0

    elif new_state == "clear":
        if _prev_alert_state == "alert":
            # Transition: alert → clear → notify once
            notify = True
        _consecutive_clear += 1
        # Never spam "all clear" on consecutive clear cycles

    _prev_alert_state = new_state
    _prev_alert_fingerprint = fp
    return notify


# ── State Management ──────────────────────────────────────────────

def load_state() -> dict:
    if STATE_FILE.exists():
        try:
            return json.loads(STATE_FILE.read_text())
        except Exception:
            pass
    return {
        "known_ports": [],
        "known_connections": 0,
        "last_ai_check": 0,
        "alert_count": 0,
        "vpn_was_up": False,
        "critical_hashes": {},
    }

def save_state(state: dict):
    STATE_FILE.write_text(json.dumps(state, indent=2))


# ── Robin's Memory (Conversation History) ─────────────────────────

MEMORY_FILE = SCRIPT_DIR / "logs" / "robin_memory.jsonl"
MAX_MEMORY_ENTRIES = 200

def load_memory(last_n: int = 10) -> list:
    """Load the last N conversation entries from Robin's memory."""
    entries = []
    try:
        if MEMORY_FILE.exists():
            lines = MEMORY_FILE.read_text(errors="replace").strip().splitlines()
            for line in lines[-last_n:]:
                try:
                    entries.append(json.loads(line))
                except json.JSONDecodeError:
                    pass
    except Exception as e:
        log.warning(f"Memory load failed: {e}")
    return entries

def save_memory(entry: dict):
    """Append a conversation entry to Robin's memory log."""
    try:
        entry["timestamp"] = datetime.now().isoformat()
        with open(MEMORY_FILE, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry) + "\n")
        # Trim if too large
        _trim_memory()
    except Exception as e:
        log.warning(f"Memory save failed: {e}")

def _trim_memory():
    """Keep memory file under MAX_MEMORY_ENTRIES lines."""
    try:
        if not MEMORY_FILE.exists():
            return
        lines = MEMORY_FILE.read_text().strip().splitlines()
        if len(lines) > MAX_MEMORY_ENTRIES:
            MEMORY_FILE.write_text("\n".join(lines[-MAX_MEMORY_ENTRIES:]) + "\n")
    except Exception:
        pass

def format_memory_context(entries: list) -> str:
    """Format memory entries into a context string for the AI."""
    if not entries:
        return "No previous patrol logs."
    lines = []
    for e in entries:
        ts = e.get("timestamp", "?")[:16]
        role = e.get("role", "system")
        msg = e.get("message", "")
        lines.append(f"[{ts}] {role}: {msg}")
    return "\n".join(lines)


# ── Robin's Personality ───────────────────────────────────────────

ROBIN_SYSTEM_PROMPT = """You are Robin — Local Larry's AI sidekick. Batman (the user, Larry) is your partner.
You speak like a loyal, sharp, slightly witty sidekick. You call the user "Batman" or "Boss".
You refer to the system as "the Batcave" and threats as "villains" or "trouble in Gotham".
You're street-smart, concise, and always have Batman's back.

Personality rules:
- Keep it SHORT (2-4 sentences max)
- Be casual but competent — you know your stuff
- Use light humor but take real threats seriously
- Reference past patrols/convos when relevant ("Last time we saw this...")
- Rate threats as: ALL CLEAR / HEADS UP / RED ALERT / CODE BLACK
- Sign off with a quick Robin-ism when appropriate

You are NOT over-the-top corny. You're cool, capable, and reliable."""


# ── Telegram Command Polling + Port Block Approval ────────────────

# pending approvals: {token: {"action": "block_port", "port": int, "direction": str, "expires": float}}
_pending_approvals: dict = {}
_last_update_id: int = 0

# Safe range — never block system ports or Ollama/dashboard without explicit override
_NEVER_BLOCK = {22, 53, 80, 443, 3777, 11434}

def _telegram_get_updates() -> list:
    """Poll Telegram for new messages. Returns list of update dicts."""
    global _last_update_id
    if not TELEGRAM_TOKEN:
        return []
    try:
        import requests
        url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/getUpdates"
        r = requests.get(url, params={"offset": _last_update_id + 1, "timeout": 5}, timeout=10)
        if r.status_code != 200:
            return []
        updates = r.json().get("result", [])
        if updates:
            _last_update_id = updates[-1]["update_id"]
        return updates
    except Exception:
        return []


def _is_authorised_chat(chat_id) -> bool:
    """Verify the message came from the configured chat ID."""
    allowed = str(TELEGRAM_CHAT_ID).split(",")
    return str(chat_id) in [x.strip() for x in allowed]


def _apply_firewall_block(port: int, direction: str = "in") -> tuple:
    """
    Apply ufw rule to block a port. Returns (success, message).
    direction: 'in' | 'out' | 'both'
    """
    try:
        cmds = []
        if direction in ("in", "both"):
            cmds.append(["sudo", "ufw", "deny", "in", str(port)])
        if direction in ("out", "both"):
            cmds.append(["sudo", "ufw", "deny", "out", str(port)])

        for cmd in cmds:
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=15)
            if result.returncode != 0:
                return False, f"ufw error: {result.stderr.strip() or result.stdout.strip()}"

        log.info(f"Port {port} blocked ({direction}) via ufw")
        save_memory({"role": "robin", "message": f"Blocked port {port} ({direction}) on Batman's orders."})
        return True, f"Port {port} blocked ({direction})"
    except FileNotFoundError:
        return False, "ufw not found — install with: sudo apt install ufw"
    except subprocess.TimeoutExpired:
        return False, "ufw command timed out"
    except Exception as e:
        return False, str(e)


def _send_block_approval_request(port: int, direction: str, token: str):
    """Send an inline-keyboard approval message for a port block."""
    import requests
    if not TELEGRAM_TOKEN or not TELEGRAM_CHAT_ID:
        return
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    text = (
        f"⚠️ <b>PORT BLOCK REQUEST</b>\n\n"
        f"Batman, shall I block port <code>{port}</code> ({direction})?\n\n"
        f"Reply with:\n"
        f"  <code>/approve {token}</code> — to confirm\n"
        f"  <code>/deny {token}</code>   — to cancel\n\n"
        f"<i>Approval token expires in 10 minutes.</i>"
    )
    try:
        requests.post(url, json={
            "chat_id": TELEGRAM_CHAT_ID,
            "text": text,
            "parse_mode": "HTML",
        }, timeout=10)
    except Exception:
        pass


def _handle_telegram_commands(updates: list):
    """Process incoming Telegram commands from Batman."""
    import secrets as _secrets
    now = time.time()

    # Prune expired approvals
    expired = [t for t, v in _pending_approvals.items() if v["expires"] < now]
    for t in expired:
        del _pending_approvals[t]

    for update in updates:
        msg = update.get("message", {})
        text = (msg.get("text") or "").strip()
        chat_id = msg.get("chat", {}).get("id")

        if not text or not _is_authorised_chat(chat_id):
            continue

        cmd = text.split()[0].lower()
        args = text.split()[1:]

        # /block <port> [in|out|both]
        if cmd == "/block":
            if not args:
                send_telegram("Usage: <code>/block &lt;port&gt; [in|out|both]</code>", "HTML")
                continue
            try:
                port = int(args[0])
            except ValueError:
                send_telegram(f"⚠️ Invalid port: <code>{args[0]}</code>", "HTML")
                continue
            direction = args[1].lower() if len(args) > 1 else "in"
            if direction not in ("in", "out", "both"):
                direction = "in"

            if port < 1 or port > 65535:
                send_telegram("⚠️ Port must be 1–65535.", "HTML")
                continue
            if port in _NEVER_BLOCK:
                send_telegram(
                    f"⛔ Port {port} is in the protected list (SSH/DNS/Dashboard/Ollama).\n"
                    "If you really want to block it, do it manually.",
                    "HTML",
                )
                continue

            token = _secrets.token_hex(4)
            _pending_approvals[token] = {
                "action": "block_port", "port": port,
                "direction": direction, "expires": now + 600,
            }
            _send_block_approval_request(port, direction, token)
            log.info(f"Block approval requested for port {port} ({direction}), token={token}")

        # /approve <token>
        elif cmd == "/approve":
            if not args:
                send_telegram("Usage: <code>/approve &lt;token&gt;</code>", "HTML")
                continue
            token = args[0]
            if token not in _pending_approvals:
                send_telegram("⚠️ Unknown or expired token.", "HTML")
                continue
            ap = _pending_approvals.pop(token)
            port, direction = ap["port"], ap["direction"]
            ok, result_msg = _apply_firewall_block(port, direction)
            if ok:
                send_telegram(
                    f"✅ <b>Done, Batman.</b> Port <code>{port}</code> is blocked ({direction}).\n"
                    f"<i>{result_msg}</i>",
                    "HTML",
                )
                if _activity:
                    _activity.emit("sentinel", f"Robin blocked port {port} ({direction}) on Batman's orders")
            else:
                send_telegram(f"❌ <b>Block failed:</b> {result_msg}", "HTML")

        # /deny <token>
        elif cmd == "/deny":
            if not args:
                continue
            token = args[0]
            if token in _pending_approvals:
                ap = _pending_approvals.pop(token)
                send_telegram(
                    f"🚫 Cancelled — port <code>{ap['port']}</code> block request denied.",
                    "HTML",
                )
            else:
                send_telegram("⚠️ Unknown or expired token.", "HTML")

        # /unblock <port> [in|out|both]
        elif cmd == "/unblock":
            if not args:
                send_telegram("Usage: <code>/unblock &lt;port&gt; [in|out|both]</code>", "HTML")
                continue
            try:
                port = int(args[0])
            except ValueError:
                send_telegram(f"⚠️ Invalid port: <code>{args[0]}</code>", "HTML")
                continue
            direction = args[1].lower() if len(args) > 1 else "in"
            if direction not in ("in", "out", "both"):
                direction = "in"
            try:
                cmds_u = []
                if direction in ("in", "both"):
                    cmds_u.append(["sudo", "ufw", "delete", "deny", "in", str(port)])
                if direction in ("out", "both"):
                    cmds_u.append(["sudo", "ufw", "delete", "deny", "out", str(port)])
                for uc in cmds_u:
                    subprocess.run(uc, capture_output=True, text=True, timeout=15)
                send_telegram(
                    f"✅ Port <code>{port}</code> unblocked ({direction}).", "HTML"
                )
                log.info(f"Port {port} unblocked ({direction})")
            except Exception as e:
                send_telegram(f"❌ Unblock failed: {e}", "HTML")

        # /status — quick system snapshot
        elif cmd == "/status":
            try:
                cpu = psutil.cpu_percent(interval=1)
                mem = psutil.virtual_memory()
                conns = psutil.net_connections(kind="inet")
                established = len([c for c in conns if c.status == "ESTABLISHED"])
                listening = len([c for c in conns if c.status == "LISTEN"])
                msg_s = (
                    f"<b>🦇 BATCAVE STATUS</b>\n"
                    f"CPU: <code>{cpu:.0f}%</code>  MEM: <code>{mem.percent:.0f}%</code>\n"
                    f"Connections: <code>{established}</code> active · <code>{listening}</code> listening\n"
                    f"Pending approvals: <code>{len(_pending_approvals)}</code>"
                )
                send_telegram(msg_s, "HTML")
            except Exception as e:
                send_telegram(f"❌ Status error: {e}", "HTML")

        # /scan — trigger immediate SCC scan
        elif cmd == "/scan":
            send_telegram("🔍 On it, Batman — running SCC scan now...", "HTML")
            try:
                scc_results = run_scc_scan()
                psutil_alerts = []
                msg_sc = format_scc_telegram(scc_results, psutil_alerts)
                send_telegram(msg_sc, "HTML")
            except Exception as e:
                send_telegram(f"❌ Scan failed: {e}", "HTML")

        # /help
        elif cmd in ("/help", "/robin"):
            send_telegram(
                "<b>🦜 Robin Commands</b>\n\n"
                "<code>/block &lt;port&gt; [in|out|both]</code> — request port block\n"
                "<code>/unblock &lt;port&gt; [in|out|both]</code> — remove block\n"
                "<code>/approve &lt;token&gt;</code> — confirm a block request\n"
                "<code>/deny &lt;token&gt;</code> — cancel a block request\n"
                "<code>/scan</code> — run immediate security scan\n"
                "<code>/status</code> — quick system snapshot\n"
                "<code>/help</code> — this menu",
                "HTML",
            )


# ── Telegram Alerts ───────────────────────────────────────────────

def send_telegram(message: str, parse_mode: str = "HTML"):
    """Send alert via Telegram bot."""
    if not TELEGRAM_TOKEN or not TELEGRAM_CHAT_ID:
        log.warning("Telegram not configured — skipping alert")
        return False
    try:
        import requests
        url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
        r = requests.post(url, json={
            "chat_id": TELEGRAM_CHAT_ID,
            "text": message,
            "parse_mode": parse_mode,
        }, timeout=10)
        if r.status_code == 200:
            log.info("Telegram alert sent")
            return True
        else:
            log.warning(f"Telegram API error: {r.status_code}")
            return False
    except Exception as e:
        log.warning(f"Telegram send failed: {e}")
        return False


# ── Security Checks ──────────────────────────────────────────────

def check_listening_ports(state: dict) -> list:
    """Detect new unexpected listening ports."""
    alerts = []
    try:
        current_ports = set()
        for conn in psutil.net_connections(kind="inet"):
            if conn.status == "LISTEN" and conn.laddr:
                current_ports.add(conn.laddr.port)

        known = set(state.get("known_ports", []))
        new_ports = current_ports - known - TRUSTED_PORTS

        if new_ports:
            alerts.append(f"New listening ports detected: {sorted(new_ports)}")

        state["known_ports"] = sorted(current_ports)
    except Exception as e:
        log.warning(f"Port check failed: {e}")
    return alerts


def check_ssh_failures() -> list:
    """Check for recent SSH brute-force attempts."""
    alerts = []
    try:
        auth_log = Path("/var/log/auth.log")
        if not auth_log.exists():
            return alerts
        # Read last 500 lines
        lines = auth_log.read_text(errors="replace").splitlines()[-500:]
        recent_fails = 0
        cutoff = datetime.now() - timedelta(minutes=10)
        for line in lines:
            if "Failed password" in line or "authentication failure" in line:
                recent_fails += 1
        if recent_fails > 10:
            alerts.append(f"SSH brute-force: {recent_fails} failed login attempts in recent logs")
    except PermissionError:
        pass  # Normal on non-root
    except Exception as e:
        log.warning(f"SSH check failed: {e}")
    return alerts


def check_suspicious_processes() -> list:
    """Flag processes with abnormally high resource usage or unknown binaries."""
    alerts = []
    try:
        for proc in psutil.process_iter(["pid", "name", "cpu_percent", "memory_percent", "exe"]):
            try:
                info = proc.info
                name = info["name"] or ""
                cpu = info.get("cpu_percent", 0) or 0
                mem = info.get("memory_percent", 0) or 0

                # High resource — but only alert if not a known process
                if cpu > 80 and name.lower() not in TRUSTED_PROCS:
                    alerts.append(f"High CPU process: {name} (PID {info['pid']}) at {cpu:.0f}%")
                if mem > 15 and name.lower() not in TRUSTED_PROCS:
                    alerts.append(f"High memory process: {name} (PID {info['pid']}) at {mem:.1f}%")

            except (psutil.NoSuchProcess, psutil.AccessDenied):
                pass
    except Exception as e:
        log.warning(f"Process check failed: {e}")
    return alerts[:5]  # Cap at 5 alerts per cycle


def check_connections(state: dict) -> list:
    """Detect sudden spike in outbound connections."""
    alerts = []
    try:
        conns = psutil.net_connections(kind="inet")
        established = [c for c in conns if c.status == "ESTABLISHED"]
        current = len(established)
        previous = state.get("known_connections", current)

        # Spike detection: >50% increase or >30 new connections
        if previous > 10 and current > previous * 1.5:
            alerts.append(f"Connection spike: {previous} -> {current} established connections")
        elif current - previous > 30:
            alerts.append(f"Connection surge: +{current - previous} new connections ({current} total)")

        state["known_connections"] = current
    except Exception as e:
        log.warning(f"Connection check failed: {e}")
    return alerts


def check_vpn(state: dict) -> list:
    """Alert when VPN drops."""
    alerts = []
    try:
        vpn_up = False
        for iface in psutil.net_if_addrs().keys():
            if any(x in iface.lower() for x in ["tun", "tap", "wg", "nordlynx", "proton", "mullvad"]):
                stats = psutil.net_if_stats().get(iface)
                if stats and stats.isup:
                    vpn_up = True
                    break

        was_up = state.get("vpn_was_up", False)
        if was_up and not vpn_up:
            alerts.append("VPN CONNECTION DROPPED — network traffic may be unprotected")
        state["vpn_was_up"] = vpn_up
    except Exception as e:
        log.warning(f"VPN check failed: {e}")
    return alerts


def check_resources() -> list:
    """Check disk, memory, and CPU pressure."""
    alerts = []
    try:
        cpu = psutil.cpu_percent(interval=1)
        mem = psutil.virtual_memory()
        disk = psutil.disk_usage("/")

        if cpu > CPU_ALERT_PCT:
            alerts.append(f"CPU critically high: {cpu:.0f}%")
        if mem.percent > MEM_ALERT_PCT:
            alerts.append(f"Memory critically high: {mem.percent:.0f}% ({mem.used/1e9:.1f}/{mem.total/1e9:.1f} GB)")
        if disk.percent > DISK_ALERT_PCT:
            alerts.append(f"Disk critically full: {disk.percent:.0f}%")
    except Exception as e:
        log.warning(f"Resource check failed: {e}")
    return alerts


def check_critical_files(state: dict) -> list:
    """Monitor critical config files for unexpected changes."""
    alerts = []
    critical_paths = [
        "/etc/passwd", "/etc/shadow", "/etc/sudoers",
        "/etc/ssh/sshd_config",
    ]
    stored_hashes = state.get("critical_hashes", {})

    for path in critical_paths:
        p = Path(path)
        if not p.exists():
            continue
        try:
            current_hash = hashlib.md5(p.read_bytes()).hexdigest()
            if path in stored_hashes and stored_hashes[path] != current_hash:
                alerts.append(f"Critical file modified: {path}")
            stored_hashes[path] = current_hash
        except PermissionError:
            pass
        except Exception:
            pass

    state["critical_hashes"] = stored_hashes
    return alerts


# ── Service Watchdog ──────────────────────────────────────────────

# Services to monitor and auto-restart
WATCHED_SERVICES = {
    "dashboard": {
        "match": "dashboard_hub.py",
        "restart_cmd": [sys.executable, str(SCRIPT_DIR / "dashboard_hub.py"), "--no-browser"],
        "cwd": str(SCRIPT_DIR),
    },
    "telegram_bot": {
        "match": "telegram_bot.py",
        "restart_cmd": None,  # Don't auto-restart — user closes to free VRAM for gaming
        "cwd": str(SCRIPT_DIR),
    },
    "crypto_bot": {
        "match": "crypto_bot.py",
        "restart_cmd": None,  # Don't auto-restart crypto bot — just alert
        "cwd": str(Path.home() / "cryptobot"),
    },
}

def _find_process(match_str: str) -> Optional[int]:
    """Find a running process by command-line match. Returns PID or None."""
    for proc in psutil.process_iter(["pid", "cmdline"]):
        try:
            cmdline = " ".join(proc.info.get("cmdline") or [])
            if match_str in cmdline:
                return proc.info["pid"]
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            pass
    return None


def check_services(state: dict) -> list:
    """Check watched services and auto-restart if down."""
    alerts = []
    for svc_name, svc in WATCHED_SERVICES.items():
        pid = _find_process(svc["match"])
        was_running = state.get(f"svc_{svc_name}_up", False)

        if pid:
            state[f"svc_{svc_name}_up"] = True
        else:
            state[f"svc_{svc_name}_up"] = False
            if was_running:
                alerts.append(f"Service DOWN: {svc_name} — was running, now stopped")
            # Auto-restart if configured
            if svc.get("restart_cmd"):
                try:
                    log.info(f"Robin's bringing {svc_name} back online...")
                    log_dir = Path(svc["cwd"]) / "Logs"
                    log_dir.mkdir(parents=True, exist_ok=True)
                    log_out = open(log_dir / f"{svc_name}_sentinel.log", "a")
                    subprocess.Popen(
                        svc["restart_cmd"],
                        cwd=svc["cwd"],
                        stdout=log_out, stderr=log_out,
                    )
                    alerts.append(f"Robin restarted {svc_name} — back in action")
                    if _activity:
                        _activity.emit("system", f"Robin revived {svc_name}")
                except Exception as e:
                    alerts.append(f"Failed to restart {svc_name}: {e}")
    return alerts


# ── AI Analysis (periodic, resource-light) ────────────────────────

def ai_analyze_threats(alerts: list, system_summary: str) -> Optional[str]:
    """Ask Robin (dolphin-mistral) to assess threats with personality and memory."""
    try:
        import requests

        # Load recent memory for context
        memory = load_memory(last_n=8)
        memory_ctx = format_memory_context(memory)

        prompt = f"""{ROBIN_SYSTEM_PROMPT}

=== RECENT PATROL LOG (your memory of past events) ===
{memory_ctx}

=== CURRENT BATCAVE STATUS ===
{system_summary}

=== ALERTS THIS CYCLE ===
{json.dumps(alerts) if alerts else 'No alerts — Gotham is quiet tonight.'}

Give Batman your assessment. Remember past events if relevant. Keep it tight."""

        r = requests.post(f"{OLLAMA_URL}/api/generate", json={
            "model": SENTINEL_MODEL,
            "prompt": prompt,
            "stream": False,
            "options": {"num_predict": 200, "temperature": 0.5},
        }, timeout=60)

        if r.status_code == 200:
            response = r.json().get("response", "").strip()
            # Save this exchange to memory
            save_memory({"role": "system", "message": f"Alerts: {alerts}" if alerts else "All clear patrol"})
            save_memory({"role": "robin", "message": response})
            return response
    except Exception as e:
        log.warning(f"Robin's AI analysis failed: {e}")
    return None


# ── SecurityCommandCenter Tool Scans ─────────────────────────────

def run_scc_scan() -> dict:
    """
    Run SecurityCommandCenter tools: quick_overview + network_hunt + investigate_ports.
    Returns a unified results dict.
    """
    if not SCC_AVAILABLE or _sec is None:
        return {"error": "SecurityCommandCenter not available"}

    results = {}
    log.info("Robin running SecurityCommandCenter full scan...")

    try:
        results["quick"] = _sec.quick_overview()
        log.info("  quick_overview done")
    except Exception as e:
        results["quick"] = {"error": str(e)}

    try:
        results["ports"] = _sec.investigate_ports(no_geo=False)
        log.info("  investigate_ports done")
    except Exception as e:
        results["ports"] = {"error": str(e)}

    try:
        results["hunt"] = _sec.network_hunt()
        log.info("  network_hunt done")
    except Exception as e:
        results["hunt"] = {"error": str(e)}

    if _activity:
        _activity.emit("sentinel", "Robin: SCC full scan complete", {"modules": list(results.keys())})

    return results


def _sev_emoji(severity: str) -> str:
    return {"critical": "🔴", "high": "🟠", "medium": "🟡", "low": "🔵"}.get(
        severity.lower(), "⚪"
    )


def format_scc_telegram(results: dict, psutil_alerts: list) -> str:
    """Format SCC scan results into a rich Telegram HTML message."""
    lines = [f"<b>🛡 ROBIN SECURITY SCAN REPORT</b> — {datetime.now():%H:%M}\n"]

    # ── Quick overview / connections ──────────────────────────────
    q = results.get("quick", {})
    if q and not q.get("error"):
        # quick_overview returns network stats directly under "network" key
        qnet = q.get("network", q.get("summary", q.get("network_summary", q.get("overview", {}))))
        total = qnet.get("total_connections", qnet.get("total", qnet.get("connections", "?")))
        estab = qnet.get("established", "?")
        listen = qnet.get("listening_ports", qnet.get("listening", "?"))
        remote = qnet.get("unique_remote_ips", "?")
        qsum = qnet  # alias so risk/warnings lines below still work
        risk = q.get("risk_level", "UNKNOWN")
        risk_emoji = {"LOW": "🟢", "MEDIUM": "🟡", "HIGH": "🟠", "CRITICAL": "🔴"}.get(
            str(risk).upper(), "⚪"
        )
        lines.append(
            f"📡 <b>CONNECTIONS</b>\n"
            f"Total: <code>{total}</code> | Active: <code>{estab}</code> | Listening: <code>{listen}</code>\n"
            f"External IPs: <code>{remote}</code>  Risk: {risk_emoji} <b>{risk}</b>"
        )
        warnings = q.get("warnings", q.get("alerts", []))
        if warnings:
            lines.append("\n⚠️ <b>Warnings:</b>")
            for w in warnings[:5]:
                lines.append(f"  • {w}")

    # ── Network hunt ──────────────────────────────────────────────
    h = results.get("hunt", {})
    if h and not h.get("error"):
        discovery = h.get("discovery", {})
        hosts_raw = discovery.get("hosts_found", [])
        host_ips = [
            hh.get("ip", hh) if isinstance(hh, dict) else str(hh)
            for hh in hosts_raw
        ]

        os_fps = {
            fp.get("host"): fp.get("os_guess", "?")
            for fp in h.get("os_fingerprints", {}).get("fingerprints", [])
            if isinstance(fp, dict)
        }

        services_raw = h.get("services", {}).get("services", [])
        # Group services by host
        svc_by_host: dict = {}
        for svc in services_raw:
            if isinstance(svc, dict) and svc.get("status") == "open":
                ip = svc.get("host", "?")
                svc_by_host.setdefault(ip, []).append(f"{svc['service']}:{svc['port']}")

        lines.append(f"\n🔍 <b>NETWORK HUNT</b> — {len(host_ips)} host(s) found")
        for ip in host_ips[:8]:
            os_g = os_fps.get(ip, "?")
            svcs = ", ".join(svc_by_host.get(ip, []))
            lines.append(f"  • <code>{ip}</code> [{os_g}]{(' — ' + svcs) if svcs else ''}")
        if len(host_ips) > 8:
            lines.append(f"  … +{len(host_ips) - 8} more")

        # Security issues
        sec_issues = h.get("security_issues", {}).get("security_issues", [])
        if sec_issues:
            lines.append(f"\n⚠️ <b>SECURITY ISSUES</b> ({len(sec_issues)})")
            for iss in sec_issues[:6]:
                if isinstance(iss, dict):
                    sev = iss.get("severity", "?")
                    lines.append(
                        f"  {_sev_emoji(sev)} <code>{iss.get('host','?')}:{iss.get('port','?')}</code>"
                        f" — {iss.get('issue','?')}"
                    )
            if len(sec_issues) > 6:
                lines.append(f"  … +{len(sec_issues) - 6} more issues")

        recs = h.get("security_issues", {}).get("recommendations", [])
        if recs:
            lines.append(f"\n💡 <b>Recommendations:</b>")
            for r in recs[:3]:
                lines.append(f"  • {r}")

    # ── Port investigator summary ─────────────────────────────────
    p = results.get("ports", {})
    if p and not p.get("error"):
        psum = p.get("summary", {})
        by_country = p.get("by_country", {})
        top_countries = sorted(by_country.items(), key=lambda x: -x[1])[:5]
        if top_countries:
            lines.append(
                "\n🌍 <b>TOP COUNTRIES</b>\n"
                + "  " + " | ".join(f"{c}: {n}" for c, n in top_countries)
            )

        suspicious = [
            c for c in (p.get("connections") or [])
            if c.get("geo", {}).get("country") not in (None, "", "United States", "US")
        ]
        if suspicious:
            lines.append(f"\n🕵️ <b>FOREIGN CONNECTIONS</b> ({len(suspicious)})")
            for c in suspicious[:5]:
                geo = c.get("geo", {})
                proc = c.get("process_name", "?")
                lines.append(
                    f"  • :{c.get('local_port','?')} → "
                    f"<code>{c.get('remote_ip','?')}</code>"
                    f" [{geo.get('country','?')}] ({proc})"
                )

    # ── Psutil raw alerts (existing checks) ───────────────────────
    if psutil_alerts:
        lines.append(f"\n🚨 <b>SYSTEM ALERTS</b> ({len(psutil_alerts)})")
        for a in psutil_alerts[:6]:
            lines.append(f"  • {a}")

    lines.append(f"\n<i>Next scan in {SCC_SCAN_INTERVAL//60} min</i>")
    return "\n".join(lines)


def format_scc_ai_prompt(results: dict, psutil_alerts: list) -> str:
    """Build a compact AI prompt from SCC results for Robin's assessment."""
    q = results.get("quick", {})
    h = results.get("hunt", {})
    p = results.get("ports", {})

    qnet = q.get("network", q.get("summary", {})) if q else {}
    hosts = h.get("discovery", {}).get("hosts_found", []) if h else []
    issues = h.get("security_issues", {}).get("security_issues", []) if h else []
    by_country = p.get("by_country", {}) if p else {}

    return (
        f"Connections: {qnet.get('total_connections', qnet.get('total','?'))} total, "
        f"{qnet.get('established','?')} active, "
        f"{qnet.get('unique_remote_ips','?')} external IPs. "
        f"Risk: {q.get('risk_level','?') if q else '?'}. "
        f"Network: {len(hosts)} hosts found. "
        f"Security issues: {len(issues)}. "
        f"Countries with connections: {list(by_country.keys())[:5]}. "
        f"Psutil alerts: {psutil_alerts if psutil_alerts else 'none'}."
    )


# ── Main Loop ────────────────────────────────────────────────────

def run_cycle(state: dict) -> list:
    """Run all security checks. Returns list of alert strings."""
    all_alerts = []
    all_alerts.extend(check_listening_ports(state))
    all_alerts.extend(check_ssh_failures())
    all_alerts.extend(check_suspicious_processes())
    all_alerts.extend(check_connections(state))
    all_alerts.extend(check_vpn(state))
    all_alerts.extend(check_resources())
    all_alerts.extend(check_critical_files(state))
    all_alerts.extend(check_services(state))

    # Emit to activity stream
    if _activity:
        if all_alerts:
            _activity.emit("system", f"Robin: {len(all_alerts)} alert(s) — trouble in Gotham", {"alerts": all_alerts[:5]})
        else:
            _activity.emit("system", "Robin: all clear, Batman")
    return all_alerts


def format_telegram_alert(alerts: list, ai_assessment: Optional[str] = None) -> str:
    """Format alerts into a Telegram message with Robin's personality."""
    header = f"<b>ROBIN PATROL REPORT</b> — {datetime.now():%H:%M}"
    body = "\n".join(f"  {a}" for a in alerts)
    msg = f"{header}\n\n{body}"
    if ai_assessment:
        msg += f"\n\n<b>Robin says:</b>\n{ai_assessment}"
    return msg


def main():
    log.info("Robin reporting for duty, Batman.")
    log.info(f"  Brain: {SENTINEL_MODEL}")
    log.info(f"  Patrol interval: {CHECK_INTERVAL//60}m (quick checks)")
    log.info(f"  Deep scan interval: {SCC_SCAN_INTERVAL//60}m (SCC full scan)")
    log.info(f"  AI analysis interval: {AI_ANALYSIS_INTERVAL//60}m")
    log.info(f"  Telegram: state-change only (dedup enabled)")
    log.info(f"  Batphone (Telegram): {'online' if TELEGRAM_TOKEN else 'NOT configured'}")

    # Load memory count
    mem_count = len(load_memory(last_n=MAX_MEMORY_ENTRIES))
    log.info(f"  Memory bank: {mem_count} entries loaded")

    state = load_state()

    log.info(f"  SecurityCommandCenter: {'online' if SCC_AVAILABLE else 'NOT available'}")

    # Initial baseline (don't alert on first run)
    log.info("Scanning the Batcave perimeter...")
    run_cycle(state)
    save_state(state)
    log.info("Baseline locked in. Eyes open, Batman.")

    save_memory({"role": "robin", "message": "Robin online. Patrol started."})
    startup_msg = (
        "<b>🦇 ROBIN ONLINE</b>\n"
        f"Hey Batman, I'm on patrol. The Batcave is locked down.\n"
        f"SecurityCommandCenter: {'✓ online' if SCC_AVAILABLE else '✗ not loaded'}\n"
        f"Scan interval: every {CHECK_INTERVAL//60}m | Deep scan: every {SCC_SCAN_INTERVAL//60}m"
    )
    send_telegram(startup_msg, "HTML")

    # Run initial SCC scan immediately at startup
    if SCC_AVAILABLE:
        try:
            log.info("Running initial SCC scan...")
            scc_results = run_scc_scan()
            psutil_alerts = run_cycle(state)
            msg = format_scc_telegram(scc_results, psutil_alerts)
            # Add Robin's quick take using AI if available
            ai_summary = format_scc_ai_prompt(scc_results, psutil_alerts)
            ai_text = ai_analyze_threats(psutil_alerts, ai_summary)
            if ai_text:
                msg += f"\n\n<b>🦜 Robin says:</b>\n<i>{ai_text}</i>"
            send_telegram(msg, "HTML")
            state["last_scc_scan"] = time.time()
            state["last_ai_check"] = time.time()
            save_state(state)
        except Exception as e:
            log.error(f"Initial SCC scan failed: {e}")

    # Telegram polling loop runs in the foreground alongside sleep
    # We break CHECK_INTERVAL into 15s slices to stay responsive to commands
    POLL_SLICE = 15  # seconds between Telegram polls

    while True:
        try:
            # Sleep in slices — poll Telegram commands each slice
            slept = 0
            while slept < CHECK_INTERVAL:
                time.sleep(POLL_SLICE)
                slept += POLL_SLICE
                updates = _telegram_get_updates()
                if updates:
                    _handle_telegram_commands(updates)

            alerts = run_cycle(state)
            now = time.time()
            notify = should_telegram(alerts)

            if alerts:
                state["alert_count"] = state.get("alert_count", 0) + len(alerts)
                log.warning(f"Trouble spotted — {len(alerts)} alert(s): {alerts}")
                save_memory({"role": "system", "message": f"{len(alerts)} alerts: {', '.join(alerts[:3])}"})
            else:
                log.info("Gotham's quiet. All clear, Batman.")
                quiet_count = state.get("quiet_streak", 0) + 1
                state["quiet_streak"] = quiet_count
                if quiet_count % 10 == 0:
                    save_memory({"role": "robin", "message": f"All quiet for {quiet_count} consecutive patrols."})

            # ── SCC deep scan on interval ─────────────────────────
            run_scc = SCC_AVAILABLE and (now - state.get("last_scc_scan", 0) > SCC_SCAN_INTERVAL)
            if run_scc:
                try:
                    log.info("Running scheduled SCC deep scan...")
                    scc_results = run_scc_scan()
                    msg = format_scc_telegram(scc_results, alerts)

                    # AI assessment of the full scan
                    ai_text = None
                    if now - state.get("last_ai_check", 0) > AI_ANALYSIS_INTERVAL:
                        ai_summary = format_scc_ai_prompt(scc_results, alerts)
                        ai_text = ai_analyze_threats(alerts, ai_summary)
                        state["last_ai_check"] = now

                    if ai_text:
                        msg += f"\n\n<b>🦜 Robin says:</b>\n<i>{ai_text}</i>"

                    # SCC scans always Telegram (they're infrequent at 60m interval)
                    send_telegram(msg, "HTML")
                    state["last_scc_scan"] = now
                    save_memory({
                        "role": "robin",
                        "message": f"SCC scan complete. Hosts found: "
                                   f"{len(scc_results.get('hunt', {}).get('discovery', {}).get('hosts_found', []))}. "
                                   f"Alerts: {len(alerts)}."
                    })
                except Exception as e:
                    log.error(f"SCC scan failed: {e}")

            elif alerts and not run_scc:
                # Alerts present but no SCC scan this cycle
                if notify:
                    # State changed (new alerts or different alert set) → Telegram
                    ai_text = None
                    if now - state.get("last_ai_check", 0) > AI_ANALYSIS_INTERVAL:
                        system_summary = (
                            f"CPU: {psutil.cpu_percent()}%, "
                            f"MEM: {psutil.virtual_memory().percent}%, "
                            f"Disk: {psutil.disk_usage('/').percent}%, "
                            f"Connections: {len(psutil.net_connections(kind='inet'))}"
                        )
                        ai_text = ai_analyze_threats(alerts, system_summary)
                        state["last_ai_check"] = now
                    msg = format_telegram_alert(alerts, ai_text)
                    send_telegram(msg, "HTML")
                else:
                    # Same alerts as last cycle — log only, no Telegram
                    log.info(f"Same alerts as previous cycle — suppressing Telegram ({len(alerts)} alert(s))")

            elif not alerts and not run_scc:
                if notify:
                    # Transition: alert → clear — send one "all clear" to Telegram
                    send_telegram(
                        f"<b>✅ ROBIN ALL CLEAR</b> — {datetime.now():%H:%M}\n"
                        "Gotham's quiet again, Batman. Standing watch.",
                        "HTML",
                    )
                # Periodic AI check-in (log only, never Telegram for quiet cycles)
                if now - state.get("last_ai_check", 0) > AI_ANALYSIS_INTERVAL:
                    system_summary = (
                        f"CPU: {psutil.cpu_percent()}%, "
                        f"MEM: {psutil.virtual_memory().percent}%, "
                        f"Disk: {psutil.disk_usage('/').percent}%, "
                        f"Connections: {len(psutil.net_connections(kind='inet'))}"
                    )
                    ai_text = ai_analyze_threats([], system_summary)
                    state["last_ai_check"] = now
                    if ai_text:
                        log.info(f"Robin: {ai_text}")

            if alerts:
                state["quiet_streak"] = 0

            save_state(state)

        except KeyboardInterrupt:
            log.info("Robin signing off. Stay safe, Batman.")
            save_memory({"role": "robin", "message": "Patrol ended. Robin signing off."})
            send_telegram("<b>ROBIN OFFLINE</b>\nPatrol ended. Stay sharp out there, Batman.", "HTML")
            break
        except Exception as e:
            log.error(f"Robin hit a snag: {e}")
            time.sleep(30)


def install_autostart():
    """Install XDG autostart entry so sentinel runs on login."""
    autostart_dir = Path.home() / ".config" / "autostart"
    autostart_dir.mkdir(parents=True, exist_ok=True)
    desktop = autostart_dir / "larry-sentinel.desktop"
    desktop.write_text(f"""[Desktop Entry]
Type=Application
Name=Larry Security Sentinel
Comment=AI-Powered Security Monitor
Exec=bash -c "cd {SCRIPT_DIR} && {sys.executable} {Path(__file__).resolve()} >> {SCRIPT_DIR}/logs/sentinel.log 2>&1"
Terminal=false
Hidden=false
X-GNOME-Autostart-enabled=true
""")
    print(f"Autostart installed: {desktop}")


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Security Sentinel")
    parser.add_argument("--install-autostart", action="store_true", help="Install XDG autostart entry")
    args = parser.parse_args()
    if args.install_autostart:
        install_autostart()
    else:
        main()
