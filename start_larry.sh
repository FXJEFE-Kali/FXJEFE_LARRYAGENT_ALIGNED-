#!/usr/bin/env bash
# start_larry.sh — single-shot launcher for the Larry G-Force stack.
#
# Behavior:
#   1. Spawns telegram_bot.py in the background (only if not already running),
#      logging to logs/telegram_bot.log and detached from this terminal.
#   2. Then exec's agent_v2.py in the foreground so the REPL takes over the
#      current terminal. The bot keeps running after you /quit the agent.
#
# Stop the bot manually with:   pkill -f telegram_bot.py
# Or, if you're using systemd:  systemctl --user stop larry-telegram

set -euo pipefail

REPO="/home/linuxlarry/Documents/Agent-Larry"
# Two separate venvs by design:
#   - .venv     → agent_v2.py (has apscheduler installed for the Robin loop)
#   - venv312   → telegram_bot.py (matches the systemd unit / py3 wrapper)
AGENT_PY="${REPO}/.venv/bin/python"
BOT_PY="${HOME}/Documents/venv312/bin/python"
BOT_WRAPPER="${HOME}/Documents/py3"
LOG_DIR="${REPO}/logs"
BOT_LOG="${LOG_DIR}/telegram_bot.log"
BOT_PIDFILE="${LOG_DIR}/telegram_bot.pid"

mkdir -p "${LOG_DIR}"

# --- Telegram bot: only start if not already running ----------------------
# Skip if either the systemd unit OR another launcher invocation has it up.
if systemctl --user is-active --quiet larry-telegram 2>/dev/null; then
    echo "[start_larry] telegram_bot.py is managed by systemd (larry-telegram) — skipping."
elif pgrep -f "${REPO}/telegram_bot.py" >/dev/null 2>&1; then
    echo "[start_larry] telegram_bot.py already running — skipping."
else
    echo "[start_larry] starting telegram_bot.py in background..."
    # Prefer the venv312 interpreter directly; fall back to the py3 wrapper.
    if [[ -x "${BOT_PY}" ]]; then
        nohup setsid "${BOT_PY}" "${REPO}/telegram_bot.py" \
            >>"${BOT_LOG}" 2>&1 </dev/null &
    elif [[ -x "${BOT_WRAPPER}" ]]; then
        # Wrapper expects to be invoked from ~/Documents with a relative path.
        ( cd "${HOME}/Documents" && \
          nohup setsid "${BOT_WRAPPER}" "Agent-Larry/telegram_bot.py" \
              >>"${BOT_LOG}" 2>&1 </dev/null & )
    else
        echo "[start_larry] ERROR: neither ${BOT_PY} nor ${BOT_WRAPPER} is executable." >&2
        echo "[start_larry] continuing anyway — agent_v2.py will start without the bot." >&2
    fi
    sleep 0.5
    NEW_PID=$(pgrep -f "${REPO}/telegram_bot.py" | head -1 || true)
    if [[ -n "${NEW_PID}" ]]; then
        echo "${NEW_PID}" >"${BOT_PIDFILE}"
        echo "[start_larry] telegram_bot.py pid=${NEW_PID} log=${BOT_LOG}"
    fi
fi

# --- Agent REPL in the foreground -----------------------------------------
echo "[start_larry] launching agent_v2.py in foreground..."
cd "${REPO}"
exec "${AGENT_PY}" "${REPO}/agent_v2.py"
