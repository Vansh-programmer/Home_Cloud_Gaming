# Ryoku Cloud Gaming — Project Plan & Architecture Blueprint

This document defines the architecture, design decisions, and phased development roadmap for the personal browser-based cloud gaming system.

---

## 1. Vision & Core Principles

The goal of this project is to create a personal cloud gaming website that feels like a polished, commercial product (similar to GeForce NOW or Xbox Cloud Gaming) while running on a single home gaming PC.

### The Most Important Rule
**Strict Per-Session Isolation:**
- When a user starts a game, they interact **only** with that game window.
- Users must **never** see or reach the host PC's desktop, taskbar, files (`/home`), terminal, other applications, or other users' sessions.
- Each play session runs inside an unprivileged, ephemeral container environment that is completely wiped and deleted when the session ends.
- **No unsafe shortcuts:** No privileged containers, no mounting the host's `/home`, `/tmp/.X11-unix/X0`, `/run/user/1000`, `/dev/input`, or `/dev/snd`.

### Key Product Requirements
1. **Invite-Only Authentication**: Private login with user accounts managed by the admin; no open public registration.
2. **Game Library**: Visual library of Steam games with cover art, search, and a single "Play" button.
3. **Steam Security & Privacy**: Steam credentials are entered strictly into Steam's own login interface inside the stream. The website never sees or stores Steam passwords. Session tokens persist per user.
4. **Browser Play**: Low-latency video/audio streaming with support for Keyboard, Mouse (with Pointer Lock), Controllers (W3C Gamepad API), Mobile Touch Controls, Fullscreen, and a real-time Stats Overlay (FPS, RTT latency, bitrate).
5. **Session Progress Screen**: Clear states: `starting` → `ready` → `playing` → `ended` with friendly error recovery.
6. **Persistence**: Game saves and user-specific Steam data persist between sessions in isolated per-user directories.
7. **Safety Limits**: Strict limit of 1 active gaming session on the PC at a time, idle timeout detection, and admin force-termination.
8. **Admin Dashboard**: Live active session monitoring, force-end control, real-time GPU load/VRAM/temperature telemetry, user management, and session history logs.
9. **External Access & Offline Status**: Works over HTTPS on your domain from outside the home network; displays an accurate "Gaming PC is offline" status page when the gaming PC is powered off (via Cloudflare Tunnel + Cloudflare Worker/Pages fallback).

---

## 2. Technical Stack & Architecture

```
                                  +---------------------------------------+
                                  |            Remote Client              |
                                  |  (Desktop / Laptop / Mobile / Tablet) |
                                  +-------------------+-------------------+
                                                      |
                                          HTTPS / WSS / WebRTC
                                                      |
                                  +-------------------v-------------------+
                                  |   Cloudflare Tunnel + Edge Worker     |
                                  |  (Domain HTTPS + Offline Status Page) |
                                  +-------------------+-------------------+
                                                      |
+-----------------------------------------------------v------------------------------------------------------+
| HOST GAMING PC (Linux / CachyOS / RTX 4060)                                                                |
|                                                                                                            |
|  +------------------------------------------------------------------------------------------------------+  |
|  | Web Backend & Orchestrator (Node.js/Fastify or Go + SQLite)                                          |  |
|  | - Invite-Only Auth, Session FSM, Idle Timers, 1-Session Lock, NVML Telemetry, Admin API              |  |
|  +---------------------------------------------------+--------------------------------------------------+  |
|                                                      | Spawns & Destroys                                   |
|                                                      v                                                     |
|  +------------------------------------------------------------------------------------------------------+  |
|  | Unprivileged Ephemeral Sandbox (Bubblewrap / bwrap)                                                  |  |
|  |   Flags: --unshare-user --unshare-pid --unshare-ipc --unshare-uts --die-with-parent --clearenv        |  |
|  |   Mounts: Fresh tmpfs on /tmp, /run, /var, /home; read-only /usr; GPU nodes: /dev/dri, /dev/nvidia*   |  |
|  |                                                                                                      |  |
|  |   +---------------------------------+  +---------------------------------+                           |  |
|  |   | Headless Kiosk Compositor       |  | Isolated Audio Subsystem        |                           |  |
|  |   | - weston --backend=headless     |  | - pipewire + wireplumber        |                           |  |
|  |   | - Xwayland (single window)      |  | - pipewire-pulse null-sink      |                           |  |
|  |   | - gamescope (scaled kiosk)      |  |   ("cloud_sink", no host audio) |                           |  |
|  |   +----------------+----------------+  +----------------+----------------+                           |  |
|  |                    |                                    |                                            |  |
|  |                    +------------------+  +--------------+                                            |  |
|  |                                       |  |                                                           |  |
|  |                                       v  v                                                           |  |
|  |   +----------------------------------------------------------------------------------------------+   |  |
|  |   | Hardware-Accelerated GStreamer WebRTC Pipeline                                               |   |  |
|  |   | - Video: ximagesrc -> nvh264enc (NVIDIA RTX 4060 NVENC, low-latency CBR) -> webrtcbin         |   |  |
|  |   | - Audio: pulsesrc (cloud_sink.monitor) -> opusenc (Opus stereo 48kHz) -> webrtcbin           |   |  |
|  |   | - DataChannel: low-latency input packets (keys, mouse deltas, gamepad state, latency ping)   |   |  |
|  |   +----------------------------------------------------------------------------------------------+   |  |
|  |                                                   ^                                                  |  |
|  |                                                   | Injects inputs via libXtst                       |  |
|  |   +-----------------------------------------------+----------------------------------------------+   |  |
|  |   | Isolated Target Game Process                                                                 |   |  |
|  |   | - Steam GamepadUI / Direct Steam AppID launch / Proton                                       |   |  |
|  |   | - Isolated Steam login & save data mounted via per-user directory                            |   |  |
|  |   +----------------------------------------------------------------------------------------------+   |  |
|  +------------------------------------------------------------------------------------------------------+  |
+------------------------------------------------------------------------------------------------------------+
```

---

## 3. Storage & Isolation Design

### Disk Strategy (176 GB Available Space)
To avoid duplicating large 50+ GB game installs across users:
- **Shared Base Game Library (`/data/steam_shared`)**: Mounted **read-only** (`:ro`) into the container.
- **Per-User Writable Overlays & Saves (`/data/users/<user_id>/`)**:
  - `steam_profile/`: Steam login state and tokens (remembered per user).
  - `compatdata/`: User-specific Wine/Proton prefixes and configuration.
  - `saves/`: Game save directories.
- **Ephemeral Sandbox Root**: Everything else (logs, caches, browser files, temp sockets) lives on `tmpfs` and is discarded on exit.

---

## 4. Phased Implementation Roadmap

### Phase 1: Isolated Single-Game WebRTC Prototype
**Status: COMPLETED (Verified with Automated Tests)**
- [x] Unprivileged Bubblewrap sandbox configuration (`engine/sandbox.py`) with zero host filesystem or socket leakage.
- [x] Headless single-application display environment (`weston` kiosk + `Xwayland`).
- [x] Isolated audio subsystem (`pipewire` + `wireplumber` + `pipewire-pulse` with `cloud_sink`).
- [x] Hardware-accelerated GStreamer WebRTC streaming pipeline (`nvh264enc` on NVIDIA RTX 4060 + `opusenc`).
- [x] Low-latency input engine (`engine/input_manager.py`) supporting Keyboard, Mouse (relative & absolute), Gamepad, and Mobile Touch.
- [x] Dynamic NVENC quality preset switching (4 Mbps to 25 Mbps).
- [x] 60 FPS 3D native test game (`CyberArena 3D`) with procedural synth audio and HUD telemetry.
- [x] Browser player UI (`web/prototype.html`) with real-time stats overlay, pointer lock, mobile touch pad, and auto-reconnect.
- [x] Automated test suite (`tests/test_phase1.py`) validating security invariants, WebRTC signaling, quality adjustments, input injection, and clean container destruction.

---

### Phase 2: Steam Integration & Per-User Persistent Storage
**Status: COMPLETED (Verified with Automated Tests)**
- [x] Configure headless Steam runtime inside container using `/usr/bin/steam -gamepadui` (`--app-id 7`) or direct AppID launch (`steam -gamepadui -applaunch <AppID>`).
- [x] Configure per-user persistent directories (`engine/storage_manager.py`) for Steam authentication tokens (`config/loginusers.vdf`, `config/config.vdf`, `userdata/`), Proton prefixes (`compatdata`), and save games (`$XDG_DATA_HOME`).
- [x] Ensure shared game files (`data/shared_steam_library`) are mounted strictly read-only (`:ro` at `/steam_shared`) while user-generated writes route to the user's persistent directories.
- [x] Implement Steam login flow inside the stream: users type passwords directly into Steam's authentic UI using normal cursor/keyboard mode; the website backend never intercepts or stores credentials.
- [x] Verify save file persistence across container destruction and restarts for multiple distinct user accounts (`tests/test_phase2.py`).

---

### Phase 3: Backend Orchestrator, Safety Limits & Auth
**Status: COMPLETED (Verified with Automated Tests)**
- [x] Central backend service (`backend/server.py` & `backend/orchestrator.py`) with SQLite database (`backend/database.py` using WAL mode).
- [x] Invite-only user authentication (admin-generated single-use invite codes `RYOKU-XXXX-XXXXXX`, salted PBKDF2-HMAC-SHA256 password hashing with constant-time verification, `HttpOnly` session cookies).
- [x] Concurrency lock: enforce strictly 1 active game session on the server (`409 Conflict` with `"Gaming PC is currently in use by <user>"` for other users).
- [x] Session State Machine: `starting` → `ready` → `playing` → `ended` with friendly stage and end-reason messages.
- [x] Idle timeout detection: terminate sessions automatically after configurable inactivity (default 10 minutes, tested at 2.2s in `tests/test_phase3.py`).
- [x] Tab refresh / network disconnect tolerance: keep session alive during the reconnect grace window (default 5 minutes) if the browser disconnects, allowing instant seamless reconnection to the running container.
- [x] Admin force-termination (`POST /api/admin/sessions/force-stop`), GPU telemetry (`nvidia-smi`), and session history audit log.

---

### Phase 4: Modern Product Web App & In-Stream HUD
**Status: COMPLETED (Verified with Automated Tests)**
- [x] Responsive web application (`web/index.html`, `web/assets/styles.css`, `web/assets/app.js`) with modern dark glassmorphism styling and desktop/mobile navigation.
- [x] Game Library view: Hero spotlight banner, 600x900 vertical game covers (`/assets/cyberarena-cover.svg`, `/assets/steam-cover.svg`, Steam CDN artwork with automatic offline SVG fallback), instant search, category filter pills, resolution/quality selectors, and "Play" buttons.
- [x] Session loading view: 4-stage visual progress stepper (`1. Ephemeral Bubblewrap Sandbox` → `2. Headless Weston Kiosk & Virtual Audio` → `3. Isolated Game Process & Persistent Saves` → `4. Hardware NVENC WebRTC Stream`).
- [x] Direct Integrated In-Stream floating HUD (no nested iframe):
  - Collapsible floating top HUD bar (`RYOKU HUD ▴ • 60 FPS • Ping ms`) with pointer-lock toggle (`Lock Mouse 3D` vs `UI Cursor`), audio mute, live quality switcher, stats toggle, touch pad toggle, and true fullscreen.
  - Virtual analog thumbstick & touch button overlay (`JUMP`, `FIRE`, `TURN L/R`) for mobile play.
  - Floating diagnostics panel (`RTT latency`, `FPS`, `bitrate`, `packet loss`, `resolution`, `input mode`, `user high score`, `Steam token`, and `Isolation Verified ✓`).

---

### Phase 5: Admin Dashboard & GPU Telemetry
**Status: COMPLETED (Verified with Automated Tests)**
- [x] Admin portal accessible only by the server owner (`role == "admin"`):
  - **Live Session View (`#admin-active-session-box`)**: Shows who is currently playing, game title, resolution/FPS/quality, connection state (`LIVE WEBRTC STREAM` vs `DISCONNECTED` grace window), uptime, idle countdown, and a **"⚡ Force-End Session Now"** emergency button.
  - **GPU & NVENC Telemetry**: Real-time RTX 4060 3D core load %, hardware NVENC encoder utilization %, VRAM usage (MB & %), temperature (°C), power draw (W), rolling 60-sample SVG sparkline chart, plus Host CPU load, RAM usage, and Disk free space.
  - **Runtime Safety Limits (`POST /api/admin/settings`)**: Live adjustment of `idle_timeout_sec` and `disconnect_grace_sec` without restarting the server.
  - **User & Invite Management**: Generate single-use invite codes with notes, copy/revoke codes, add users, suspend/reactivate accounts (immediately force-ending active sessions on suspend), reset passwords, or delete accounts.
  - **Session History Audit Log**: Full historical log of sessions (user, game, quality, duration, end reason) with one-click history clearing (`DELETE /api/admin/history`).

---

### Phase 6: External HTTPS Access, STUN/TURN & PC-Offline Status
**Status: COMPLETED (Verified with Automated Tests)**
- [x] Cloudflare Tunnel (`deploy/cloudflared-config.yml`) configuration for secure external HTTPS/WSS access without exposing home router ports.
- [x] STUN/TURN server configuration (`deploy/turnserver.conf` & `backend/network_manager.py`) with time-limited HMAC-SHA1 TURN REST credentials (`GET /api/webrtc/ice-config`) and GStreamer `turn://` URI formatting for cellular/NAT networks.
- [x] Always-on PC-offline status page (`web/offline.html` & `deploy/cloudflare_worker.js`):
  - Lightweight Cloudflare Edge Worker (`deploy/cloudflare_worker.js`) for your custom domain.
  - Health check ping to `/api/health` on the home gaming PC.
  - When the gaming PC is on, HTTP and WebSocket traffic proxies seamlessly to the home server.
  - When the gaming PC is off (or in maintenance mode), displays the branded "Gaming PC is Currently Powered Off" status page (`web/offline.html`) that automatically reconnects when the PC boots.

---

## 5. Verification Checklist per Phase

| Phase | Core Deliverable | Verification Criteria | Status |
| :---: | :--- | :--- | :---: |
| **1** | Single-Game WebRTC Prototype | Automated tests pass; 60 FPS hardware NVENC stream; zero host desktop/file exposure; container destroyed on game exit. | **Done** |
| **2** | Steam & Persistent Storage | Launch Steam AppID; Steam login preserved across runs; save games persist; user A cannot see user B's saves. | **Done** |
| **3** | Backend, Limits & Auth | Invite-only login works; 1-session GPU lock enforced; idle timeout ends container; tab reconnect resumes game. | **Done** |
| **4** | Polished Web App & HUD | Steam library UI with artwork; in-stream mobile controls; telemetry HUD; responsive mobile experience. | **Done** |
| **5** | Admin Portal & Telemetry | Live GPU stats displayed; admin can force-kill session; user list & session history functional. | **Done** |
| **6** | Domain HTTPS & Offline Page | External access over custom domain; cellular playback via TURN; offline fallback page when PC is off. | **Done** |

