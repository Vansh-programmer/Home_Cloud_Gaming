# Ryoku Cloud Gaming

A personal browser-based cloud gaming system that turns your Linux gaming PC into a private cloud gaming service. Stream games directly to any desktop or mobile browser over WebRTC with hardware-accelerated video/audio encoding and low-latency controls.

---

## The Core Security Rule

> **Strict Isolation — Zero Host Access**
> When a user launches a game, they interact **only** with that isolated game. They can never access your PC's desktop, files (`/home`), host applications, audio devices, physical keyboard/mouse devices, or other users' sessions. Each session runs in an unprivileged ephemeral sandbox that is completely destroyed when the session ends.

---

## Current Status: Phase 1 Completed

Phase 1 (Isolated Single-Game WebRTC Prototype) is fully functional and verified:
- **Sandbox**: Unprivileged Bubblewrap (`bwrap`) container with isolated PID, IPC, UTS, and user namespaces; ephemeral `tmpfs` mounts for `/tmp`, `/run`, `/var`, `/home`.
- **Kiosk Display**: Headless `weston` compositor + isolated `Xwayland` server running with single-window enforcement (no window manager, desktop icons, or panels).
- **Isolated Audio**: Private `pipewire` + `wireplumber` + `pipewire-pulse` daemon with a virtual null-sink (`cloud_sink`), streaming audio only to the browser without playing out of host speakers or accessing host microphones.
- **Hardware Video Encoding**: NVIDIA NVENC (`nvh264enc`) on RTX 4060 with low-latency baseline CBR profiles and dynamic bitrate switching (4 Mbps to 25 Mbps).
- **Input Engine**: Browser keyboard, mouse (Pointer Lock relative motion and absolute positioning), Gamepad API (controllers), and mobile touch controls injected directly into the isolated Xwayland server using `libXtst`.
- **Interactive 3D Game**: `CyberArena 3D` (`engine/test_game/arena3d`), a native 60 FPS OpenGL + SDL2 3D arena game with real-time synthesized stereo audio, GPU detection, and input telemetry.
- **Web Player**: Modern responsive client with a real-time stats overlay (RTT/ping, FPS, bitrate, packet loss, isolation status), quality switcher, virtual on-screen touch controller, and automatic reconnect.

---

## Project Structure

```
Home_Cloud_Gaming/
├── engine/
│   ├── sandbox.py          # Ephemeral Bubblewrap container isolation manager & self-check
│   ├── session_runner.py   # Isolated session daemon (display, audio, game lifecycle, HTTP/WS)
│   ├── webrtc_streamer.py  # GStreamer webrtcbin + NVENC H.264 + Opus audio + RTCDataChannel
│   ├── input_manager.py    # X11 kiosk window enforcer & libXtst low-latency input injector
│   ├── launch_phase1.py    # Host CLI launcher (manages container lifecycle and directory cleanup)
│   └── test_game/
│       ├── arena3d.c       # Source for 60 FPS OpenGL/SDL2 test game with synth audio
│       └── arena3d         # Compiled binary
├── web/
│   └── prototype.html      # Browser WebRTC player UI with stats overlay and mobile controls
├── tests/
│   └── test_phase1.py      # Automated security invariant and end-to-end WebRTC test suite
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
  - `sdl2`, `mesa-utils`

---

## How to Run

### 1. Compile the Test Game (Optional / If Modified)
The `CyberArena 3D` test game binary is pre-compiled, but if you modify `engine/test_game/arena3d.c`, recompile it with:
```bash
gcc -O2 -Wall engine/test_game/arena3d.c -o engine/test_game/arena3d \
  -I/usr/include/SDL2 -D_GNU_SOURCE=1 -D_REENTRANT -lSDL2 -lGL -lm
```

### 2. Run the Automated Verification Suite
Verify security invariants, sandbox isolation, WebRTC signaling, input injection, and automatic session cleanup:
```bash
python3 tests/test_phase1.py
```
*Expected output: `Ran 2 tests in ~7.5s ... OK` with `Zero leftover session directories!`*

### 3. Start the Phase 1 Streaming Server
Launch an isolated session on your local network:
```bash
python3 engine/launch_phase1.py --port 8080
```

Available flags:
- `--port <number>`: Web server port (default: `8080`)
- `--width <px>`: Video stream width (default: `1280`)
- `--height <px>`: Video stream height (default: `720`)
- `--fps <number>`: Target framerate (default: `60`)
- `--quality <low|medium|high|ultra>`: Default bitrate profile (default: `high`)
- `--game-cmd <command>`: Custom command to run inside the container

### 4. Connect in Your Browser
Open the following URL on your PC or on any mobile phone / tablet on the same Wi-Fi network:
```
http://localhost:8080
# or from your phone/laptop:
http://<YOUR_PC_LAN_IP>:8080
```

---

## In-Game Controls & Features

| Control | Action |
| :--- | :--- |
| **Click Video** | Locks mouse pointer & unmutes stereo audio stream |
| **W, A, S, D / Arrow Keys** | Move and strafe in 3D |
| **Mouse Motion** | 3D camera look (pitch & yaw) |
| **Left Click / F / Enter** | Fire laser projectile (plays procedural synth laser sound) |
| **Right Click / Space** | Jump (plays whoosh sound effect) |
| **Gamepad (Controller)** | Left stick to move, right stick to look, `A` to jump, `X`/`RT` to fire |
| **Touch Pad (Mobile)** | On-screen virtual analog thumbstick + `JUMP`, `FIRE`, `TURN`, `LOOK` touch buttons |
| **Stats Button / Tab** | Toggle real-time overlay (Latency/RTT ms, FPS, Bitrate Mbps, Isolation status) |
| **Quality Dropdown** | Dynamically adjust NVENC bitrate on the fly (Low 4M, Med 8M, High 15M, Ultra 25M) |
| **Fullscreen Button** | Toggle true fullscreen video mode |
| **Escape Key / End Session** | Quits the game, immediately destroys the container, and wipes all session files |

---

## Verifying Isolation

1. While playing in the browser, check the **Stream Telemetry** overlay in the top left:
   - Status badge displays **`ISOLATION VERIFIED ✓`**.
   - Confirms that host home directory (`/home/vansh`), host X11 display socket (`/tmp/.X11-unix/X0`), host Wayland socket (`/run/user/1000`), physical input devices (`/dev/input/by-id`), and host soundcard are completely blocked.
2. The HUD displays `GPU: NVIDIA GeForce RTX 4060/PCIe/SSE2`, verifying hardware rendering through the isolated render node.
3. Audio generated by the game is audible **only** through your browser; your physical PC speakers stay silent.
4. When you press `ESC` in the game or click **End Session**, inspect `/tmp`:
   ```bash
   ls -la /tmp/cloudgaming-session-*
   ```
   The ephemeral directory is completely removed.

---

## Next Steps

See [PLAN.md](PLAN.md) for the complete roadmap, architectural design, and details on **Phase 2: Steam Integration & Per-User Persistent Storage**.
# Ryoku Cloud Gaming

A personal browser-based cloud gaming system that turns your Linux gaming PC into a private cloud gaming service. Stream games directly to any desktop or mobile browser over WebRTC with hardware-accelerated video/audio encoding and low-latency controls.

---

## The Core Security Rule

> **Strict Isolation — Zero Host Access**
> When a user launches a game, they interact **only** with that isolated game. They can never access your PC's desktop, files (`/home`), host applications, audio devices, physical keyboard/mouse devices, or other users' sessions. Each session runs in an unprivileged ephemeral sandbox that is completely destroyed when the session ends.

---

## Current Status: Phase 1 Completed

Phase 1 (Isolated Single-Game WebRTC Prototype) is fully functional and verified:
- **Sandbox**: Unprivileged Bubblewrap (`bwrap`) container with isolated PID, IPC, UTS, and user namespaces; ephemeral `tmpfs` mounts for `/tmp`, `/run`, `/var`, `/home`.
- **Kiosk Display**: Headless `weston` compositor + isolated `Xwayland` server running with single-window enforcement (no window manager, desktop icons, or panels).
- **Isolated Audio**: Private `pipewire` + `wireplumber` + `pipewire-pulse` daemon with a virtual null-sink (`cloud_sink`), streaming audio only to the browser without playing out of host speakers or accessing host microphones.
- **Hardware Video Encoding**: NVIDIA NVENC (`nvh264enc`) on RTX 4060 with low-latency baseline CBR profiles and dynamic bitrate switching (4 Mbps to 25 Mbps).
- **Input Engine**: Browser keyboard, mouse (Pointer Lock relative motion and absolute positioning), Gamepad API (controllers), and mobile touch controls injected directly into the isolated Xwayland server using `libXtst`.
- **Interactive 3D Game**: `CyberArena 3D` (`engine/test_game/arena3d`), a native 60 FPS OpenGL + SDL2 3D arena game with real-time synthesized stereo audio, GPU detection, and input telemetry.
- **Web Player**: Modern responsive client with a real-time stats overlay (RTT/ping, FPS, bitrate, packet loss, isolation status), quality switcher, virtual on-screen touch controller, and automatic reconnect.

---

## Project Structure

```
Home_Cloud_Gaming/
├── engine/
│   ├── sandbox.py          # Ephemeral Bubblewrap container isolation manager & self-check
│   ├── session_runner.py   # Isolated session daemon (display, audio, game lifecycle, HTTP/WS)
│   ├── webrtc_streamer.py  # GStreamer webrtcbin + NVENC H.264 + Opus audio + RTCDataChannel
│   ├── input_manager.py    # X11 kiosk window enforcer & libXtst low-latency input injector
│   ├── launch_phase1.py    # Host CLI launcher (manages container lifecycle and directory cleanup)
│   └── test_game/
│       ├── arena3d.c       # Source for 60 FPS OpenGL/SDL2 test game with synth audio
│       └── arena3d         # Compiled binary
├── web/
│   └── prototype.html      # Browser WebRTC player UI with stats overlay and mobile controls
├── tests/
│   └── test_phase1.py      # Automated security invariant and end-to-end WebRTC test suite
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
  - `sdl2`, `mesa-utils`

---

## How to Run

### 1. Compile the Test Game (Optional / If Modified)
The `CyberArena 3D` test game binary is pre-compiled, but if you modify `engine/test_game/arena3d.c`, recompile it with:
```bash
gcc -O2 -Wall engine/test_game/arena3d.c -o engine/test_game/arena3d \
  -I/usr/include/SDL2 -D_GNU_SOURCE=1 -D_REENTRANT -lSDL2 -lGL -lm
```

### 2. Run the Automated Verification Suite
Verify security invariants, sandbox isolation, WebRTC signaling, input injection, and automatic session cleanup:
```bash
python3 tests/test_phase1.py
```
*Expected output: `Ran 2 tests in ~7.5s ... OK` with `Zero leftover session directories!`*

### 3. Start the Phase 1 Streaming Server
Launch an isolated session on your local network:
```bash
python3 engine/launch_phase1.py --port 8080
```

Available flags:
- `--port <number>`: Web server port (default: `8080`)
- `--width <px>`: Video stream width (default: `1280`)
- `--height <px>`: Video stream height (default: `720`)
- `--fps <number>`: Target framerate (default: `60`)
- `--quality <low|medium|high|ultra>`: Default bitrate profile (default: `high`)
- `--game-cmd <command>`: Custom command to run inside the container

### 4. Connect in Your Browser
Open the following URL on your PC or on any mobile phone / tablet on the same Wi-Fi network:
```
http://localhost:8080
# or from your phone/laptop:
http://<YOUR_PC_LAN_IP>:8080
```

---

## In-Game Controls & Features

| Control | Action |
| :--- | :--- |
| **Click Video** | Locks mouse pointer & unmutes stereo audio stream |
| **W, A, S, D / Arrow Keys** | Move and strafe in 3D |
| **Mouse Motion** | 3D camera look (pitch & yaw) |
| **Left Click / F / Enter** | Fire laser projectile (plays procedural synth laser sound) |
| **Right Click / Space** | Jump (plays whoosh sound effect) |
| **Gamepad (Controller)** | Left stick to move, right stick to look, `A` to jump, `X`/`RT` to fire |
| **Touch Pad (Mobile)** | On-screen virtual analog thumbstick + `JUMP`, `FIRE`, `TURN`, `LOOK` touch buttons |
| **Stats Button / Tab** | Toggle real-time overlay (Latency/RTT ms, FPS, Bitrate Mbps, Isolation status) |
| **Quality Dropdown** | Dynamically adjust NVENC bitrate on the fly (Low 4M, Med 8M, High 15M, Ultra 25M) |
| **Fullscreen Button** | Toggle true fullscreen video mode |
| **Escape Key / End Session** | Quits the game, immediately destroys the container, and wipes all session files |

---

## Verifying Isolation

1. While playing in the browser, check the **Stream Telemetry** overlay in the top left:
   - Status badge displays **`ISOLATION VERIFIED ✓`**.
   - Confirms that host home directory (`/home/vansh`), host X11 display socket (`/tmp/.X11-unix/X0`), host Wayland socket (`/run/user/1000`), physical input devices (`/dev/input/by-id`), and host soundcard are completely blocked.
2. The HUD displays `GPU: NVIDIA GeForce RTX 4060/PCIe/SSE2`, verifying hardware rendering through the isolated render node.
3. Audio generated by the game is audible **only** through your browser; your physical PC speakers stay silent.
4. When you press `ESC` in the game or click **End Session**, inspect `/tmp`:
   ```bash
   ls -la /tmp/cloudgaming-session-*
   ```
   The ephemeral directory is completely removed.

---

## Next Steps

See [PLAN.md](PLAN.md) for the complete roadmap, architectural design, and details on **Phase 2: Steam Integration & Per-User Persistent Storage**.
