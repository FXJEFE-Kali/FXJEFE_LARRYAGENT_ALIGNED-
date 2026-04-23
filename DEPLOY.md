# Agent Larry — Deployment & Operations Guide

> **Status:** Portable (USB-runnable), cross-platform (Linux / macOS / Windows), Docker-ready.
> **Scope:** Personal multi-device deployment — ThinkPad (Win11 16GB), MacBook Pro M1 (macOS Tahoe 26.4, 8GB), Ubuntu 25 workstation (RTX 4060 8GB VRAM + 64GB DDR5).
> **Date:** 2026-04-09

---

## Table of Contents

1. [What Agent Larry Is](#1-what-agent-larry-is)
2. [Project Structure](#2-project-structure)
3. [Hardware Profiles & Recommended Models](#3-hardware-profiles--recommended-models)
4. [Configuration Files](#4-configuration-files)
5. [OS-Specific Install Paths](#5-os-specific-install-paths)
6. [Per-OS Setup](#6-per-os-setup)
    - [6.1 Ubuntu 25 (RTX 4060 workstation)](#61-ubuntu-25-rtx-4060-workstation)
    - [6.2 macOS Tahoe 26.4 on M1](#62-macos-tahoe-264-on-m1)
    - [6.3 Windows 11 (ThinkPad)](#63-windows-11-thinkpad)
7. [Running From USB](#7-running-from-usb)
8. [Docker Deployment](#8-docker-deployment)
9. [Environment Variables](#9-environment-variables)
10. [How To Launch (All Platforms)](#10-how-to-launch-all-platforms)
11. [Troubleshooting](#11-troubleshooting)
12. [File Manifest](#12-file-manifest)

---

## 1. What Agent Larry Is

Agent Larry (codename **LARRY G-FORCE**) is a local, multi-model AI agent built on top of Ollama. Core capabilities:

- **Task-based model routing** — picks the right model for each query (coding vs. analysis vs. ultra-context vs. fast chat)
- **Production RAG** — ChromaDB vector store with BAAI/bge-reranker-v2-m3 reranker
- **Web + finance tools** — headless Chromium scraping, YouTube transcripts, CoinGecko prices, forex rates, sentiment
- **MCP servers** — filesystem, memory graph, SQLite, Brave Search, GitHub, Playwright, time, context7
- **Kali security toolkit** — nmap / nikto / gobuster / etc. gated behind NL regex dispatch
- **Multi-frontend** — CLI (`agent_v2.py`), web dashboard (`dashboard_hub.py`), Telegram bot (`telegram_bot.py`)
- **Portable** — anchored to `Path(__file__).parent` via `larry_paths.py`; runs identically from HDD, USB, or container

---

## 2. Project Structure

```
Agent-Larry/                        ← $LARRY_HOME (BASE_DIR)
├── agent_v2.py                     ← main CLI entrypoint
├── dashboard_hub.py                ← web UI (http://127.0.0.1:3777)
├── telegram_bot.py                 ← Telegram frontend
├── larry_paths.py                  ← portable path resolution
├── larry_config.json               ← agent + model config
├── mcp.json                        ← MCP server registry
├── .env                            ← API keys + env vars
├── .env.example                    ← template
├── run_larry.sh                    ← Linux / macOS launcher
├── run_larry.bat                   ← Windows launcher
├── Dockerfile                      ← portable container image
├── docker-compose.yml              ← multi-service stack
├── requirements.txt                ← pip deps (full)
├── requirements-production.txt     ← pip deps (minimal)
├── DEPLOY.md                       ← this file
│
├── production_rag.py               ← RAG engine (Chroma + reranker)
├── web_tools.py                    ← WebScraper, YouTubeSummarizer, FinanceScraper
├── agent_tools.py                  ← Robin tool-calling loop (APScheduler)
├── hardware_profiles.py            ← SPEED / ACCURACY / ULTRA_CONTEXT profiles
├── model_router.py                 ← task→model routing
├── mcp_client.py                   ← MCP transport layer
├── mcp_servers/                    ← native MCP server implementations
│   ├── filesystem_server.py
│   ├── memory_server.py
│   ├── sqlite_server.py
│   ├── brave_search_server.py
│   ├── playwright_server.py
│   ├── context7_server.py
│   ├── time_server.py
│   └── ...
├── kali_tools.py                   ← security toolkit dispatch
├── safe_code_executor.py           ← sandboxed Python runner
├── file_browser.py                 ← chroot-style file handler
│
├── data/                           ← created at first run — SQLite, memory JSON
│   ├── unified_context.db
│   └── rag_memory.json
├── chroma_db/                      ← vector store (created at first run)
├── exports/                        ← scraped markdown, summaries
├── logs/                           ← rotating logs
└── sandbox/                        ← safe code execution workspace
```

**Key principle:** every writable directory is created under `BASE_DIR` on first run — nothing outside the project root is touched. This makes backup, relocation, and USB deployment trivial.

---

## 3. Hardware Profiles & Recommended Models

Your three machines have very different memory budgets. Pick the profile that matches.

| Machine              | RAM   | GPU / Accel            | Profile         | Default model (coding)    | Default model (chat)    |
|----------------------|-------|------------------------|-----------------|---------------------------|-------------------------|
| **MacBook Pro M1**   | 8 GB  | MPS (Metal unified)    | `TINY`          | `qwen2.5-coder:1.5b`      | `llama3.2:1b`           |
| **ThinkPad Win11**   | 16 GB | Integrated / CPU only  | `SPEED`         | `qwen2.5-coder:3b`        | `llama3.2:3b`           |
| **Ubuntu RTX 4060**  | 64 GB DDR5 + 8 GB VRAM | CUDA          | `ACCURACY` / `ULTRA_CONTEXT` | `qwen3-coder:30b`   | `dolphin-mixtral:8x7b`  |

### MacBook M1 (8 GB) — critical constraints
macOS reserves ~3 GB for the OS, leaving ~5 GB for everything else. You **cannot** run 7B+ models comfortably.

**Recommended models (pull only these):**
```bash
ollama pull llama3.2:1b           # 1.3 GB — general chat
ollama pull qwen2.5-coder:1.5b    # 986 MB — coding
ollama pull granite4:1b           # 1.0 GB — fast classify / routing
ollama pull nomic-embed-text      # 274 MB — RAG embeddings
```
Set `LARRY_PROFILE=TINY` and disable the reranker (see [§4](#4-configuration-files)).

### ThinkPad Win11 (16 GB DDR5, no dGPU)
Comfortable with 3B–7B models, CPU inference. Avoid anything over 7B unless you accept very slow generation.

**Recommended models:**
```bash
ollama pull llama3.2:3b           # 2.0 GB — chat
ollama pull qwen2.5-coder:3b      # 1.9 GB — coding
ollama pull qwen2.5:7b-instruct-q4_K_M  # 4.7 GB — analysis
ollama pull nomic-embed-text      # embeddings
```
Set `LARRY_PROFILE=SPEED`.

### Ubuntu 4060 workstation (64 GB + 8 GB VRAM)
The flagship. Can run 30B+ models CPU-offloaded (slow) or 14B fully on GPU (fast).

**Recommended models:**
```bash
ollama pull qwen3-coder:30b       # 18 GB — flagship coder (CPU offload)
ollama pull dolphin-mixtral:8x7b  # 26 GB — chat / analysis
ollama pull qwen2.5:14b-instruct  # 9 GB — GPU-resident fast
ollama pull qwen2.5-128k          # 14 GB — long context
ollama pull nomic-embed-text
ollama pull mxbai-embed-large     # 670 MB — better RAG embeddings
```
Set `LARRY_PROFILE=ACCURACY` or `ULTRA_CONTEXT`.

---

## 4. Configuration Files

### `larry_config.json`
Primary config. Already portable — `working_directory` is `null`, so it inherits from `larry_paths.BASE_DIR`.

Key fields:
```jsonc
{
  "working_directory": null,           // null = portable mode; let larry_paths resolve
  "hardware": {
    "mode": "GPU",                     // "GPU" or "CPU"
    "ram_gb": 64,
    "gpu": "RTX 4060 8GB",
    "gpu_power_limit_w": 100           // undervolt for stability
  },
  "ollama": {
    "host": "http://localhost:11434",  // or http://ollama:11434 in Docker
    "default_model": "dolphin-mixtral:8x7b",
    "embedding_model": "nomic-embed-text:latest",
    "keep_alive": "10m"
  },
  "profiles": {
    "default": "ACCURACY",             // SPEED | BALANCED | ACCURACY | ULTRA_CONTEXT
    "flagship_model": "llama3.3:70b",
    "coding_model": "qwen3-coder:30b",
    "fast_model": "ministral-3:latest"
  },
  "rag": {
    "backend": "chroma",
    "chroma_path": "./chroma_db",      // relative — portable
    "embedding_model": "nomic-embed-text:latest",
    "reranker_model": "BAAI/bge-reranker-v2-m3",
    "reranker_device": "cuda:0"        // set to "cpu" on Mac/Win, "cuda:0" on Linux RTX
  }
}
```

**Per-machine overrides** — keep one `larry_config.json` per machine or use env vars:
- MacBook M1 → `"reranker_device": "mps"` or `"cpu"`, profile `TINY`
- ThinkPad → `"reranker_device": "cpu"`, profile `SPEED`
- Ubuntu 4060 → `"reranker_device": "cuda:0"`, profile `ACCURACY`

### `mcp.json`
Registry of MCP servers. All paths inside are **relative** (`./sandbox`, `./memory.json`, `./data/unified_context.db`) — portable as-is.

### `.env`
API keys + environment variables. See [§9](#9-environment-variables).

---

## 5. OS-Specific Install Paths

The **recommended install location** differs per OS. Agent Larry itself works from any location — these are just conventions.

### Linux (Ubuntu 25)
| Purpose                | Path                                            |
|------------------------|-------------------------------------------------|
| Primary install        | `~/Documents/Agent-Larry`                       |
| Portable (USB)         | `/media/$USER/<USB_LABEL>/Agent-Larry`          |
| Ollama models          | `~/.ollama/models`                              |
| HuggingFace cache      | `~/.cache/huggingface`                          |
| Python venv (bundled)  | `<Agent-Larry>/.venv`                           |
| Logs                   | `<Agent-Larry>/logs/`                           |
| Vector store           | `<Agent-Larry>/chroma_db/`                      |
| Systemd unit (optional)| `~/.config/systemd/user/larry-agent.service`    |

### macOS (Tahoe 26.4 on M1)
| Purpose                | Path                                            |
|------------------------|-------------------------------------------------|
| Primary install        | `~/Documents/Agent-Larry`                       |
| Portable (USB)         | `/Volumes/<USB_LABEL>/Agent-Larry`              |
| Ollama models          | `~/.ollama/models`                              |
| HuggingFace cache      | `~/.cache/huggingface` (or `~/Library/Caches/huggingface`) |
| Python (Homebrew)      | `/opt/homebrew/bin/python3`                     |
| Python venv (bundled)  | `<Agent-Larry>/.venv`                           |
| Logs                   | `<Agent-Larry>/logs/`                           |
| LaunchAgent (optional) | `~/Library/LaunchAgents/com.larry.agent.plist`  |

### Windows 11 (ThinkPad)
| Purpose                | Path                                                             |
|------------------------|------------------------------------------------------------------|
| Primary install        | `C:\Users\<user>\Documents\Agent-Larry`                          |
| Portable (USB)         | `E:\Agent-Larry` (drive letter varies)                           |
| Ollama models          | `C:\Users\<user>\.ollama\models`                                 |
| HuggingFace cache      | `C:\Users\<user>\.cache\huggingface`                             |
| Python (python.org)    | `C:\Users\<user>\AppData\Local\Programs\Python\Python312\python.exe` |
| Python venv (bundled)  | `<Agent-Larry>\.venv`                                            |
| Logs                   | `<Agent-Larry>\logs\`                                            |
| Startup (optional)     | `shell:startup` → shortcut to `run_larry.bat dashboard`          |

---

## 6. Per-OS Setup

### 6.1 Ubuntu 25 (RTX 4060 workstation)

**1. Install Python 3.12 + build tools:**
```bash
sudo apt update
sudo apt install -y python3.12 python3.12-venv python3.12-dev \
    build-essential git curl jq ffmpeg \
    libnss3 libatk-bridge2.0-0 libgbm1 libasound2    # Playwright deps
```

**2. Install Ollama (native, GPU-enabled):**
```bash
curl -fsSL https://ollama.com/install.sh | sh
sudo systemctl enable --now ollama
```

**3. Install NVIDIA CUDA (if not already):**
```bash
# Ubuntu 25 usually ships with 550+ drivers
nvidia-smi                        # sanity check
# Ollama auto-detects CUDA — no manual config needed
```

**4. Clone/copy the project and create venv:**
```bash
cd ~/Documents
# Either: cp -r /media/$USER/LocalLarry-/Agent-Larry .
# Or: git clone <your-repo> Agent-Larry
cd Agent-Larry
python3.12 -m venv .venv
source .venv/bin/activate
pip install --upgrade pip
pip install -r requirements.txt
playwright install chromium
```

**5. Pull models:**
```bash
ollama pull qwen3-coder:30b
ollama pull dolphin-mixtral:8x7b
ollama pull qwen2.5:14b-instruct
ollama pull nomic-embed-text
ollama pull mxbai-embed-large
```

**6. First launch:**
```bash
./run_larry.sh paths       # verify paths resolve
./run_larry.sh             # interactive CLI
./run_larry.sh dashboard   # open http://127.0.0.1:3777
```

### 6.2 macOS Tahoe 26.4 on M1

**1. Install Homebrew + Python 3.12:**
```bash
/bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"
brew install python@3.12 git jq ffmpeg
```

**2. Install Ollama (native, uses Metal / MPS):**
```bash
brew install ollama
brew services start ollama
# OR: download https://ollama.com/download/mac and drag to /Applications
```

**3. Copy the project:**
```bash
cd ~/Documents
cp -r /Volumes/LocalLarry-/Agent-Larry .
cd Agent-Larry
/opt/homebrew/bin/python3.12 -m venv .venv
source .venv/bin/activate
pip install --upgrade pip
pip install -r requirements.txt
playwright install chromium
```

**4. Apply M1 low-RAM patch** — edit `larry_config.json`:
```jsonc
{
  "profiles": { "default": "SPEED" },
  "rag": {
    "reranker_device": "mps",   // or "cpu" if MPS causes issues
    "_reranker_disabled_comment": "On 8GB M1, disable reranker entirely:",
    "use_reranker": false
  },
  "ollama": {
    "default_model": "llama3.2:1b",
    "keep_alive": "2m"            // evict quickly to free RAM
  }
}
```

**5. Pull tiny models only:**
```bash
ollama pull llama3.2:1b
ollama pull qwen2.5-coder:1.5b
ollama pull granite4:1b
ollama pull nomic-embed-text
```

**6. First launch:**
```bash
./run_larry.sh paths
./run_larry.sh
```

> ⚠️ **Don't run dashboard + CLI + telegram simultaneously on the M1.** With 8 GB you'll swap hard. Pick one frontend at a time.

### 6.3 Windows 11 (ThinkPad)

**1. Install Python 3.12 from python.org:**
Download `python-3.12.x-amd64.exe`, tick **"Add python.exe to PATH"** and **"Install for all users"**.

**2. Install Ollama:**
Download `OllamaSetup.exe` from https://ollama.com/download/windows and run it. It installs a systray app and starts `ollama serve` automatically on `http://localhost:11434`.

**3. Install Git (if you want to clone):**
Download from https://git-scm.com/download/win

**4. Copy the project — from USB or Git:**
Open **PowerShell** (not CMD):
```powershell
cd $HOME\Documents
# From USB (drive letter varies — check File Explorer):
Copy-Item -Recurse E:\Agent-Larry .\Agent-Larry
cd Agent-Larry

# Create venv and install
py -3.12 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
pip install -r requirements.txt
playwright install chromium
```

If you hit `execution of scripts is disabled`, run once as admin:
```powershell
Set-ExecutionPolicy -Scope CurrentUser RemoteSigned
```

**5. Pull models:**
```powershell
ollama pull llama3.2:3b
ollama pull qwen2.5-coder:3b
ollama pull qwen2.5:7b-instruct-q4_K_M
ollama pull nomic-embed-text
```

**6. First launch:**
```powershell
.\run_larry.bat paths
.\run_larry.bat
.\run_larry.bat dashboard
```

Or double-click `run_larry.bat` in Explorer.

---

## 7. Running From USB

The USB sticks already have full deployments — no install required on the host, **but you still need Python and Ollama on the host machine**. The USB only carries the code, config, and venv (if bundled).

| USB              | Mount path (Linux)                                    | Mount path (macOS)            | Mount path (Windows) |
|------------------|-------------------------------------------------------|-------------------------------|----------------------|
| `LocalLarry-`    | `/media/<user>/LocalLarry-/Agent-Larry`               | `/Volumes/LocalLarry-/Agent-Larry` | `E:\Agent-Larry` (varies) |
| `LARRY-BACKUP`   | `/media/<user>/LARRY-BACKUP/Agent-Larry/backup_YYYYMMDD_HHMMSS` | same pattern | same pattern |
| `casper-rw`      | `/media/<user>/casper-rw/upper/home/ubuntu/Agent-Larry` (requires sudo) | n/a (Linux only) | n/a |

**Launch directly from USB:**
```bash
# Linux/macOS
/media/$USER/LocalLarry-/Agent-Larry/run_larry.sh paths
/media/$USER/LocalLarry-/Agent-Larry/run_larry.sh

# Windows
E:\Agent-Larry\run_larry.bat paths
E:\Agent-Larry\run_larry.bat
```

No path is hardcoded — the launcher sets `$LARRY_HOME` to the script's own directory and everything anchors to that.

> ⚠️ **USB write performance.** ChromaDB and SQLite are *very* chatty. First indexing on a USB-2 stick can take 10× longer than on an internal SSD. Recommendation: run from USB for setup/portability, but `cp -r` to local storage for daily use.

---

## 8. Docker Deployment

Docker is the easiest path for the ThinkPad and Ubuntu workstation. **Not recommended for the M1 MacBook** — Ollama inside a Linux container can't use Metal/MPS, so you'd be stuck on CPU and the 8 GB limit becomes brutal. On M1, use the native Ollama install.

### Quick start (Linux / Windows WSL2)

```bash
cd ~/Documents/Agent-Larry

# 1. Build and bring up the stack
docker compose build
docker compose up -d ollama        # Ollama first (heals before agent starts)

# 2. Pull models INTO the Ollama container
docker compose exec ollama ollama pull llama3.2:3b
docker compose exec ollama ollama pull qwen2.5-coder:3b
docker compose exec ollama ollama pull nomic-embed-text

# 3. Start agent (interactive)
docker compose run --rm -it agent
# OR start all services detached
docker compose up -d

# 4. View logs
docker compose logs -f agent

# 5. Launch dashboard (detached mode)
docker compose --profile dashboard up -d dashboard
# → open http://localhost:3777
```

### Docker services

| Service         | Image                     | Port  | Purpose                                   |
|-----------------|---------------------------|-------|-------------------------------------------|
| `ollama`        | `ollama/ollama:latest`    | 11434 | Local LLM inference                       |
| `agent`         | built from `./Dockerfile` | —     | Agent CLI (interactive via `docker compose run`) |
| `dashboard`     | built from `./Dockerfile` | 3777  | Web UI (profile: `dashboard`)             |
| `postgres`      | `ankane/pgvector:latest`  | 5432  | Optional pgvector backend                 |
| `n8n`           | `n8nio/n8n:latest`        | 5678  | Optional workflow automation (profile: `full`) |

### GPU passthrough (Ubuntu 4060)

Uncomment the `deploy.resources.reservations.devices` block in `docker-compose.yml` under the `ollama` service, then install `nvidia-container-toolkit`:
```bash
sudo apt install -y nvidia-container-toolkit
sudo systemctl restart docker
```
Ollama in the container will see the RTX 4060.

### Volumes (persisted on host)

All stateful data lives on the host filesystem under the project directory — **no Docker named volumes for Larry state** (only for Ollama models). Relocation is a `cp -r` away.

```
./chroma_db    →  /app/chroma_db     (vector store)
./data         →  /app/data          (SQLite, RAG memory)
./exports      →  /app/exports       (scraped content)
./logs         →  /app/logs
./sandbox      →  /app/sandbox       (safe code executor)
./mcp.json     →  /app/mcp.json      (MCP registry)
./larry_config.json → /app/larry_config.json
./.env         →  /app/.env
```

Named volume for Ollama models:
```
larry-ollama-data  →  /root/.ollama   (persists models between restarts)
```

---

## 9. Environment Variables

Stored in `.env` — already populated for personal use. Override via shell env if needed.

| Variable                      | Purpose                                      | Default                       |
|-------------------------------|----------------------------------------------|-------------------------------|
| `LARRY_HOME`                  | Override project root                        | (auto-detect from script dir) |
| `LARRY_PYTHON`                | Override python interpreter                  | `.venv/bin/python` → `python3`|
| `LARRY_ALLOWED_ROOTS`         | Extra paths agent may touch (`:` sep Linux, `;` Windows) | — |
| `LARRY_PROFILE`               | Hardware profile                             | `SPEED`                       |
| `OLLAMA_URL`                  | Ollama chat endpoint                         | `http://localhost:11434/api/chat` |
| `OLLAMA_HOST`                 | Ollama base URL                              | `http://localhost:11434`      |
| `LARRY_DEFAULT_MODEL`         | Fallback model when router fails             | `qwen2.5:7b-instruct`         |
| `HF_TOKEN` / `HUGGINGFACE_TOKEN` | HuggingFace for reranker download         | (blank)                       |
| `BRAVE_API_KEY`               | Brave Search MCP                             | (blank — disables search)     |
| `GITHUB_TOKEN`                | GitHub MCP                                   | (blank)                       |
| `TELEGRAM_BOT_TOKEN`          | Telegram bot frontend                        | (populated in .env)           |
| `TELEGRAM_ALLOWED_CHAT_IDS`   | Telegram allow-list                          | (populated in .env)           |
| `OPENROUTER_API_KEY`          | Optional cloud fallback                      | (blank)                       |
| `ANONYMIZED_TELEMETRY=False`  | Disable Chroma telemetry                     | set                           |
| `TOKENIZERS_PARALLELISM=false`| Silence HF warnings                          | set by launcher               |
| `CUDA_VISIBLE_DEVICES=0`      | Pin to single GPU (Ubuntu only)              | — set manually if needed      |

---

## 10. How To Launch (All Platforms)

### The one command you need to remember
```bash
./run_larry.sh <command>       # Linux / macOS
run_larry.bat <command>        # Windows
```

### Available commands

| Command         | What it does                                                    |
|-----------------|-----------------------------------------------------------------|
| *(none)* / `agent` / `cli` | Interactive CLI (`agent_v2.py`)                      |
| `dashboard` / `hub`        | Web UI on `http://127.0.0.1:3777`                    |
| `telegram`                 | Telegram bot listener                                |
| `paths` / `where`          | Print resolved project paths (diagnostic)            |
| `help`                     | Usage                                                |
| `<any script.py>`          | Run any project script with the bundled venv        |

### Examples

```bash
# Launch interactive agent (typical usage)
./run_larry.sh

# Open dashboard in browser, then keep agent running
./run_larry.sh dashboard &
./run_larry.sh

# Run the test suite
./run_larry.sh test_web_finance.py

# Print paths for debugging
./run_larry.sh paths

# Override LARRY_HOME to a different install
LARRY_HOME=/tmp/larry-test ./run_larry.sh paths
```

### Interactive CLI commands (inside `agent_v2.py`)
```
/help                    — list all commands
/models                  — show model routing table
/profile ACCURACY        — switch hardware profile
/scrape <url>            — scrape + markdown
/summarize <url>         — scrape + summarize via Ollama
/sentiment <topic>       — headlines + X + FF sentiment aggregate
/prices BTC,ETH crypto   — crypto prices via CoinGecko
/prices USD forex        — forex pairs via open.er-api.com
/headlines reuters       — scrape financial news
/forexfactory            — scrape FF calendar
/tools                   — list Kali / security tools
/rag stats               — ChromaDB stats
/exit                    — quit
```

---

## 11. Troubleshooting

### "Ollama not reachable"
- **Linux:** `systemctl status ollama` → `sudo systemctl restart ollama`
- **macOS:** `brew services restart ollama` or relaunch the Ollama app
- **Windows:** check systray Ollama icon; if missing, relaunch `OllamaSetup.exe`
- **Docker:** `docker compose logs ollama` — look for "listening on"
- Test: `curl http://localhost:11434/api/tags`

### "No module named 'beautifulsoup4'" (or any dep)
You launched with the wrong Python. The launcher prefers `.venv/bin/python` — if that's missing:
```bash
./run_larry.sh paths        # check which Python it picked
# If wrong, create the venv:
python3 -m venv .venv && source .venv/bin/activate && pip install -r requirements.txt
```

### MacBook M1 — out-of-memory / swap
1. Lower `num_ctx` in `larry_config.json` to `4096`
2. `use_reranker: false` in the RAG block
3. `keep_alive: "2m"` for fast model eviction
4. Use `llama3.2:1b` / `qwen2.5-coder:1.5b` only
5. Close all Chrome tabs 😄

### Windows — "execution of scripts is disabled"
PowerShell script-signing policy. One-time fix (admin PowerShell):
```powershell
Set-ExecutionPolicy -Scope CurrentUser RemoteSigned
```

### "ChromaDB not initialised"
Your vector store is stale or corrupt. Nuke and re-index:
```bash
mv chroma_db chroma_db.broken.$(date +%s)
./run_larry.sh          # will re-index on next startup
```

### USB runs but super slow
Expected. USB-2 is 40 MB/s write; Chroma / SQLite do thousands of random writes. Copy to internal SSD:
```bash
cp -r /media/$USER/LocalLarry-/Agent-Larry ~/Documents/
```

### GPU not detected (Docker, Ubuntu)
```bash
# Verify NVIDIA toolkit
sudo apt install -y nvidia-container-toolkit
sudo systemctl restart docker
docker run --rm --gpus all nvidia/cuda:12.3.0-base-ubuntu22.04 nvidia-smi
```
Then uncomment the `deploy.resources` block in `docker-compose.yml`.

### Telegram bot crashes on startup
Known issue. The systemd service under pyenv 3.12 segfaults — shelved for now. Run manually instead:
```bash
./run_larry.sh telegram
```

### RAG gives wildly off-topic answers
Already mitigated (threshold 0.78, final_k=2, 300-char cap). If it still happens, you have stale indexed content. Rebuild:
```bash
rm -rf chroma_db/
./run_larry.sh   # agent_v2 will re-index on boot
```

---

## 12. File Manifest

Portable deploy (what ships in the USB + Docker image) — **178 files / ~4 MB** after filtering:

```
✓ *.py              (68 Python source files)
✓ mcp_servers/      (native MCP implementations)
✓ mcp.json
✓ larry_config.json
✓ .env / .env.example
✓ requirements*.txt
✓ run_larry.sh / run_larry.bat
✓ Dockerfile / docker-compose.yml
✓ DEPLOY.md (this file)
✓ README.md
```

**Excluded** (generated at runtime or too large for USB):
```
✗ .venv/            (regenerate with pip install -r requirements.txt)
✗ chroma_db/        (115 GB — rebuilt by /rag reindex)
✗ .git/
✗ __pycache__/
✗ logs/             (41 MB)
✗ sandbox/
✗ opt/Binance/      (596 MB)
✗ REFACTORclaude*/  (stale duplicates)
✗ security_reports/
```

---

## Quick Reference — Paste-ready commands

### Ubuntu first-time setup (one-liner)
```bash
curl -fsSL https://ollama.com/install.sh | sh && \
sudo apt install -y python3.12-venv build-essential libnss3 libgbm1 && \
cd ~/Documents/Agent-Larry && python3.12 -m venv .venv && \
source .venv/bin/activate && pip install -r requirements.txt && \
playwright install chromium && \
ollama pull qwen3-coder:30b && ollama pull nomic-embed-text && \
./run_larry.sh
```

### macOS M1 first-time setup (one-liner)
```bash
brew install python@3.12 ollama && brew services start ollama && \
cd ~/Documents/Agent-Larry && /opt/homebrew/bin/python3.12 -m venv .venv && \
source .venv/bin/activate && pip install -r requirements.txt && \
playwright install chromium && \
ollama pull llama3.2:1b && ollama pull qwen2.5-coder:1.5b && ollama pull nomic-embed-text && \
./run_larry.sh
```

### Windows 11 first-time setup (PowerShell)
```powershell
# Assumes python.org Python 3.12 + Ollama installer already run
cd $HOME\Documents\Agent-Larry
py -3.12 -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
playwright install chromium
ollama pull llama3.2:3b
ollama pull qwen2.5-coder:3b
ollama pull nomic-embed-text
.\run_larry.bat
```

### Docker (any Linux / WSL2)
```bash
docker compose build && \
docker compose up -d ollama && \
docker compose exec ollama ollama pull llama3.2:3b && \
docker compose exec ollama ollama pull nomic-embed-text && \
docker compose run --rm -it agent
```

---

**End of guide.** Updates to this document go in the same file — don't create DEPLOY_v2.md, edit in place.
