"""
agent_tools.py — Tool-calling loop for Robin / Larry G-Force.

Uses Ollama's native /api/chat tools interface.
Includes secure path allow-list, APScheduler with rehydration, separate log
files for background processes vs scheduled health checks, Telegram failure
alerts (with hashlib-based dedup), and optional remote-host execution against
the Windows Meshnet runner.
"""
import atexit
import hashlib
import json
import os
import subprocess
import time
import uuid
from pathlib import Path
from typing import Any, Callable

import requests
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.interval import IntervalTrigger

# Portable path resolution — anchored to this file, honors $LARRY_HOME.
try:
    from larry_paths import BASE_DIR as _LARRY_BASE
except ImportError:
    _LARRY_BASE = Path(__file__).parent.resolve()

# ---------- configuration ----------
OLLAMA_URL = os.environ.get("OLLAMA_URL", "http://localhost:11434/api/chat")
DEFAULT_MODEL = os.environ.get("LARRY_DEFAULT_MODEL", "qwen2.5:7b-instruct")

STATE_FILE = Path.home() / ".robin" / "jobs.json"
STATE_FILE.parent.mkdir(exist_ok=True)
if not STATE_FILE.exists():
    STATE_FILE.write_text("{}")

# ---------- security: local allow-list ----------
# Portable: always include the project root derived from this file's location.
# Extend via $LARRY_ALLOWED_ROOTS (colon-separated on Linux, semicolon on Windows).
_extra_roots_env = os.environ.get("LARRY_ALLOWED_ROOTS", "")
_sep = ";" if os.name == "nt" else ":"
ALLOWED_ROOTS = [_LARRY_BASE]
for _r in _extra_roots_env.split(_sep):
    _r = _r.strip()
    if _r:
        try:
            ALLOWED_ROOTS.append(Path(_r).resolve())
        except Exception:
            pass


def _path_allowed(p: str) -> bool:
    try:
        target = Path(p).resolve()
        return any(target.is_relative_to(root) for root in ALLOWED_ROOTS)
    except Exception:
        return False


# ---------- remote runner config ----------
REMOTE_HOSTS = {
    "win11": {
        "url": "http://100.88.131.215:7341",  # Win11Pro Meshnet IP
        "token_file": Path.home() / ".robin" / "remote_token",
    },
}


def _remote_call(host: str, method: str, path: str,
                 json_body: dict | None = None) -> dict:
    cfg = REMOTE_HOSTS.get(host)
    if not cfg:
        return {"ok": False, "error": f"unknown host '{host}'"}
    try:
        token = cfg["token_file"].read_text().strip()
    except Exception as e:
        return {"ok": False, "error": f"cannot read remote token: {e}"}
    headers = {"Authorization": f"Bearer {token}"}
    url = cfg["url"] + path
    try:
        if method == "GET":
            r = requests.get(url, headers=headers, timeout=300)
        else:
            r = requests.post(url, headers=headers, json=json_body, timeout=300)
        if r.status_code >= 400:
            return {"ok": False, "error": f"remote {r.status_code}: {r.text[:300]}"}
        return r.json()
    except requests.exceptions.RequestException as e:
        return {"ok": False, "error": f"remote unreachable: {e}"}


# ---------- state helpers ----------
def _load() -> dict:
    return json.loads(STATE_FILE.read_text())


def _save(state: dict) -> None:
    STATE_FILE.write_text(json.dumps(state, indent=2))


# ---------- Telegram dedup shim ----------
# security_sentinel.send_telegram() exists but has no dedup wrapper. Wrap it
# here with an in-memory MD5 fingerprint cache so we don't spam the channel
# when the same check fails on every tick.
_TELEGRAM_DEDUP_CACHE: dict[str, float] = {}
_TELEGRAM_DEDUP_TTL = 600  # seconds — re-alert at most every 10 min per fingerprint


def _send_telegram_dedup(message: str) -> None:
    fp = hashlib.md5(message.encode("utf-8")).hexdigest()
    now = time.time()
    last = _TELEGRAM_DEDUP_CACHE.get(fp)
    if last is not None and (now - last) < _TELEGRAM_DEDUP_TTL:
        return
    _TELEGRAM_DEDUP_CACHE[fp] = now
    # prune
    for k, t in list(_TELEGRAM_DEDUP_CACHE.items()):
        if (now - t) > _TELEGRAM_DEDUP_TTL * 4:
            del _TELEGRAM_DEDUP_CACHE[k]
    try:
        from security_sentinel import send_telegram
        send_telegram(message, parse_mode="HTML")
    except Exception:
        # never let alerting break the scheduler
        pass


# ---------- process liveness ----------
def _pid_alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
        return True
    except OSError:
        return False


# ---------- tool implementations ----------
def run_script(path: str, args: list[str] | None = None,
               cwd: str | None = None, timeout: int = 120,
               host: str | None = None) -> dict:
    if host:
        return _remote_call(host, "POST", "/run_script", {
            "path": path, "args": args or [], "cwd": cwd, "timeout": timeout,
        })
    if not _path_allowed(path):
        return {"ok": False, "error": "Local path is outside the allowed directories"}
    args = args or []
    try:
        proc = subprocess.run(
            ["python3", path, *args],
            cwd=cwd, capture_output=True, text=True, timeout=timeout,
        )
        return {
            "ok": proc.returncode == 0,
            "exit_code": proc.returncode,
            "stdout": proc.stdout[-4000:],
            "stderr": proc.stderr[-2000:],
        }
    except subprocess.TimeoutExpired:
        return {"ok": False, "error": f"timeout after {timeout}s"}
    except Exception as e:
        return {"ok": False, "error": str(e)}


def start_background(path: str, name: str, args: list[str] | None = None,
                     host: str | None = None) -> dict:
    if host:
        return _remote_call(host, "POST", "/start_background", {
            "path": path, "name": name, "args": args or [],
        })
    if not _path_allowed(path):
        return {"ok": False, "error": "Local path is outside the allowed directories"}
    args = args or []
    state = _load()
    existing = state.get(name)
    if isinstance(existing, dict) and "pid" in existing and _pid_alive(existing["pid"]):
        return {"ok": False, "error": f"Job '{name}' is already running (pid {existing['pid']})"}
    try:
        log_path = STATE_FILE.parent / f"{name}.bg.log"
        log_fh = open(log_path, "ab")
        proc = subprocess.Popen(
            ["python3", path, *args],
            stdout=log_fh, stderr=subprocess.STDOUT, start_new_session=True,
        )
        state[name] = {
            "pid": proc.pid,
            "path": path,
            "started": time.time(),
            "log": str(log_path),
        }
        _save(state)
        return {"ok": True, "pid": proc.pid, "log": str(log_path)}
    except Exception as e:
        return {"ok": False, "error": str(e)}


def stop_background(name: str, host: str | None = None) -> dict:
    if host:
        return _remote_call(host, "POST", "/stop_background", {"name": name})
    state = _load()
    if name not in state or not isinstance(state[name], dict) or "pid" not in state[name]:
        return {"ok": False, "error": f"No background job named '{name}'"}
    pid = state[name]["pid"]
    try:
        subprocess.run(["kill", str(pid)], check=False)
        del state[name]
        _save(state)
        return {"ok": True, "killed": pid}
    except Exception as e:
        return {"ok": False, "error": str(e)}


def list_jobs(host: str | None = None) -> dict:
    if host:
        return _remote_call(host, "GET", "/list_jobs")
    state = _load()
    out: dict[str, Any] = {}
    for name, info in state.items():
        if isinstance(info, dict) and "pid" in info:
            entry = dict(info)
            entry["alive"] = _pid_alive(info["pid"])
            out[name] = entry
    return {"ok": True, "jobs": out}


def health_check(target: str, host: str | None = None) -> dict:
    if host:
        return _remote_call(host, "POST", "/health_check", {"target": target})
    try:
        if target.startswith("http"):
            r = requests.get(target, timeout=5)
            return {"ok": r.ok, "status": r.status_code, "body": r.text[:500]}
        return run_script(target, timeout=30)
    except Exception as e:
        return {"ok": False, "error": str(e)}


# ---------- scheduler ----------
_scheduler: BackgroundScheduler | None = None


def _make_job_func(target: str, name: str, host: str | None = None) -> Callable:
    """Build the closure that runs one scheduled health check (local or remote)."""
    def job_func():
        result = health_check(target, host=host)
        log_path = STATE_FILE.parent / f"{name}.health.log"
        timestamp = time.strftime("%Y-%m-%d %H:%M:%S")
        try:
            with open(log_path, "a") as f:
                f.write(f"[{timestamp}] {result}\n")
        except Exception:
            pass
        if not result.get("ok"):
            detail = result.get("error") or result.get("status") or "unknown"
            location = host or "local"
            _send_telegram_dedup(
                f"[{name}] health check failed on {location}: {detail}"
            )
    return job_func


def _add_job_to_scheduler(name: str, target: str, interval_seconds: int,
                          host: str | None = None):
    """Register a job with the live scheduler. Used by schedule_interval and rehydrate."""
    # Direct module-global reference: caller guarantees _scheduler is started.
    trigger = IntervalTrigger(seconds=interval_seconds)
    return _scheduler.add_job(
        _make_job_func(target, name, host),
        trigger=trigger,
        id=name,
        name=name,
        replace_existing=True,
    )


def _rehydrate_scheduler():
    """Re-register scheduled jobs from jobs.json after an agent restart."""
    state = _load()
    for name, info in state.get("scheduled", {}).items():
        try:
            _add_job_to_scheduler(
                name,
                info["target"],
                info["interval_seconds"],
                info.get("host"),
            )
        except Exception as e:
            print(f"  ⚠  failed to rehydrate '{name}': {e}")


def get_scheduler() -> BackgroundScheduler:
    global _scheduler
    if _scheduler is None:
        _scheduler = BackgroundScheduler()
        _scheduler.start()
        atexit.register(lambda: _scheduler.shutdown(wait=False) if _scheduler else None)
        _rehydrate_scheduler()
    return _scheduler


def schedule_interval(target: str, interval_seconds: int, name: str,
                      host: str | None = None) -> dict:
    """Schedule a recurring health check, optionally on a remote host."""
    # Validation: URLs always OK. Local paths must pass local allow-list.
    # Remote paths are validated by the remote server itself.
    if not target.startswith("http") and host is None and not _path_allowed(target):
        return {
            "ok": False,
            "error": "Local target path is outside the allowed directories",
        }
    if host is not None and host not in REMOTE_HOSTS:
        return {
            "ok": False,
            "error": f"Unknown remote host '{host}'. Available hosts: {list(REMOTE_HOSTS.keys())}",
        }
    if interval_seconds < 10:
        return {"ok": False, "error": "Interval must be at least 10 seconds"}

    state = _load()
    if "scheduled" not in state:
        state["scheduled"] = {}
    if name in state["scheduled"]:
        return {"ok": False, "error": f"A scheduled job named '{name}' already exists"}

    try:
        get_scheduler()  # ensure running
        job = _add_job_to_scheduler(name, target, interval_seconds, host)
        state["scheduled"][name] = {
            "target": target,
            "interval_seconds": interval_seconds,
            "host": host,
            "started": time.time(),
            "next_run": str(job.next_run_time),
        }
        _save(state)
        return {
            "ok": True,
            "name": name,
            "interval_seconds": interval_seconds,
            "host": host or "local",
            "next_run": str(job.next_run_time),
            "log": str(STATE_FILE.parent / f"{name}.health.log"),
        }
    except Exception as e:
        return {"ok": False, "error": str(e)}


def list_scheduled_jobs() -> dict:
    state = _load()
    return {"ok": True, "scheduled": state.get("scheduled", {})}


def remove_scheduled_job(name: str) -> dict:
    state = _load()
    if "scheduled" not in state or name not in state["scheduled"]:
        return {"ok": False, "error": f"No scheduled job named '{name}'"}
    try:
        get_scheduler().remove_job(name)
        del state["scheduled"][name]
        _save(state)
        return {"ok": True, "removed": name}
    except Exception as e:
        return {"ok": False, "error": str(e)}


# ---------- tool registry + schemas ----------
TOOLS: dict[str, Callable] = {
    "run_script": run_script,
    "start_background": start_background,
    "stop_background": stop_background,
    "list_jobs": list_jobs,
    "health_check": health_check,
    "schedule_interval": schedule_interval,
    "list_scheduled_jobs": list_scheduled_jobs,
    "remove_scheduled_job": remove_scheduled_job,
}

TOOL_SCHEMAS = [
    {
        "type": "function",
        "function": {
            "name": "run_script",
            "description": (
                "Run a Python (.py) or batch (.bat) script to completion and return "
                "stdout/stderr/exit code. Pass host='win11' to execute on the Windows "
                "laptop via Meshnet instead of locally. Path must be inside the allow-list "
                "of the target host."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "Absolute path on the target host"},
                    "args": {"type": "array", "items": {"type": "string"}},
                    "cwd": {"type": "string"},
                    "timeout": {"type": "integer", "description": "Seconds before kill"},
                    "host": {
                        "type": "string",
                        "description": "Optional remote host name (e.g. 'win11'). Omit for local Ubuntu.",
                    },
                },
                "required": ["path"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "start_background",
            "description": (
                "Launch a script as a detached background process on the target host. "
                "Pass host='win11' for the Windows laptop. Path must be inside the allow-list."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string"},
                    "name": {
                        "type": "string",
                        "description": "Unique job name used to stop/inspect later",
                    },
                    "args": {"type": "array", "items": {"type": "string"}},
                    "host": {"type": "string", "description": "Optional remote host. Omit for local."},
                },
                "required": ["path", "name"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "stop_background",
            "description": "Kill a previously started background job by name on the target host.",
            "parameters": {
                "type": "object",
                "properties": {
                    "name": {"type": "string"},
                    "host": {"type": "string", "description": "Optional remote host. Omit for local."},
                },
                "required": ["name"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "list_jobs",
            "description": (
                "List all tracked background jobs on the target host and whether they are "
                "still alive. Jobs on Ubuntu and Windows are tracked separately."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "host": {"type": "string", "description": "Optional remote host. Omit for local."},
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "health_check",
            "description": (
                "Hit a URL or run a health-check script once on the target host. "
                "Pass host='win11' to run the check from the Windows side."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "target": {"type": "string"},
                    "host": {"type": "string", "description": "Optional remote host. Omit for local."},
                },
                "required": ["target"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "schedule_interval",
            "description": (
                "Schedule a recurring health check (URL or script path) at a fixed interval. "
                "Pass host='win11' to run the check on the Windows laptop. Logs every run to "
                "~/.robin/{name}.health.log and fires a Telegram alert on failure. "
                "Minimum interval is 10 seconds."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "target": {"type": "string", "description": "URL or absolute script path on target host"},
                    "interval_seconds": {"type": "integer", "description": "Seconds between runs (min 10)"},
                    "name": {"type": "string", "description": "Unique job name"},
                    "host": {"type": "string", "description": "Optional remote host (e.g. 'win11'). Omit for local."},
                },
                "required": ["target", "interval_seconds", "name"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "list_scheduled_jobs",
            "description": "List all scheduled recurring health checks with their intervals and next run times.",
            "parameters": {"type": "object", "properties": {}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "remove_scheduled_job",
            "description": "Remove a scheduled recurring job by name.",
            "parameters": {
                "type": "object",
                "properties": {"name": {"type": "string"}},
                "required": ["name"],
            },
        },
    },
]

# ---------- the loop ----------
SYSTEM_PROMPT = """You are Robin, an operations agent on LinuxLarry's Ubuntu homelab.

You have tools. To do anything in the real world you MUST call a tool.
Never describe actions you have not taken. Never invent file paths.
If you are missing a required argument, ask ONE specific question and stop.
When a tool returns, read the result and decide the next step.
When the user's goal is achieved, reply with a single short sentence confirming what ran and the result. No preamble, no phases, no role-play."""

_ACTION_WORDS = ("i'll ", "i will ", "deploying", "executing", "scheduled", "starting the")


def _looks_like_fake_action(text: str) -> bool:
    low = text.lower()
    return any(w in low for w in _ACTION_WORDS)


def chat(user_msg: str, history: list[dict], model: str = DEFAULT_MODEL,
         max_steps: int = 6) -> tuple[str, list[dict]]:
    """
    Run one user turn through the tool-calling loop.
    Returns (final_text, updated_history). The returned history excludes the
    system prompt so it can be persisted across turns without duplication.
    """
    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        *history,
        {"role": "user", "content": user_msg},
    ]

    for step in range(max_steps):
        try:
            resp = requests.post(
                OLLAMA_URL,
                json={
                    "model": model,
                    "messages": messages,
                    "tools": TOOL_SCHEMAS,
                    "stream": False,
                    "options": {"temperature": 0.2, "num_ctx": 16384},
                },
                timeout=300,
            ).json()
        except Exception as e:
            return f"Ollama call failed: {e}", history

        if "message" not in resp:
            return f"Ollama returned no message: {resp}", history

        msg = resp["message"]
        messages.append(msg)
        tool_calls = msg.get("tool_calls") or []

        if not tool_calls:
            text = msg.get("content", "")
            # Guardrail: re-prompt once if the model narrated an action without calling a tool.
            if step == 0 and _looks_like_fake_action(text):
                messages.append({
                    "role": "user",
                    "content": "You described an action but called no tool. Call the tool now or ask one question.",
                })
                continue
            return text, messages[1:]  # drop system from returned history

        for call in tool_calls:
            fn = call["function"]["name"]
            raw_args = call["function"].get("arguments", {})
            args = raw_args if isinstance(raw_args, dict) else json.loads(raw_args)
            print(f"  ⚙  {fn}({args})")
            if fn not in TOOLS:
                result = {"ok": False, "error": f"unknown tool {fn}"}
            else:
                try:
                    result = TOOLS[fn](**args)
                except TypeError as e:
                    result = {"ok": False, "error": f"bad arguments: {e}"}
            messages.append({
                "role": "tool",
                "content": json.dumps(result),
                "name": fn,
            })

    return "Step budget exhausted.", messages[1:]
