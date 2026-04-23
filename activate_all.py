#!/usr/bin/env python3
"""
Larry Agent - Service Activation Script
========================================
Activates all services in the correct order:
1. Check/start Ollama
2. Initialize databases
3. Load MCP servers
4. Start agent

Usage:
    python activate_all.py              # Start everything
    python activate_all.py --check      # Check status only
    python activate_all.py --agent      # Start agent only
    python activate_all.py --telegram   # Start telegram bot only
    python activate_all.py --both       # Start both agent and telegram
"""

import os
import sys

# =============================================================================
# DISABLE TELEMETRY BEFORE ANY IMPORTS
# =============================================================================
os.environ["ANONYMIZED_TELEMETRY"] = "False"
os.environ["CHROMA_TELEMETRY"] = "False"
os.environ["POSTHOG_DISABLED"] = "1"
os.environ["DO_NOT_TRACK"] = "1"
os.environ["TF_ENABLE_ONEDNN_OPTS"] = "0"  # Suppress TensorFlow warnings
os.environ["TF_CPP_MIN_LOG_LEVEL"] = "2"   # Suppress TensorFlow info logs

# HuggingFace - set token if available, or use offline mode
HF_TOKEN = os.environ.get("HF_TOKEN", os.environ.get("HUGGINGFACE_TOKEN", ""))
if HF_TOKEN:
    os.environ["HF_TOKEN"] = HF_TOKEN
    os.environ["HUGGINGFACE_TOKEN"] = HF_TOKEN
else:
    # Use local cache only if no token
    os.environ["HF_HUB_OFFLINE"] = "1"
    os.environ["TRANSFORMERS_OFFLINE"] = "1"

import time
import json
import signal
import argparse
import subprocess
import threading
from pathlib import Path
from typing import Optional, Dict, List, Tuple
from dataclasses import dataclass
from datetime import datetime

# Project root
PROJECT_ROOT = Path(__file__).parent.resolve()
sys.path.insert(0, str(PROJECT_ROOT))

# =============================================================================
# CONFIGURATION
# =============================================================================

@dataclass
class ServiceStatus:
    name: str
    running: bool
    message: str
    pid: Optional[int] = None


class Colors:
    GOLD = '\033[38;2;255;215;0m'
    GREEN = '\033[92m'
    YELLOW = '\033[93m'
    RED = '\033[91m'
    CYAN = '\033[96m'
    BOLD = '\033[1m'
    END = '\033[0m'


# =============================================================================
# SERVICE CHECKS
# =============================================================================

def check_ollama() -> ServiceStatus:
    """Check if Ollama is running."""
    try:
        import requests
        resp = requests.get("http://localhost:11434/api/tags", timeout=5)
        if resp.status_code == 200:
            models = resp.json().get("models", [])
            return ServiceStatus("Ollama", True, f"Running with {len(models)} models")
    except Exception:
        pass
    return ServiceStatus("Ollama", False, "Not running - start with 'ollama serve'")


def start_ollama() -> bool:
    """Attempt to start Ollama."""
    try:
        # Check if ollama command exists
        if sys.platform == "win32":
            subprocess.Popen(["ollama", "serve"], 
                           creationflags=subprocess.CREATE_NEW_CONSOLE,
                           cwd=PROJECT_ROOT)
        else:
            subprocess.Popen(["ollama", "serve"],
                           stdout=subprocess.DEVNULL,
                           stderr=subprocess.DEVNULL,
                           start_new_session=True)
        time.sleep(3)  # Wait for startup
        return check_ollama().running
    except Exception as e:
        print(f"{Colors.RED}Failed to start Ollama: {e}{Colors.END}")
        return False


def check_databases() -> ServiceStatus:
    """Check database connectivity."""
    try:
        # Check SQLite
        from unified_context_manager import UnifiedContextManager
        ctx = UnifiedContextManager()
        
        # Check ChromaDB
        from production_rag import ProductionRAG
        rag = ProductionRAG()
        config = rag.get_config()
        
        kb_count = rag.kb_collection.count() if rag.kb_collection else 0
        code_count = rag.code_collection.count() if rag.code_collection else 0
        
        return ServiceStatus("Databases", True, 
                           f"SQLite OK, ChromaDB: {kb_count + code_count} docs")
    except Exception as e:
        return ServiceStatus("Databases", False, str(e))


def check_mcp_servers() -> ServiceStatus:
    """Check MCP server availability."""
    try:
        from mcp_servers import (
            FilesystemServer, MemoryServer, SQLiteServer,
            BraveSearchServer, PlaywrightServer, TimeServer
        )
        
        servers = ["filesystem", "memory", "sqlite", "brave-search", "playwright", "time"]
        return ServiceStatus("MCP Servers", True, f"{len(servers)} servers available")
    except Exception as e:
        return ServiceStatus("MCP Servers", False, str(e))


def check_models() -> ServiceStatus:
    """Check available Ollama models."""
    try:
        from model_router import ModelRouter
        router = ModelRouter()
        models = router.available_models
        
        if models:
            return ServiceStatus("Models", True, f"{len(models)} models available")
        return ServiceStatus("Models", False, "No models found")
    except Exception as e:
        return ServiceStatus("Models", False, str(e))


# =============================================================================
# AGENT LAUNCHER
# =============================================================================

class AgentLauncher:
    """Launch and manage agent processes."""
    
    def __init__(self):
        self.processes: Dict[str, subprocess.Popen] = {}
        self.running = True
        
        # Handle shutdown signals
        signal.signal(signal.SIGINT, self._shutdown)
        signal.signal(signal.SIGTERM, self._shutdown)
    
    def _shutdown(self, signum, frame):
        """Handle shutdown signal."""
        print(f"\n{Colors.YELLOW}Shutting down...{Colors.END}")
        self.running = False
        for name, proc in self.processes.items():
            if proc.poll() is None:
                print(f"  Stopping {name}...")
                proc.terminate()
                try:
                    proc.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    proc.kill()
        sys.exit(0)
    
    def start_agent(self) -> bool:
        """Start the main agent."""
        agent_path = PROJECT_ROOT / "agent_v2.py"
        if not agent_path.exists():
            print(f"{Colors.RED}agent_v2.py not found{Colors.END}")
            return False
        
        print(f"{Colors.CYAN}Starting Larry Agent...{Colors.END}")
        
        try:
            if sys.platform == "win32":
                # On Windows, use CREATE_NEW_CONSOLE for interactive agent
                proc = subprocess.Popen(
                    [sys.executable, str(agent_path)],
                    cwd=PROJECT_ROOT,
                    creationflags=subprocess.CREATE_NEW_CONSOLE
                )
            else:
                proc = subprocess.Popen(
                    [sys.executable, str(agent_path)],
                    cwd=PROJECT_ROOT
                )
            
            self.processes["agent"] = proc
            return True
        except Exception as e:
            print(f"{Colors.RED}Failed to start agent: {e}{Colors.END}")
            return False
    
    def start_telegram(self) -> bool:
        """Start the Telegram bot."""
        bot_path = PROJECT_ROOT / "telegram_bot.py"
        if not bot_path.exists():
            print(f"{Colors.RED}telegram_bot.py not found{Colors.END}")
            return False
        
        print(f"{Colors.CYAN}Starting Telegram Bot...{Colors.END}")
        
        try:
            proc = subprocess.Popen(
                [sys.executable, str(bot_path)],
                cwd=PROJECT_ROOT,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE
            )
            self.processes["telegram"] = proc
            return True
        except Exception as e:
            print(f"{Colors.RED}Failed to start telegram bot: {e}{Colors.END}")
            return False
    
    def wait(self):
        """Wait for processes to complete."""
        while self.running and self.processes:
            for name, proc in list(self.processes.items()):
                if proc.poll() is not None:
                    print(f"{Colors.YELLOW}{name} exited with code {proc.returncode}{Colors.END}")
                    del self.processes[name]
            time.sleep(1)


# =============================================================================
# MAIN
# =============================================================================

def print_banner():
    """Print startup banner."""
    print(f"""
{Colors.GOLD}{Colors.BOLD}╔══════════════════════════════════════════════════════════════════╗
║                                                                  ║
║   ██╗      █████╗ ██████╗ ██████╗ ██╗   ██╗                     ║
║   ██║     ██╔══██╗██╔══██╗██╔══██╗╚██╗ ██╔╝                     ║
║   ██║     ███████║██████╔╝██████╔╝ ╚████╔╝                      ║
║   ██║     ██╔══██║██╔══██╗██╔══██╗  ╚██╔╝                       ║
║   ███████╗██║  ██║██║  ██║██║  ██║   ██║                        ║
║   ╚══════╝╚═╝  ╚═╝╚═╝  ╚═╝╚═╝  ╚═╝   ╚═╝                        ║
║                                                                  ║
║           G-FORCE AI AGENT - LOCAL LLM SYSTEM                   ║
║                                                                  ║
╚══════════════════════════════════════════════════════════════════╝{Colors.END}
""")


def check_all_services() -> List[ServiceStatus]:
    """Check all services and return status list."""
    services = [
        check_ollama(),
        check_databases(),
        check_mcp_servers(),
        check_models(),
    ]
    return services


def print_status(services: List[ServiceStatus]):
    """Print service status table."""
    print(f"\n{Colors.BOLD}Service Status:{Colors.END}")
    print(f"{'─' * 60}")
    
    for svc in services:
        status_icon = f"{Colors.GREEN}✓{Colors.END}" if svc.running else f"{Colors.RED}✗{Colors.END}"
        print(f"  {status_icon} {svc.name:<20} {svc.message}")
    
    print(f"{'─' * 60}")
    
    all_ok = all(s.running for s in services)
    if all_ok:
        print(f"{Colors.GREEN}All services ready!{Colors.END}")
    else:
        print(f"{Colors.YELLOW}Some services need attention{Colors.END}")
    
    return all_ok


def main():
    parser = argparse.ArgumentParser(description="Larry Agent Activation")
    parser.add_argument("--check", action="store_true", help="Check status only")
    parser.add_argument("--agent", action="store_true", help="Start agent only")
    parser.add_argument("--telegram", action="store_true", help="Start telegram only")
    parser.add_argument("--both", action="store_true", help="Start both agent and telegram")
    parser.add_argument("--auto-start-ollama", action="store_true", help="Auto-start Ollama if not running")
    parser.add_argument("--no-banner", action="store_true", help="Skip banner")
    
    args = parser.parse_args()
    
    os.chdir(PROJECT_ROOT)
    
    if not args.no_banner:
        print_banner()
    
    print(f"{Colors.CYAN}Checking services...{Colors.END}")
    services = check_all_services()
    
    # Try to start Ollama if needed
    ollama_status = services[0]
    if not ollama_status.running and args.auto_start_ollama:
        print(f"{Colors.YELLOW}Starting Ollama...{Colors.END}")
        if start_ollama():
            services[0] = check_ollama()
    
    all_ok = print_status(services)
    
    if args.check:
        sys.exit(0 if all_ok else 1)
    
    # Determine what to start
    start_agent = args.agent or args.both or (not args.telegram)
    start_telegram = args.telegram or args.both
    
    if not services[0].running:  # Ollama
        print(f"\n{Colors.RED}Cannot start - Ollama not running{Colors.END}")
        print(f"Start Ollama first: ollama serve")
        sys.exit(1)
    
    launcher = AgentLauncher()
    
    if start_agent:
        launcher.start_agent()
    
    if start_telegram:
        launcher.start_telegram()
    
    if launcher.processes:
        print(f"\n{Colors.GREEN}Services started. Press Ctrl+C to stop.{Colors.END}")
        launcher.wait()
    else:
        print(f"\n{Colors.YELLOW}No services started{Colors.END}")


if __name__ == "__main__":
    main()
