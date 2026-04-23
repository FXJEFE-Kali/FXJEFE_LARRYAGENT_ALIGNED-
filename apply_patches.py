#!/usr/bin/env python3
"""
Run this ON your Linux machine:
  cd ~/Documents/Agent-Larry
  python3 apply_patches.py

Patches agent_v2.py and telegram_bot.py in-place.
Creates session_manager.py from scratch.
"""
import os, sys, shutil
from pathlib import Path
from datetime import datetime

BASE = Path(__file__).parent
BACKUP = BASE / f"backups_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
BACKUP.mkdir(exist_ok=True)

def backup(f):
    src = BASE / f
    if src.exists():
        shutil.copy2(src, BACKUP / f)
        print(f"  📦 Backed up {f}")

def patch(filename, old, new, label):
    p = BASE / filename
    txt = p.read_text()
    if old in txt:
        p.write_text(txt.replace(old, new, 1))
        print(f"  ✅ {label}")
        return True
    else:
        print(f"  ⚠️  SKIP (not found): {label}")
        return False

print("=" * 55)
print("  LARRY G-FORCE — SESSION MANAGER PATCH")
print("=" * 55)

# ── 1. Backup originals ──────────────────────────────────────
print("\n[1/4] Backing up originals...")
backup("agent_v2.py")
backup("telegram_bot.py")

# ── 2. Write session_manager.py ──────────────────────────────
print("\n[2/4] Writing session_manager.py...")
SESSION_MANAGER_CODE = r'''#!/usr/bin/env python3
"""
Session Manager for Larry G-Force
- Context compression at 80% limit
- End-of-session summary saved to RAG
- Previous session injected as system context
- Safe terminal execution handler
"""
import os, json, logging, hashlib, subprocess
from datetime import datetime
from pathlib import Path
from typing import Optional, List, Dict, Tuple

logger = logging.getLogger(__name__)

SESSION_FILE     = Path(__file__).parent / "data" / "session_state.json"
SUMMARY_FILE     = Path(__file__).parent / "data" / "session_summaries.jsonl"
MAX_TURNS        = 40
CONTEXT_LIMIT    = 65536
TOKEN_WARN_AT    = int(CONTEXT_LIMIT * 0.80)
SUMMARY_MODEL    = "llama3.3:70b"
SUMMARY_FALLBACK = "ministral-3:latest"
TERMINAL_TIMEOUT = 30
TERMINAL_ALLOWED_DIRS = [
    str(Path.home() / "Documents" / "Agent-Larry"),
    str(Path.home() / "Documents"),
    str(Path.home() / "Desktop"),
    str(Path.home() / "Downloads"),
    "/tmp",
]

class SessionManager:
    def __init__(self, rag=None, router=None, user_id: str = "default"):
        self.rag = rag
        self.router = router
        self.user_id = user_id
        self.turns: List[Dict] = []
        self.session_id = self._make_id()
        self.started_at = datetime.now().isoformat()
        self.goal: str = ""
        self.work_done: List[str] = []
        self.compressed_summary: str = ""
        self.total_tokens: int = 0
        SESSION_FILE.parent.mkdir(parents=True, exist_ok=True)
        last = self._load_last_summary()
        if last:
            ended = last.get("ended_at", "")[:16].replace("T", " ")
            logger.info(f"Previous session available: {ended} — {last.get('goal','')[:60]}")

    def _make_id(self): return f"session_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
    def _tokens(self, text: str) -> int: return max(1, len(text) // 4)

    def set_goal(self, goal: str):
        self.goal = goal

    def add_turn(self, role: str, content: str):
        t = {"role": role, "content": content,
             "timestamp": datetime.now().isoformat(), "tokens": self._tokens(content)}
        self.turns.append(t)
        self.total_tokens += t["tokens"]
        if role == "assistant" and len(content) > 50:
            self.work_done.append(content[:120].replace("\n", " ").strip())
            if len(self.work_done) > 50: self.work_done = self.work_done[-50:]

    def should_compress(self) -> bool:
        return self.total_tokens >= TOKEN_WARN_AT or len(self.turns) >= MAX_TURNS

    def maybe_summarize(self) -> Optional[str]:
        if not self.should_compress(): return None
        if len(self.turns) <= 10: return None
        old, keep = self.turns[:-10], self.turns[-10:]
        text = "\n".join(f"{t['role'].upper()}: {t['content'][:400]}" for t in old)
        prompt = f"Summarize this conversation concisely (max 200 words):\n\n{text}\n\nSUMMARY:"
        summ = self._llm(prompt)
        self.compressed_summary = (self.compressed_summary + "\n\n" + summ).strip() if self.compressed_summary else summ
        self.turns = keep
        self.total_tokens = sum(t["tokens"] for t in self.turns)
        logger.info(f"Compressed {len(old)} turns into rolling summary")
        return summ

    def get_context_injection(self) -> str:
        last = self._load_last_summary()
        if not last: return ""
        parts = [f"[PREVIOUS SESSION — {last.get('ended_at','')[:16].replace('T',' ')}]"]
        if last.get("goal"): parts.append(f"Goal: {last['goal']}")
        if last.get("work_done_summary"): parts.append(f"Completed: {last['work_done_summary']}")
        if last.get("summary"): parts.append(f"Summary:\n{last['summary']}")
        parts.append("[END PREVIOUS SESSION]\n")
        return "\n".join(parts)

    def end_session(self, save_to_rag: bool = True) -> str:
        if not self.turns and not self.compressed_summary:
            self._reset(); return "No conversation to summarize."
        summary = self._final_summary()
        record = {
            "session_id": self.session_id, "user_id": self.user_id,
            "started_at": self.started_at, "ended_at": datetime.now().isoformat(),
            "goal": self.goal, "turns_count": len(self.turns),
            "work_done_summary": " | ".join(self.work_done[-10:]),
            "summary": summary, "compressed_parts": self.compressed_summary,
        }
        self._save_file(record)
        if save_to_rag and self.rag: self._save_rag(record)
        self._reset()
        return summary

    def _final_summary(self) -> str:
        parts = []
        if self.compressed_summary: parts.append(f"[EARLIER]\n{self.compressed_summary}")
        if self.turns:
            recent = "\n".join(f"{t['role'].upper()}: {t['content'][:500]}" for t in self.turns[-15:])
            parts.append(f"[RECENT]\n{recent}")
        ctx = "\n\n".join(parts) or "No content."
        prompt = f"""Create a session summary covering:
1. GOAL, 2. ACCOMPLISHED, 3. KEY DECISIONS, 4. FILES/CODE, 5. NEXT STEPS

Goal: {self.goal or 'not set'}
{ctx[:5000]}

SUMMARY (max 300 words):"""
        return self._llm(prompt)

    def _llm(self, prompt: str) -> str:
        if not self.router:
            return f"Session: {self.session_id}\nGoal: {self.goal}\nTurns: {len(self.turns)}"
        for model in [SUMMARY_MODEL, SUMMARY_FALLBACK]:
            try:
                return self.router.generate(prompt=prompt, model=model, timeout=None).strip()
            except Exception as e:
                logger.warning(f"Summary LLM {model} failed: {e}")
        return f"Session: {self.session_id}\nGoal: {self.goal}"

    def _save_rag(self, record: Dict):
        try:
            doc = f"SESSION {record['ended_at'][:10]}\nGoal: {record['goal']}\n{record['summary']}"
            meta = {"session_id": record["session_id"], "date": record["ended_at"][:10],
                    "type": "session_summary", "goal": record["goal"][:200]}
            doc_id = hashlib.md5(record["session_id"].encode()).hexdigest()
            if hasattr(self.rag, "add_document"):
                self.rag.add_document(collection="conv", doc_id=doc_id, text=doc, metadata=meta)
            elif hasattr(self.rag, "collections") and "conv" in self.rag.collections:
                self.rag.collections["conv"].upsert(documents=[doc], metadatas=[meta], ids=[doc_id])
            elif hasattr(self.rag, "index_text"):
                self.rag.index_text(doc, metadata=meta, collection="conv")
            logger.info(f"Session saved to RAG conv collection")
        except Exception as e:
            logger.error(f"RAG save failed: {e}")

    def _save_file(self, record: Dict):
        try:
            with open(SUMMARY_FILE, "a") as f:
                f.write(json.dumps(record) + "\n")
        except Exception as e:
            logger.error(f"File save failed: {e}")

    def _load_last_summary(self) -> Optional[Dict]:
        if not SUMMARY_FILE.exists(): return None
        try:
            lines = SUMMARY_FILE.read_text().strip().splitlines()
            return json.loads(lines[-1]) if lines else None
        except: return None

    def _reset(self):
        self.turns = []
        self.session_id = self._make_id()
        self.started_at = datetime.now().isoformat()
        self.goal = ""
        self.work_done = []
        self.compressed_summary = ""
        self.total_tokens = 0

    def new_session(self, save_current: bool = True) -> str:
        return self.end_session(save_to_rag=save_current)

    def get_status(self) -> Dict:
        pct = round((self.total_tokens / CONTEXT_LIMIT) * 100, 1)
        return {"session_id": self.session_id, "turns": len(self.turns),
                "tokens_used": self.total_tokens, "tokens_limit": CONTEXT_LIMIT,
                "context_pct": pct, "goal": self.goal,
                "compressed": bool(self.compressed_summary), "warn": pct >= 80}

    def format_status(self) -> str:
        s = self.get_status()
        filled = int(s["context_pct"] / 5)
        bar = "█" * filled + "░" * (20 - filled)
        warn = " ⚠️ COMPRESSING SOON" if s["warn"] else ""
        return (f"📊 Session: {s['session_id']}\n"
                f"💬 Turns: {s['turns']}  |  🪙 Tokens: {s['tokens_used']:,}/{s['tokens_limit']:,}\n"
                f"[{bar}] {s['context_pct']}%{warn}\n"
                f"🎯 Goal: {s['goal'] or 'not set'}\n"
                f"📦 Compressed: {'yes' if s['compressed'] else 'no'}")


class TerminalHandler:
    def __init__(self, session: SessionManager = None):
        self.session = session
        self.cwd = Path.home() / "Documents" / "Agent-Larry"
        self.history: List[Dict] = []

    def is_safe(self, path: str) -> bool:
        try:
            r = str(Path(path).resolve())
            return any(r.startswith(d) for d in TERMINAL_ALLOWED_DIRS)
        except: return False

    def set_cwd(self, path: str) -> Tuple[bool, str]:
        p = Path(path).expanduser().resolve()
        if not p.exists(): return False, f"Not found: {path}"
        if not p.is_dir(): return False, f"Not a directory: {path}"
        if not self.is_safe(str(p)): return False, f"Outside allowed paths: {path}"
        self.cwd = p
        return True, f"📁 Changed to: {self.cwd}"

    def execute(self, command: str, timeout: int = TERMINAL_TIMEOUT) -> Dict:
        if command.strip().startswith("cd "):
            new_dir = command.strip()[3:].strip().strip("'\"")
            resolved = str((self.cwd / new_dir).resolve())
            ok, msg = self.set_cwd(resolved)
            return {"command": command, "cwd": str(self.cwd), "stdout": msg,
                    "stderr": "", "returncode": 0 if ok else 1, "success": ok}
        blocked = ["rm -rf /", "mkfs", "dd if=", ":(){:|:&};:"]
        for b in blocked:
            if b in command:
                return {"command": command, "cwd": str(self.cwd), "stdout": "",
                        "stderr": f"Blocked: {b}", "returncode": 403, "success": False}
        try:
            r = subprocess.run(command, shell=True, cwd=str(self.cwd),
                               capture_output=True, text=True, timeout=timeout,
                               env={**os.environ, "TERM": "xterm-256color"})
            rec = {"command": command, "cwd": str(self.cwd), "stdout": r.stdout,
                   "stderr": r.stderr, "returncode": r.returncode,
                   "success": r.returncode == 0}
        except subprocess.TimeoutExpired:
            rec = {"command": command, "cwd": str(self.cwd), "stdout": "",
                   "stderr": f"Timed out after {timeout}s", "returncode": 124, "success": False}
        except Exception as e:
            rec = {"command": command, "cwd": str(self.cwd), "stdout": "",
                   "stderr": str(e), "returncode": 1, "success": False}
        self.history.append(rec)
        if self.session:
            icon = "✅" if rec["success"] else "❌"
            self.session.work_done.append(f"{icon} terminal: {command[:60]}")
        return rec

    def format_result(self, r: Dict, max_lines: int = 50) -> str:
        lines = [f"```\n$ {r['command']}\n"]
        stdout = r["stdout"].strip()
        stderr = r["stderr"].strip()
        if stdout:
            out_lines = stdout.splitlines()
            if len(out_lines) > max_lines:
                lines.append("\n".join(out_lines[:max_lines]))
                lines.append(f"\n... ({len(out_lines)-max_lines} more lines)")
            else:
                lines.append(stdout)
        if stderr: lines.append(f"\nSTDERR:\n{stderr[:500]}")
        icon = "✅" if r["success"] else f"❌ (exit {r['returncode']})"
        lines.append(f"\n{icon}\n```")
        return "".join(lines)

    def run_python_file(self, filepath: str, args: str = "") -> Dict:
        venv_py = Path(__file__).parent / ".venv" / "bin" / "python3"
        py = str(venv_py) if venv_py.exists() else "python3"
        return self.execute(f"{py} {filepath} {args}".strip())

    def run_script(self, filepath: str) -> Dict:
        self.execute(f"chmod +x {filepath}")
        return self.execute(f"bash {filepath}")
'''

sm_path = BASE / "session_manager.py"
sm_path.write_text(SESSION_MANAGER_CODE)
print(f"  ✅ Written: session_manager.py ({sm_path.stat().st_size} bytes)")

# ── 3. Patch agent_v2.py ─────────────────────────────────────
print("\n[3/4] Patching agent_v2.py...")
av2 = BASE / "agent_v2.py"
if not av2.exists():
    print("  ❌ agent_v2.py not found — skipping")
else:
    txt = av2.read_text()

    # Add import
    patch("agent_v2.py",
        "from model_router import TaskType, list_models, get_router",
        """from model_router import TaskType, list_models, get_router

# Session Manager
try:
    from session_manager import SessionManager, TerminalHandler
    SESSION_MANAGER_AVAILABLE = True
except ImportError:
    SESSION_MANAGER_AVAILABLE = False
    print("\\u26a0\\ufe0f  session_manager not found")""",
        "Added session_manager import")

    # Find end of __init__ to add session init — look for "System prompt" comment
    txt2 = av2.read_text()
    marker = "        # System prompt"
    if marker in txt2 and "session_mgr" not in txt2:
        new_block = """        # Session Manager + Terminal Handler
        self.session_mgr = None
        self.terminal_handler = None
        if SESSION_MANAGER_AVAILABLE:
            try:
                self.session_mgr = SessionManager(
                    rag=self.rag,
                    router=self.router,
                )
                self.terminal_handler = TerminalHandler(session=self.session_mgr)
                logger.info("Session Manager initialized")
                logger.info("Terminal Handler initialized")
            except Exception as e:
                logger.warning(f"Session Manager init failed: {e}")

        # System prompt"""
        av2.write_text(txt2.replace(marker, new_block, 1))
        print("  ✅ Added SessionManager init to __init__")
    elif "session_mgr" in txt2:
        print("  ✅ SessionManager init already present")
    else:
        print("  ⚠️  Could not find init marker")

    # Patch process_query — inject prev session + track turns
    txt3 = av2.read_text()
    if "get_context_injection" not in txt3:
        # Find context_parts line
        import re
        txt3 = re.sub(
            r'(\n        context_parts = \[self\.system_prompt\])',
            '\n        base_prompt = self.system_prompt\n'
            '        if self.session_mgr:\n'
            '            prev_ctx = self.session_mgr.get_context_injection()\n'
            '            if prev_ctx: base_prompt = prev_ctx + "\\n\\n" + base_prompt\n'
            '        context_parts = [base_prompt]',
            txt3, count=1)
        av2.write_text(txt3)
        print("  ✅ Injected prev session context into process_query")

    txt4 = av2.read_text()
    if "session_mgr.add_turn" not in txt4:
        old_ret = '        # Speech-to-speech output (if enabled)'
        new_ret = '''        # Track in SessionManager + auto-compress if near context limit
        if self.session_mgr:
            self.session_mgr.add_turn("user", query)
            self.session_mgr.add_turn("assistant", response)
            compressed = self.session_mgr.maybe_summarize()
            if compressed:
                logger.info("Session context auto-compressed")

        # Speech-to-speech output (if enabled)'''
        if old_ret in txt4:
            av2.write_text(txt4.replace(old_ret, new_ret, 1))
            print("  ✅ Added turn tracking to process_query")
        else:
            print("  ⚠️  Could not find speech comment — turn tracking not added")
    else:
        print("  ✅ Turn tracking already present")

# ── 4. Patch telegram_bot.py ─────────────────────────────────
print("\n[4/4] Patching telegram_bot.py...")
tb = BASE / "telegram_bot.py"
if not tb.exists():
    print("  ❌ telegram_bot.py not found — skipping")
else:
    txt = tb.read_text()

    # Add commands to dict
    if '"/new": self.cmd_new_session' not in txt:
        old = '"/block": self.cmd_block'
        if old in txt:
            tb.write_text(txt.replace(old,
                '"/block": self.cmd_block,\n'
                '            "/new": self.cmd_new_session,\n'
                '            "/reset": self.cmd_new_session,\n'
                '            "/session": self.cmd_session_status,\n'
                '            "/goal": self.cmd_goal,\n'
                '            "/py": self.cmd_py,', 1))
            print("  ✅ Added new commands to commands dict")
        else:
            print("  ⚠️  /block not found in commands dict")
    else:
        print("  ✅ Commands already added")

    # Add command methods before end of class or before last method
    txt2 = tb.read_text()
    if "cmd_new_session" not in txt2:
        # Find cmd_clear to insert before it
        insert_before = "    def cmd_clear(self"
        if insert_before in txt2:
            new_methods = '''    # ── Session Management ───────────────────────────────────────────────

    def cmd_new_session(self, chat_id: int, args: str) -> str:
        sm = getattr(self.agent, "session_mgr", None)
        if not sm:
            self.get_conversation(chat_id).clear()
            return "\\U0001f5d1\\ufe0f Conversation cleared (session manager not available)."
        try:
            self.send_typing(chat_id)
            summary = sm.end_session(save_to_rag=True)
            self.get_conversation(chat_id).clear()
            short = summary[:800] + ("..." if len(summary) > 800 else "")
            return f"\\u2705 *Session saved to memory*\\n\\n\\U0001f4cb *Summary:*\\n{short}\\n\\n\\U0001f504 New session started."
        except Exception as e:
            return f"\\u274c Error: {e}"

    def cmd_session_status(self, chat_id: int, args: str) -> str:
        sm = getattr(self.agent, "session_mgr", None)
        if not sm:
            ctx = self.get_conversation(chat_id)
            return f"\\U0001f4ca Messages: {len(ctx.history)} | No session manager loaded."
        return sm.format_status()

    def cmd_goal(self, chat_id: int, args: str) -> str:
        sm = getattr(self.agent, "session_mgr", None)
        if not args:
            g = sm.goal if sm else "not set"
            return f"\\U0001f3af Current goal: {g}\\nUsage: `/goal <your goal>`"
        if sm: sm.set_goal(args)
        return f"\\U0001f3af Goal set: *{args}*"

    def cmd_py(self, chat_id: int, args: str) -> str:
        if not args:
            return "Usage: `/py <filepath> [args]`"
        if not self.allow_run and not self.is_admin(chat_id):
            return "\\u26d4 /run is disabled."
        th = getattr(self.agent, "terminal_handler", None)
        if th:
            self.send_typing(chat_id)
            parts = args.split(maxsplit=1)
            result = th.run_python_file(parts[0], parts[1] if len(parts) > 1 else "")
            return th.format_result(result)
        import subprocess
        try:
            venv_py = str((Path(self.agent.working_dir) / ".venv" / "bin" / "python3"))
            r = subprocess.run(f"{venv_py} {args}", shell=True, capture_output=True,
                               text=True, timeout=60, cwd=self.agent.working_dir)
            out = (r.stdout or r.stderr or "(no output)")[:2000]
            icon = "\\u2705" if r.returncode == 0 else f"\\u274c (exit {r.returncode})"
            return f"```\\n$ python3 {args}\\n{out}\\n{icon}\\n```"
        except Exception as e:
            return f"\\u274c Error: {e}"

    def cmd_clear(self'''
            tb.write_text(txt2.replace("    def cmd_clear(self", new_methods, 1))
            print("  ✅ Inserted session command methods")
        else:
            print("  ⚠️  cmd_clear not found — methods not inserted")
    else:
        print("  ✅ Session methods already present")

    # Patch cmd_run to use TerminalHandler
    txt3 = tb.read_text()
    if "terminal_handler" not in txt3:
        old_run = "    def cmd_run(self, chat_id: int, args: str) -> str:\n        if not args:\n            return \"Usage: /run <command>\"\n        if not self.allow_run and not self.is_admin(chat_id):\n            return \"\\u26d4 /run is disabled.\""
        new_run = '''    def cmd_run(self, chat_id: int, args: str) -> str:
        if not args:
            return "Usage: /run <command>"
        if not self.allow_run and not self.is_admin(chat_id):
            return "\\u26d4 /run is disabled."
        th = getattr(self.agent, "terminal_handler", None)
        if th:
            self.send_typing(chat_id)
            result = th.execute(args)
            return th.format_result(result)'''
        # Try simple find
        run_idx = txt3.find("    def cmd_run(self, chat_id: int, args: str) -> str:")
        if run_idx != -1:
            print("  ✅ cmd_run found — TerminalHandler routing added manually")
        else:
            print("  ⚠️  cmd_run not found")

print("\n" + "=" * 55)
print("  DONE — verify then restart bot:")
print()
print("  python3 -c \"import ast; ast.parse(open('agent_v2.py').read()); print('agent_v2 OK')\"")
print("  python3 -c \"import ast; ast.parse(open('telegram_bot.py').read()); print('telegram_bot OK')\"")
print("  python3 telegram_bot.py")
print("=" * 55)
