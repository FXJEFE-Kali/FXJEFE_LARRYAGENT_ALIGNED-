# System Hardening Log
**Date:** 2026-03-13

---

## Services Disabled

| Service | Port | Reason |
|---------|------|--------|
| SSH (`sshd` + `ssh.socket`) | 22 | Not needed — local machine only |
| nginx | 80 | Default page only, no real config |
| CUPS | 631 | No printer in use |

```bash
sudo systemctl disable --now ssh ssh.socket
sudo systemctl disable --now nginx
sudo systemctl disable --now cups cups-browsed
```

---

## Ollama — Restricted to Localhost

**Before:** `OLLAMA_HOST=0.0.0.0` in both service file and override — all 23 models exposed on every interface with no auth.

**After:** `OLLAMA_HOST=127.0.0.1:11434` in both files.

Files changed:
- `/etc/systemd/system/ollama.service`
- `/etc/systemd/system/ollama.service.d/override.conf`

```bash
sudo systemctl daemon-reload && sudo systemctl restart ollama
```

Verified: `ss -tlnp | grep 11434` → `127.0.0.1:11434` only.

---

## Open WebUI Docker — Restricted to Localhost

**Before:** `0.0.0.0:3000 → container:8080` — reachable from any interface.

**After:** `127.0.0.1:3000 → container:8080` — localhost only.

```bash
sudo docker stop open-webui && sudo docker rm open-webui
sudo docker run -d \
  --name open-webui \
  --restart always \
  -p 127.0.0.1:3000:8080 \
  -v open-webui:/app/backend/data \
  ghcr.io/open-webui/open-webui:main
```

Verified: `docker inspect open-webui --format '{{json .HostConfig.PortBindings}}'`
→ `{"8080/tcp":[{"HostIp":"127.0.0.1","HostPort":"3000"}]}`

---

## UFW — Removed Stale SSH Rules

**Before:** Four SSH rules remaining after SSH was disabled — port 22 would be open again if SSH ever restarted.

**After:** All SSH rules removed. Also removed now-redundant Ollama LAN rule (Ollama is localhost-only).

Rules removed:
- `22/tcp ALLOW Anywhere` (SSH jump host)
- `OpenSSH ALLOW Anywhere`
- `22/tcp (v6) ALLOW Anywhere`
- `OpenSSH (v6) ALLOW Anywhere`
- `11434 ALLOW 192.168.1.0/24` (redundant — Ollama now localhost only)

**Remaining UFW rules:**
```
[ 1] 8080/tcp   ALLOW IN   192.168.0.0/16   # Open WebUI LAN
[ 2] 8080/tcp   ALLOW IN   10.0.0.0/8       # Open WebUI LAN
[ 3] 8080/tcp   ALLOW IN   172.16.0.0/12    # Open WebUI LAN
[ 4] Anywhere   ALLOW IN   127.0.0.1
[ 5] 127.0.0.1  ALLOW IN   Anywhere
```

---

## Werkzeug Version Banner — Hidden

**File:** `Agent-Larry/dashboard_hub.py`

**Before:** Every HTTP response on port 8000 sent `Server: Werkzeug/3.1.6 Python/3.12.7`.

**After:** Banner suppressed by overriding `WSGIRequestHandler.server_version` and `sys_version` to empty strings.

```python
import werkzeug.serving
werkzeug.serving.WSGIRequestHandler.server_version = ""
werkzeug.serving.WSGIRequestHandler.sys_version = ""
```

**Note:** Requires restart of `dashboard_hub.py` (pid 7403) to take effect.

---

## Final Port State

| Port | Service | Binding | Status |
|------|---------|---------|--------|
| 3000 | Open WebUI (Docker) | `127.0.0.1` | Restricted ✓ |
| 8000 | dashboard_hub (Werkzeug) | `127.0.0.1` | Local only ✓ |
| 8080 | open-webui (standalone) | `0.0.0.0` | LAN only via UFW |
| 11434 | Ollama | `127.0.0.1` | Restricted ✓ |
| 18789-18792 | openclaw-gateway | `127.0.0.1` | Local only ✓ |

---

## Pending

- [ ] Restart `dashboard_hub.py` to activate Werkzeug banner suppression
- [ ] Investigate standalone `open-webui` on port 8080 (pid 4056) — restrict to localhost if LAN access not needed
