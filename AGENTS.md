# AGENTS.md — AI Agent Operating Guide & System Specifications

This document serves as the authoritative operational manual, architecture guide, and behavioral specification for any AI agent (Antigravity, Cursor, Windsurf, Claude Code, GitHub Copilot Workspace, Devin, etc.) working on the **Ryoku Cloud Gaming** repository.

---

## 1. System Mission & Core Constraints

Ryoku Cloud Gaming is a headless, self-hosted cloud gaming infrastructure running on Arch Linux / CachyOS with an NVIDIA GeForce RTX 4060 GPU. It provides zero-install, in-browser gaming via WebCodecs/WASM alongside native Moonlight streaming.

### Non-Negotiable Operational Constraints

1. **Zero Host Desktop Exposure**:
   * Never expose the host operating system's desktop environment, wallpaper, taskbars, terminal sessions, or personal files.
   * Games and launchers must run strictly inside isolated containerized Wayland display sessions managed by Wolf.
2. **Anti-Tamper Master Storage (`:ro`)**:
   * Master game files in `data/shared_games` must **always** be mounted **Read-Only (`:ro`)** into all containers.
   * Containers must never have write access to shared game libraries.
3. **Per-User Isolation (`:rw`)**:
   * Savegames, login tokens (Steam, Heroic, Epic, GOG), and Wine/Proton prefixes belong strictly in the isolated `ryoku-user-storage` volume.
4. **Zero AI Emojis Policy**:
   * Do not generate AI-style emojis (e.g., rocket, sparkle, fire, robot) in commit messages, user messages, documentation, or code comments.

---

## 2. Infrastructure Architecture & Service Topology

```text
+-----------------------------------------------------------------------------------------+
|                                    CLIENT ACCESS                                        |
|  Browser Client (WebCodecs/WASM)               Native Moonlight Client (PC / TV / Phone)|
+-----------------------------------+-----------------------------------------------------+
                                    |
                                    v
+-----------------------------------------------------------------------------------------+
|                                   INGRESS LAYER                                         |
|  Cloudflare Tunnel (cloudflared)  OR  Direct Router DMZ / Port Forward (80/443)         |
+-----------------------------------+-----------------------------------------------------+
                                    |
                                    v
+-----------------------------------------------------------------------------------------+
|                              EDGE REVERSE PROXY (Caddy)                                 |
|  Container: ryoku-gateway                                                               |
|  - Root (/): Custom Branded Dark-Mode Portal (web/index.html)                           |
|  - Health (/api/health): JSON Edge Status Responder                                     |
|  - Stream (/stream*, /ws*, /assets/*): Proxied to Moonlight Web (:8080)                 |
+-----------------------------------+-----------------------------------------------------+
                                    |
                                    v
+-----------------------------------------------------------------------------------------+
|                          STREAMING ENGINE LAYER (Host Network)                          |
|                                                                                         |
|  Moonlight Web (ryoku-moonlight-web)        Wolf GameStream Server (ryoku-cloud-server) |
|  - In-browser WebCodecs client              - NVENC H.264/HEVC encoder                  |
|  - Port: 8080                               - Host ports: 47984, 47989, 48010, UDP      |
|                                             - Controls Docker via /var/run/docker.sock  |
+---------------------------------------------+-------------------------------------------+
                                              | Spawns on demand
                                              v
+-----------------------------------------------------------------------------------------+
|                               ON-DEMAND GAME CONTAINERS                                 |
|  - Steam Cloud (ghcr.io/games-on-whales/steam:edge)                                     |
|  - Heroic Games Launcher (ghcr.io/games-on-whales/heroic-games-launcher:edge)           |
|  Mounts:                                                                                |
|    - data/shared_games:/shared_games:ro (Read-Only Game Files)                           |
|    - ryoku-user-storage:/home/retro:rw   (Isolated User Saves & Configs)                 |
+-----------------------------------------------------------------------------------------+
```

---

## 3. Repository File Organization

| Path | Purpose |
| :--- | :--- |
| `docker-compose.yml` | Master container orchestration (Wolf, Moonlight Web, Caddy gateway). |
| `Caddyfile` | Reverse proxy routing, header manipulation, and static portal asset serving. |
| `autostart.sh` | Main lifecycle script (`start`, `stop`, `restart`, `status`, `check-ip`). |
| `web/` | Custom branded dark-mode portal files (`index.html`, `portal.css`, `portal.js`). |
| `wolf/config/` | Games on Whales configuration files (`config.toml`, app definitions). |
| `deploy/` | Deployment configs including `cloudflared-config.yml` and provisioning scripts. |
| `data/shared_games/` | Master shared game library root (mounted `:ro`). |

---

## 4. Hard-Won Technical Knowledge & Pitfalls

Agents modifying this repository must respect the following known failure modes:

### A. Moonlight Web WebSocket 403 Forbidden
* **Problem**: Moonlight Web validates `normalizeAuthority(Origin) == normalizeAuthority(Host)`. If Caddy proxies to `localhost:8080` while retaining `Origin: https://play.vanshdev.online`, the Go/C++ backend rejects the WebSocket upgrade with `403 Forbidden` ("all transport modes failed").
* **Requirement**: In `Caddyfile`, all reverse proxy blocks targeting `localhost:8080` must explicitly set:
  ```caddy
  header_up Host localhost:8080
  header_up Origin http://localhost:8080
  header_down -X-Frame-Options
  header_down -Content-Security-Policy
  ```

### B. Steam Container Crash on Missing `/tmp/.X11-unix`
* **Problem**: The upstream `steam:edge` image defines `XDG_RUNTIME_DIR=/tmp/.X11-unix`. Container init script `/etc/cont-init.d/10-setup_user.sh` runs `chown -R retro:retro $XDG_RUNTIME_DIR`. Because the folder does not exist, `set -e` causes the container to immediately crash with exit code 1.
* **Requirement**: App definitions in Wolf's config (`wolf/config/cfg/config.toml`) must pass:
  ```toml
  env = [
      "XDG_RUNTIME_DIR=/tmp"
  ]
  ```

### C. Multi-Architecture Manifest Stalls on GHCR
* **Problem**: Running `docker pull ghcr.io/games-on-whales/steam:edge` frequently hangs indefinitely because the Docker daemon stalls on `unknown/unknown` multi-arch attestation manifests.
* **Requirement**: Pull specifically by amd64 digest and re-tag:
  ```bash
  # Steam Edge
  docker pull ghcr.io/games-on-whales/steam@sha256:5a2db53cf9ea5d6022b3adb8338a9711c7192225e40f9c61dee5608823dce8fc
  docker tag ghcr.io/games-on-whales/steam@sha256:5a2db53cf9ea5d6022b3adb8338a9711c7192225e40f9c61dee5608823dce8fc ghcr.io/games-on-whales/steam:edge

  # Heroic Edge
  docker pull ghcr.io/games-on-whales/heroic-games-launcher@sha256:35f691df044acb051d81bd7a3ecb43e947409a69eeb885d6b84f6fcf14d61824
  docker tag ghcr.io/games-on-whales/heroic-games-launcher@sha256:35f691df044acb051d81bd7a3ecb43e947409a69eeb885d6b84f6fcf14d61824 ghcr.io/games-on-whales/heroic-games-launcher:edge
  ```

### D. User Storage Volume Permissions
* **Problem**: Containers execute games under unprivileged user `retro` (UID 1000). If Docker volume `ryoku-user-storage` is owned by `root:root`, Steam cannot write its configuration files and fails silently.
* **Requirement**: Permission normalization is automated in `autostart.sh` before stack launch:
  ```bash
  docker run --rm -v ryoku-user-storage:/home/retro alpine sh -c "chmod -R 777 /home/retro"
  ```

### E. Dynamic IP vs Cloudflare Tunnel Ingress
* **Direct DMZ Mode**: Requires an `A` record in Cloudflare pointing to the active WAN IP. When the router restarts, the ISP reassigns the IP, requiring an update to the DNS record. Local LAN clients must access `http://192.168.1.5` if the router lacks NAT loopback.
* **Cloudflare Tunnel Mode (Preferred)**: Uses systemd unit `ryoku-cloudflare-tunnel.service`. Routes outbound through Cloudflare Edge, meaning dynamic IP changes and NAT loopback limitations do not break external or local access.

---

## 5. Systemd Services & Headless Boot

| Service Unit | Scope | Role |
| :--- | :--- | :--- |
| `ryoku-cloud-gaming.service` | User (`~/.config/systemd/user/`) | Runs `./autostart.sh start` on system boot. Linger is enabled (`loginctl enable-linger vansh`) so it runs headlessly without graphical login. |
| `ryoku-cloudflare-tunnel.service` | System (`/etc/systemd/system/`) | Maintains persistent outbound Cloudflare Tunnel connection (`vansh-cloud-gaming`). |

---

## 6. Standard Agent Development Workflows

### Checking Service Health
```bash
# Full health check via autostart controller
./autostart.sh status

# Verify Docker container status
docker compose ps

# Test local HTTP health endpoint
curl -s http://127.0.0.1:80/api/health
```

### Applying Web Portal Changes (`web/`)
Portal files (`index.html`, `portal.css`, `portal.js`) are bind-mounted into `ryoku-gateway`.
```bash
# Verify Caddyfile syntax and hot-reload without dropping connections
docker exec ryoku-gateway caddy reload --config /etc/caddy/Caddyfile
```

### Modifying Wolf Configuration (`wolf/config/`)
```bash
# Restart Wolf after modifying config.toml or adding new game launch configs
docker restart ryoku-cloud-server
```

### Inspecting Streaming Logs
```bash
# Gateway access & WebSocket upgrade logs
docker logs ryoku-gateway --tail 50 -f

# Wolf streaming & container spawning logs
docker logs ryoku-cloud-server --tail 50 -f

# Moonlight Web client logs
docker logs ryoku-moonlight-web --tail 50 -f
```

---

## 7. Rules for Code & Configuration Changes

1. **Do not disrupt active game sessions** unless the user explicitly requests a restart.
2. **Never commit secrets** (API tokens, Cloudflare credentials, private keys) to git. Keep secrets in `.env` or `~/.cloudflared/`.
3. **Preserve vanilla web standards**: Keep the web portal lightweight, responsive, and dependency-free (vanilla HTML/CSS/JS) to ensure instant loading across mobile and desktop browsers.
4. **Always verify syntax** before restarting production containers (e.g., test Caddyfile formatting, TOML syntax, and shell script exit codes).

