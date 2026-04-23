"""
larry_paths.py — portable path resolution for Agent Larry.

All scripts should import BASE_DIR / DATA_DIR / LOG_DIR / EXPORTS_DIR from here
instead of hardcoding paths. This makes the whole project runnable from any
location — USB stick, network share, Linux, Windows, or Mac.

Resolution order:
  1. $LARRY_HOME environment variable (if set and exists)
  2. Directory containing this file (default — travels with the repo)

This file has zero dependencies so it can be imported before any third-party
packages and works on bare Python 3.8+.
"""
from __future__ import annotations

__version__ = "2.1.0"

import os
import sys
from pathlib import Path

# 1. BASE_DIR — the project root. Anchored to __file__ so it works from any
#    location the script is launched from.
_env_home = os.environ.get("LARRY_HOME")
if _env_home and Path(_env_home).is_dir():
    BASE_DIR: Path = Path(_env_home).resolve()
else:
    BASE_DIR = Path(__file__).parent.resolve()

# 2. Standard subdirectories (project-relative — travel with the codebase).
DATA_DIR: Path = BASE_DIR / "data"
LOG_DIR: Path = BASE_DIR / "logs"
EXPORTS_DIR: Path = BASE_DIR / "exports"
CHROMA_DIR: Path = BASE_DIR / "chroma_db"
SANDBOX_DIR: Path = BASE_DIR / "sandbox"
CONFIG_FILE: Path = BASE_DIR / "larry_config.json"
MCP_CONFIG_FILE: Path = BASE_DIR / "mcp.json"

# Create mutable dirs on first import (cheap, idempotent).
for _d in (DATA_DIR, LOG_DIR, EXPORTS_DIR):
    try:
        _d.mkdir(parents=True, exist_ok=True)
    except Exception:
        pass


def resolve_under_base(*parts: str) -> Path:
    """Join a relative sub-path to BASE_DIR. Safe for user input."""
    p = BASE_DIR.joinpath(*parts).resolve()
    if BASE_DIR not in p.parents and p != BASE_DIR:
        raise ValueError(f"Path escapes BASE_DIR: {p}")
    return p


def is_windows() -> bool:
    return os.name == "nt"


def is_portable() -> bool:
    """True if we look like we're running from a removable/USB medium."""
    base = str(BASE_DIR).lower()
    return any(marker in base for marker in (
        "/media/", "/mnt/", "/run/media/",          # linux auto-mount
        ":\\", "usb", "removable",                   # windows drive letters
        "locallarry", "larry-backup", "casper",      # known larry USBs
    ))


def validate_env(required: list[str] | None = None, warn: list[str] | None = None) -> list[str]:
    """Check for missing environment variables at startup.

    Returns list of warnings (empty = all good). Prints warnings to stderr.
    """
    warnings = []
    for var in (required if required is not None else []):
        if not os.environ.get(var):
            msg = f"MISSING REQUIRED: ${var} is not set"
            warnings.append(msg)
            print(f"[larry_paths] {msg}", file=sys.stderr)
    _warn_list = warn if warn is not None else ["OLLAMA_HOST", "BRAVE_API_KEY", "GITHUB_TOKEN"]
    for var in _warn_list:
        if not os.environ.get(var):
            msg = f"OPTIONAL: ${var} not set — some features will be limited"
            warnings.append(msg)
    return warnings


if __name__ == "__main__":
    # Quick diagnostic: `python larry_paths.py` shows what the project resolves to.
    print(f"Agent Larry v{__version__}")
    print(f"BASE_DIR     = {BASE_DIR}")
    print(f"DATA_DIR     = {DATA_DIR}")
    print(f"LOG_DIR      = {LOG_DIR}")
    print(f"EXPORTS_DIR  = {EXPORTS_DIR}")
    print(f"CHROMA_DIR   = {CHROMA_DIR}")
    print(f"CONFIG_FILE  = {CONFIG_FILE}  (exists={CONFIG_FILE.exists()})")
    print(f"is_windows   = {is_windows()}")
    print(f"is_portable  = {is_portable()}")
    print()
    env_warnings = validate_env()
    if env_warnings:
        print(f"Environment warnings ({len(env_warnings)}):")
        for w in env_warnings:
            print(f"  - {w}")
    else:
        print("Environment: all checks passed")
