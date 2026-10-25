# Ryoku Cloud Gaming — Complete End-to-End Workflow & Anywhere Deployment Guide

This document explains:
1. **How the Entire System Works End-to-End** (Architecture, Security Isolation, WebRTC Pipeline, Input Injection, Storage, and Session Lifecycle).
2. **How to Deploy & Run This Project Anywhere** (Local PC, New Linux PC, Custom Domain `play.vanshdev.online` & `vanshdev.online/cloudgaming`, Cloudflare Tunnel, Always-On Offline Page, and Auto-Start on Boot).

---

## Part 1: How It Works — Complete End-to-End Workflow

### 1. High-Level Request & Media Flow

```
[Player Browser (Desktop / Phone / Tablet)]
       │
       │ 1. Opens https://vanshdev.online/cloudgaming (or https://play.vanshdev.online)
       ▼
[Cloudflare Edge Worker (deploy/cloudflare_worker.js)]
       ├──► If Gaming PC is OFF (502/503/530):
       │      Serves "Gaming PC is Currently Powered Off" page (auto-polls /api/health every 5s)
       │
       └──► If Gaming PC is ON:
              Forwards HTTPS & WebSocket (/ws) through Cloudflare Tunnel (`cloudflared`)
              │
              ▼
[Host Gaming PC — Backend Orchestrator (backend/server.py + backend/orchestrator.py)]
  (Listens on 127.0.0.1:8080 / 0.0.0.0:8080)
       │
       ├─► Step A: Authenticates user via SQLite WAL DB (`data/cloud_gaming.db`)
       │           (Invite-only accounts, PBKDF2-HMAC-SHA256 hashes, HttpOnly + Secure cookies)
       ├─► Step B: Checks Single-Session GPU Lock (1 active session on the PC at a time)
       ├─► Step C: Prepares User Storage (`engine/storage_manager.py`)
       │           - Shared Steam library (`data/shared_steam_library`) -> mounted READ-ONLY (:ro)
       │           - User's personal folder (`data/users/<username>/home/`) -> mounted WRITABLE (:rw)
       └─► Step D: Spawns Ephemeral Bubblewrap Sandbox (`engine/launch_phase2.py` -> `bwrap`)
              │
              ▼
[Isolated Ephemeral Container (`/tmp/cloudgaming-session-<id>`)]
  (Unshared User, PID, IPC, UTS, Cgroup namespaces; --clearenv; --die-with-parent)
       │
       ├─► 1. Private D-Bus + PipeWire + WirePlumber + PipeWire-Pulse (`cloud_sink` virtual audio)
       ├─► 2. Headless Weston Wayland Compositor (`--backend=headless --renderer=gl --shell=kiosk`)
       ├─► 3. Isolated Xwayland Display (`:90+`) + Single-Window Fullscreen Kiosk Enforcer (`libX11`)
       ├─► 4. Target Game Process (`CyberArena 3D`, `Steam Big Picture`, or `steam -applaunch <AppID>`)
       └─► 5. GStreamer WebRTC Engine (`engine/webrtc_streamer.py` on 127.0.0.1:<internal_port>)
              ├─► Video: `ximagesrc` -> NVIDIA RTX 4060 `nvh264enc` (or `x264enc`) -> `webrtcbin`
              ├─► Audio: `pulsesrc (cloud_sink.monitor)` -> `opusenc` (48kHz stereo) -> `webrtcbin`
              └─► Input: Browser `RTCDataChannel` -> `libXtst` X11 injection (`engine/input_manager.py`)
```

---

### 2. Step-by-Step Lifecycle of a Play Session

#### Stage 1: Authentication & Invite-Only Access ([`backend/database.py`](file:///home/vansh/Projects/Home_Cloud_Gaming/backend/database.py))
- Public sign-up is disabled (`403 Forbidden`).
- Only the admin (`vansh`) can generate single-use invite codes (`RYOKU-XXXX-XXXXXX`) from the **Admin Console** or CLI.
- When a friend redeems an invite code, the backend creates their account in `data/cloud_gaming.db` and initializes their private persistent directory at `data/users/<username>/home/`.

#### Stage 2: Game Discovery ([`engine/steam_manager.py`](file:///home/vansh/Projects/Home_Cloud_Gaming/engine/steam_manager.py))
- The backend scans `data/shared_steam_library/steamapps/appmanifest_*.acf` to discover installed Steam games automatically (filtering out Proton/Steam Linux Runtime tools).
- It also includes built-in entries:
  - **AppID `0` (`CyberArena 3D`)**: Native 60 FPS OpenGL/SDL2 3D arena game with synth audio and persistent high-score saves.
  - **AppID `7` (`Steam Big Picture`)**: Launches Steam in GamepadUI mode inside the container so users can log into their Steam account directly inside the video stream (the website never sees or stores Steam passwords).

#### Stage 3: Single-Session Lock & Container Spawn ([`backend/orchestrator.py`](file:///home/vansh/Projects/Home_Cloud_Gaming/backend/orchestrator.py))
- When a player clicks **▶ Launch Game**, `SessionOrchestrator.start_or_reconnect_session()` checks the concurrency lock:
  - If **another user** is already playing, it returns HTTP `409 Conflict` (`"Gaming PC is currently in use by <user>"`).
  - If the **same user** already has that game running (e.g., after refreshing the tab or switching from desktop to phone), it **reconnects** to the running container immediately.
  - Otherwise, it picks a free local loopback port (`127.0.0.1:<internal_port>`) and launches [`engine/launch_phase2.py`](file:///home/vansh/Projects/Home_Cloud_Gaming/engine/launch_phase2.py).

#### Stage 4: Strict Ephemeral Sandbox Isolation ([`engine/sandbox.py`](file:///home/vansh/Projects/Home_Cloud_Gaming/engine/sandbox.py))
- `EphemeralSandbox` constructs an unprivileged Bubblewrap (`bwrap`) container:
  - **Blocked from Host**: Host `/home/vansh`, host X11 (`/tmp/.X11-unix/X0`), host Wayland (`/run/user/1000`), physical keyboards/mice (`/dev/input`), and host speakers/microphones (`/dev/snd`) are **never** mounted inside the container.
  - **GPU Device Pass-Through**: Only `/dev/dri` and `/dev/nvidia*` are bound so the game and GStreamer can use the RTX 4060 GPU and NVENC hardware encoder.
  - **Storage Mounts**:
    - `/steam_shared`: Mounted strictly **read-only (`--ro-bind`)** from `data/shared_steam_library`.
    - `/home/gamer/.steam`, `/home/gamer/.local/share`, `/home/gamer/.config`: Mounted **writable (`--bind`)** from `data/users/<username>/home/` so only that user's saves and Steam login tokens persist.
    - `/tmp`, `/run`, `/var`: Fresh RAM-backed `tmpfs` mounts that vanish when the container exits.

#### Stage 5: Headless Display, Virtual Audio & WebRTC Streaming ([`engine/session_runner.py`](file:///home/vansh/Projects/Home_Cloud_Gaming/engine/session_runner.py), [`engine/webrtc_streamer.py`](file:///home/vansh/Projects/Home_Cloud_Gaming/engine/webrtc_streamer.py))
Inside the container, `session_runner.py` boots a self-contained desktop-free graphics and audio stack:
1. **Audio**: Starts a private `dbus-daemon`, `pipewire`, `wireplumber`, and `pipewire-pulse`, creating a virtual null-sink named `cloud_sink`. The game's audio goes into `cloud_sink`, and GStreamer captures `cloud_sink.monitor` into `opusenc`.
2. **Display**: Starts headless `weston --backend=headless --renderer=gl --shell=kiosk` and an isolated `Xwayland` display.
3. **Kiosk Enforcer & Input Injection ([`engine/input_manager.py`](file:///home/vansh/Projects/Home_Cloud_Gaming/engine/input_manager.py))**: Monitors X11 windows via `libX11` to force the game window to fill the exact stream resolution (`1280x720` or `1920x1080`) and injects browser keyboard, mouse (both normal UI cursor and 3D Pointer Lock relative motion), W3C Gamepad, and mobile touch inputs via `libXtst`.
4. **Hardware NVENC WebRTC**: Captures the isolated `Xwayland` display with `ximagesrc`, encodes H.264 on the RTX 4060 via `nvh264enc` (`preset=low-latency-hq zerolatency=true`), and streams video + Opus audio + `RTCDataChannel` directly to the browser.

#### Stage 6: Watchdog, Reconnect Grace & Teardown
- The orchestrator watchdog polls the container every `350ms`:
  - **Game Exit**: If the player quits inside the game (e.g., presses `Escape` or selects *Quit to Desktop* in Steam), the container exits immediately and all `/tmp/cloudgaming-session-*` files are wiped.
  - **Tab Close / Network Drop**: If the browser disconnects, the session enters a **5-minute reconnect grace window** (`READY` paused state) so the player can reload the page and resume without losing progress.
  - **Idle Timeout**: If no keyboard/mouse/gamepad/touch input is received for **10 minutes** (configurable live in the Admin Console), the session is automatically terminated.
  - **Admin Force-Stop**: The admin can click **⚡ Force-End Session Now** in the Admin Console at any time.

---

## Part 2: How to Deploy & Run This Anywhere (Step-by-Step)

### Scenario A: Run Locally or on Your Home Wi-Fi (Any Linux PC)

1. **Install System Dependencies**:
   - **Arch Linux / CachyOS**:
     ```bash
     sudo pacman -Syu --needed \
       python python-pip python-gobject python-aiohttp \
       bubblewrap weston xorg-server-xwayland gamescope \
       pipewire pipewire-pulse wireplumber libpulse \
       gstreamer gst-plugins-base gst-plugins-good gst-plugins-bad gst-plugins-ugly gst-libav libnice \
       libx11 libxtst sdl2 mesa glu gcc pkgconf steam cloudflared coturn
     ```
   - *(For Ubuntu/Debian and Fedora package commands, see [`SETUP_AND_REQUIREMENTS.md`](file:///home/vansh/Projects/Home_Cloud_Gaming/SETUP_AND_REQUIREMENTS.md#L80-L128).)*

2. **Compile the 3D Test Game (if on a new machine)**:
   ```bash
   gcc -O2 engine/test_game/arena3d.c -o engine/test_game/arena3d $(sdl2-config --cflags --libs) -lGL -lGLU -lm
   ```

3. **Start the Server**:
   ```bash
   python3 engine/launch_phase6.py --host 0.0.0.0 --port 8080 --admin-user vansh --admin-password ryoku-admin-2026
   ```
   - Open **`http://localhost:8080`** (or **`http://localhost:8080/cloudgaming`**).

---

### Scenario B: Deploy Globally on Your Domain (`play.vanshdev.online` & `vanshdev.online/cloudgaming`)

Follow these exact steps on **any Linux PC** to connect it to your Cloudflare domain:

#### Step 1: Log In & Set Up the Cloudflare Tunnel on the PC
```bash
# 1. Authenticate cloudflared with your Cloudflare account (select vanshdev.online in browser)
cloudflared tunnel login

# 2. If setting up a brand-new tunnel:
#    cloudflared tunnel create vansh-cloud-gaming
#
#    OR if reusing your existing tunnel (UUID: 43a598d8-3099-49ff-8e65-a28b63cafa05) on this PC,
#    download its credentials JSON file directly from Cloudflare:
mkdir -p ~/.cloudflared
cloudflared tunnel token --cred-file ~/.cloudflared/43a598d8-3099-49ff-8e65-a28b63cafa05.json vansh-cloud-gaming

# 3. Route the subdomain play.vanshdev.online to the tunnel
#    (This leaves your root vanshdev.online DNS record untouched!)
cloudflared tunnel route dns vansh-cloud-gaming play.vanshdev.online
```

#### Step 2: Verify [`deploy/cloudflared-config.yml`](file:///home/vansh/Projects/Home_Cloud_Gaming/deploy/cloudflared-config.yml)
Ensure [`deploy/cloudflared-config.yml`](file:///home/vansh/Projects/Home_Cloud_Gaming/deploy/cloudflared-config.yml) points to your credentials file:
```yaml
tunnel: 43a598d8-3099-49ff-8e65-a28b63cafa05
credentials-file: /home/vansh/.cloudflared/43a598d8-3099-49ff-8e65-a28b63cafa05.json

ingress:
  - hostname: play.vanshdev.online
    service: http://127.0.0.1:8080
    originRequest:
      noTLSVerify: true
      connectTimeout: 5s

  - hostname: vanshdev.online
    path: ^/cloudgaming(/.*)?$
    service: http://127.0.0.1:8080
    originRequest:
      noTLSVerify: true
      connectTimeout: 5s

  - service: http_status:404
```

#### Step 3: Run the Tunnel & Server
- **Terminal 1 (Cloudflare Tunnel)**:
  ```bash
  cd /home/vansh/Projects/Home_Cloud_Gaming
  cloudflared tunnel --config deploy/cloudflared-config.yml run
  ```
- **Terminal 2 (Ryoku Cloud Gaming Server)**:
  ```bash
  cd /home/vansh/Projects/Home_Cloud_Gaming
  python3 engine/launch_phase6.py \
    --host 0.0.0.0 \
    --port 8080 \
    --public-domain vanshdev.online/cloudgaming \
    --admin-user vansh \
    --admin-password ryoku-admin-2026
  ```

#### Step 4: Connect `https://vanshdev.online/cloudgaming` & Always-On Offline Page in Cloudflare Dashboard
Because `vanshdev.online` has its own DNS record for your main website, a **Cloudflare Worker** sits on `vanshdev.online/cloudgaming*` and forwards requests to `play.vanshdev.online` when your PC is on, or serves the **"Gaming PC is Currently Powered Off"** page when your PC is off:

1. Go to [https://dash.cloudflare.com](https://dash.cloudflare.com) → **Workers & Pages** → **Create** → **Create Worker**.
2. Name it **`ryoku-cloud-gaming`** → click **Deploy** → click **Edit code**.
3. Paste the full contents of [`deploy/cloudflare_worker.js`](file:///home/vansh/Projects/Home_Cloud_Gaming/deploy/cloudflare_worker.js) and click **Deploy**.
4. Go to your Worker's **Settings** → **Domains & Routes** → **+ Add** → **Route**:
   - **Zone**: `vanshdev.online`
   - **Route**: `vanshdev.online/cloudgaming*`
   - **Worker**: `ryoku-cloud-gaming`
5. *(Optional)* Add a second route `play.vanshdev.online/*` → `ryoku-cloud-gaming` so both URLs show the offline status page when your PC is powered down.

---

### Scenario C: Run Automatically in the Background on Boot (`systemd`)

If you want both the **Ryoku Cloud Gaming Server** ([`deploy/ryoku-cloud-gaming.service`](file:///home/vansh/Projects/Home_Cloud_Gaming/deploy/ryoku-cloud-gaming.service)) and the **Cloudflare Tunnel** ([`deploy/ryoku-cloudflare-tunnel.service`](file:///home/vansh/Projects/Home_Cloud_Gaming/deploy/ryoku-cloudflare-tunnel.service)) to start automatically whenever you turn on your gaming PC:

```bash
# 1. Copy both service files into /etc/systemd/system/
sudo cp /home/vansh/Projects/Home_Cloud_Gaming/deploy/ryoku-cloud-gaming.service /etc/systemd/system/
sudo cp /home/vansh/Projects/Home_Cloud_Gaming/deploy/ryoku-cloudflare-tunnel.service /etc/systemd/system/

# 2. Reload systemd and enable + start both services on boot
sudo systemctl daemon-reload
sudo systemctl enable --now ryoku-cloud-gaming.service ryoku-cloudflare-tunnel.service

# 3. Verify both are running
sudo systemctl status ryoku-cloud-gaming.service ryoku-cloudflare-tunnel.service
```
To stop or disable them at any time:
```bash
# Stop right now:
sudo systemctl stop ryoku-cloud-gaming.service ryoku-cloudflare-tunnel.service

# Disable auto-start on boot:
sudo systemctl disable ryoku-cloud-gaming.service ryoku-cloudflare-tunnel.service
```

