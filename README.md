# Ryoku Cloud Gaming

A personal browser-based cloud gaming system that turns your Linux gaming PC into a private cloud gaming service. Stream games directly to any desktop or mobile browser over WebRTC with hardware-accelerated video/audio encoding, per-user persistent saves, and low-latency controls.

---

## The Core Security Rule

> **Strict Isolation — Zero Host Access**
> When a user launches a game, they interact **only** with that isolated game. They can never access your PC's desktop, files (`/home`), host applications, audio devices, physical keyboard/mouse devices, or other users' sessions. Each session runs in an unprivileged ephemeral sandbox that is completely destroyed when the session ends.

---

## Current Status: Phases 1 & 2 Completed

### Phase 1: Isolated Single-Game WebRTC Prototype (Completed)
- **Sandbox**: Unprivileged Bubblewrap (`bwrap`) container with isolated PID, IPC, UTS, and user namespaces; ephemeral `tmpfs` mounts for `/tmp`, `/run`, `/var`, `/home`, `/dev/shm`.
- **Kiosk Display**: Headless `weston` compositor + isolated `Xwayland` server running with single-window enforcement (no window manager, desktop icons, or panels).
- **Isolated Audio**: Private `pipewire` + `wireplumber` + `pipewire-pulse` daemon with a virtual null-sink (`cloud_sink`), streaming audio only to the browser without playing out of host speakers or accessing host microphones.
- **Hardware Video Encoding**: NVIDIA NVENC (`nvh264enc`) on RTX 4060 with low-latency baseline CBR profiles and dynamic bitrate switching (4 Mbps to 25 Mbps).
- **Input Engine**: Browser keyboard, mouse (both normal UI cursor mode and 3D Pointer Lock relative mode), Gamepad API (controllers), and mobile touch controls injected directly into the isolated Xwayland server using `libXtst`.

### Phase 2: Steam Integration & Per-User Persistent Storage (Completed)
- **Shared Read-Only Base Library**: `data/shared_steam_library` is mounted strictly read-only (`:ro` at `/steam_shared`) inside the container so game binaries are never duplicated across users and cannot be modified by any session.
- **Per-User Persistent Storage**: Each user gets an isolated persistent directory (`data/users/<user_id>/home/`) mounted into `/home/gamer/.steam`, `/home/gamer/.local/share`, and `/home/gamer/.config`. User A can never see or access User B's saves or Steam session.
- **Zero-Knowledge Steam Login**: Users type Steam credentials strictly into Steam's own GamepadUI (`--app-id 7`) inside the video stream; our application never sees or stores Steam passwords. Steam's encrypted session tokens (`config/loginusers.vdf`, `config/config.vdf`, `userdata/`) persist across sessions per user.
- **Steam `.acf` Manifest Scanner**: Automatically discovers installed Steam games (`appmanifest_*.acf`), filters out Proton/runtime redistributables, and launches games via `/usr/bin/steam -gamepadui -applaunch <AppID>`.
- **Multi-User Save Persistence**: `CyberArena 3D` and native/Proton games persist save files in the user's isolated `$XDG_DATA_HOME` across container destruction and restarts.

---

## Project Structure

```
Home_Cloud_Gaming/
├── engine/
│   ├── sandbox.py          # Ephemeral Bubblewrap container isolation manager & self-check
│   ├── storage_manager.py  # Per-user persistent storage & shared read-only Steam library linker
│   ├── steam_manager.py    # Valve .acf manifest parser, game scanner & GamepadUI launcher
│   ├── session_runner.py   # Isolated session daemon (display, audio, game lifecycle, HTTP/WS)
│   ├── webrtc_streamer.py  # GStreamer webrtcbin + NVENC H.264 + Opus audio + RTCDataChannel
│   ├── input_manager.py    # X11 kiosk window enforcer & libXtst low-latency input injector
│   ├── launch_phase1.py    # Host CLI launcher (supports --user, --app-id, --list-games, etc.)
│   ├── launch_phase2.py    # Phase 2 CLI entrypoint for multi-user & Steam sessions
│   └── test_game/
│       ├── arena3d.c       # Source for 60 FPS OpenGL/SDL2 test game with persistent saves
│       └── arena3d         # Compiled binary
├── web/
│   └── prototype.html      # Browser WebRTC player UI (Cursor + Lock Mouse, stats HUD, touch pad)
├── tests/
│   ├── test_phase1.py      # Phase 1 security invariant & WebRTC streaming test suite
│   └── test_phase2.py      # Phase 2 multi-user save persistence & Steam library test suite
├── data/                   # Auto-created runtime storage (shared_steam_library + users/<id>)
├── README.md               # Quickstart & operational guide (this file)
└── PLAN.md                 # Complete architectural blueprint and 6-phase roadmap
```

---

## Prerequisites

- **OS**: Linux (tested on CachyOS / Arch Linux with kernel 7.2+)
- **GPU**: NVIDIA GPU with NVENC support (tested on RTX 4060, driver 615+)
- **Installed Packages**:
  - `bubblewrap` (`bwrap`)
  - `gamescope`, `weston`, `xorg-server-xwayland`
  - `gstreamer`, `gst-plugins-base`, `gst-plugins-good`, `gst-plugins-bad`, `gst-libav`
  - `pipewire`, `pipewire-pulse`, `wireplumber`
  - `python` (3.10+), `python-gobject`, `python-aiohttp`
  - `sdl2`, `mesa-utils`, `steam`

---

## How to Run & Verify

### 1. Run the Automated Test Suites
Verify Phase 1 (sandbox isolation, WebRTC SDP/ICE, NVENC bitrate switching, input injection) and Phase 2 (per-user storage isolation, `.acf` game discovery, and multi-user persistent savegames across ephemeral container restarts):
```bash
python3 tests/test_phase1.py
python3 tests/test_phase2.py
```

### 2. List Discovered Games & Check User Storage Status
```bash
# List built-in games and any Steam games in data/shared_steam_library/steamapps:
python3 engine/launch_phase2.py --list-games

# Check persistent savegame & Steam login status for a specific user:
python3 engine/launch_phase2.py --user vansh --user-status
```

### 3. Launch a Session with Per-User Persistent Saves
Launch `CyberArena 3D` (`--app-id 0`) for user `vansh`:
```bash
python3 engine/launch_phase2.py --user vansh --app-id 0 --port 8080
```
Open **`http://localhost:8080`** (or `http://<YOUR_PC_LAN_IP>:8080` on your phone/laptop):
1. Click **Lock Mouse** in the top bar (or click the video) to lock the mouse for 3D look, and press **`F`** or **Left Click** to shoot crystals (`+250` points each).
2. Notice the 3D HUD at the top (`CYBERARENA 3D - SCORE: ... HIGH: ... USER: VANSH (RUN 1)`) and the **Stats** overlay (`User Profile`, `High Score`, `Steam Login`).
3. Press **`Escape`** (or click **End Session**) to exit the game and destroy the ephemeral container.
4. Run the command again for `--user vansh`: your `HIGH` score and `RUN 2` counter are automatically restored in the new container!
5. Run with `--user friend1`: `friend1` starts cleanly with `HIGH: 0` and `RUN 1`, completely isolated from `vansh`.

### 4. Launch Isolated Steam Big Picture (Account Login & Steam Games)
To log into Steam inside your isolated per-user container (so your Steam credentials are typed strictly inside Steam's own UI and remembered for next time):
```bash
python3 engine/launch_phase2.py --user vansh --app-id 7 --port 8080
```
- In the browser (`http://localhost:8080`), use normal cursor mode (default) to click and type into Steam's login screen, or use a controller.
- To expose existing installed Steam games from a library folder into the read-only shared library (`data/shared_steam_library/steamapps`), copy or bind-mount `appmanifest_<appid>.acf` and `common/<GameFolder>` into `data/shared_steam_library/steamapps/`, then launch directly with `--app-id <appid>`.

---

## In-Game Controls & Features

| Control | Action |
| :--- | :--- |
| **Normal Cursor Mode** | Default mode: move cursor, click buttons, and type into Steam login / game menus |
| **Lock Mouse Button** | Locks mouse pointer for 360° 3D FPS camera look |
| **W, A, S, D / Arrow Keys** | Move and strafe in 3D |
| **Left Click / F / Enter** | Fire laser projectile (plays procedural synth laser sound & saves high score) |
| **Right Click / Space** | Jump (plays whoosh sound effect) |
| **Gamepad (Controller)** | Left stick to move, right stick to look, `A` to jump, `X`/`RT` to fire |
| **Touch Pad (Mobile)** | On-screen virtual analog thumbstick + `JUMP`, `FIRE`, `TURN`, `LOOK` touch buttons |
| **Stats Button / Tab** | Toggle real-time overlay (Latency/RTT ms, FPS, Bitrate, User, High Score, Steam Login, Isolation) |
| **Quality Dropdown** | Dynamically adjust NVENC bitrate on the fly (Low 4M, Med 8M, High 15M, Ultra 25M) |
| **Fullscreen Button** | Toggle true fullscreen video mode |
| **Escape Key / End Session** | Quits the game, immediately destroys the container, and wipes all temporary session files |

---

## Next Steps

See [PLAN.md](file:///home/vansh/Projects/Home_Cloud_Gaming/PLAN.md) for the complete roadmap and details on **Phase 3: Backend Orchestrator, Safety Limits & Invite-Only Auth**.
