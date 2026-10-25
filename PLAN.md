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
**Status: UP NEXT**
- [ ] Install / configure headless Steam runtime inside container using `gamescope -e -- /usr/bin/steam -tenfoot` or direct AppID launch (`steam -applaunch <AppID>`).
- [ ] Configure per-user persistent directories for Steam authentication credentials (`config/config.vdf`, `ssfn*` files), Proton prefixes (`compatdata`), and save games.
- [ ] Ensure shared game files are mounted read-only while user-generated writes route to the user's upper directory.
- [ ] Implement Steam login flow inside the stream: users type passwords directly into Steam's authentic UI; the website backend never intercepts or stores credentials.
- [ ] Verify save file persistence across container destruction and restarts for multiple distinct user accounts.

---

### Phase 3: Backend Orchestrator, Safety Limits & Auth
**Status: PLANNED**
- [ ] Central backend service (Node.js/Fastify or Go) with SQLite database (`better-sqlite3` or `sqlc`).
- [ ] Invite-only user authentication (admin-generated invite tokens, salted password hashing with Argon2/bcrypt, secure session cookies).
- [ ] Concurrency lock: enforce exactly 1 active game session on the server; return friendly "Server in use by [User]" status to others.
- [ ] Session State Machine: `starting` → `ready` → `playing` → `ended`.
- [ ] Idle timeout detection: terminate sessions automatically after configurable inactivity (e.g., 10 minutes without input).
- [ ] Tab refresh / network disconnect tolerance: keep session alive for 5 minutes if browser disconnects, allowing instant seamless reconnection.

---

### Phase 4: Modern Product Web App & In-Stream HUD
**Status: PLANNED**
- [ ] Responsive web application (Next.js / React + Tailwind CSS) with modern styling (dark mode, glassmorphism, responsive navigation).
- [ ] Game Library view: Steam game covers, search, filtering, and "Play" buttons.
- [ ] Session loading view: smooth progress bar, stage indicators (`Starting Sandbox` → `Configuring Display` → `Launching Game`).
- [ ] In-Stream floating HUD:
  - Collapsible control bar (fullscreen, audio volume, stats toggle, quality preset selector).
  - Virtual gamepad / touch overlay customized for mobile portrait/landscape orientations.
  - Floating diagnostics panel (RTT latency, FPS counter, bitrate, packet loss, resolution).

---

### Phase 5: Admin Dashboard & GPU Telemetry
**Status: PLANNED**
- [ ] Admin portal accessible only by the server owner:
  - **Live Session View**: Who is currently playing, which game, connection duration, and a "Force End Session" emergency button.
  - **GPU Telemetry**: Real-time GPU load %, VRAM usage, temperature (°C), and encoder utilization via `nvidia-smi` / `NVML`.
  - **User Management**: Create invite codes, list users, reset passwords, deactivate or delete accounts.
  - **Session History**: Historical log of sessions (user, game, duration, start/end timestamps).

---

### Phase 6: External HTTPS Access, STUN/TURN & PC-Offline Status
**Status: PLANNED**
- [ ] Cloudflare Tunnel (`cloudflared`) configuration for secure external access without port forwarding.
- [ ] STUN/TURN server configuration (`coturn`) to guarantee WebRTC connection traversal across strict cellular/NAT networks.
- [ ] Always-on PC-offline status page:
  - Lightweight Cloudflare Worker / Cloudflare Pages frontend hosted on your domain.
  - Health check ping to the home gaming PC.
  - When the gaming PC is on, traffic proxies seamlessly to the home server.
  - When the gaming PC is off, displays a clean "Gaming PC is Offline" status with estimated availability.

---

## 5. Verification Checklist per Phase

| Phase | Core Deliverable | Verification Criteria | Status |
| :---: | :--- | :--- | :---: |
| **1** | Single-Game WebRTC Prototype | Automated tests pass; 60 FPS hardware NVENC stream; zero host desktop/file exposure; container destroyed on game exit. | **Done** |
| **2** | Steam & Persistent Storage | Launch Steam AppID; Steam login preserved across runs; save games persist; user A cannot see user B's saves. | Next |
| **3** | Backend, Limits & Auth | Invite-only login works; 1-session GPU lock enforced; idle timeout ends container; tab reconnect resumes game. | Queued |
| **4** | Polished Web App & HUD | Steam library UI with artwork; in-stream mobile controls; telemetry HUD; responsive mobile experience. | Queued |
| **5** | Admin Portal & Telemetry | Live GPU stats displayed; admin can force-kill session; user list & session history functional. | Queued |
| **6** | Domain HTTPS & Offline Page | External access over custom domain; cellular playback via TURN; offline fallback page when PC is off. | Queued |

