# UNIVERSAL LINUX SETUP GUIDE // RYOKU CLOUD GAMING

Turn any Linux laptop or desktop PC into a self-hosted cloud gaming server. Stream 60 FPS video and low-latency audio directly to any web browser (phones, tablets, MacBooks, Chromebooks, Smart TVs) without installing client software.

---

## 1. SUPPORTED DISTRIBUTIONS & HARDWARE

Ryoku runs natively on any modern Linux distribution with kernel 5.15+:

| Linux Distribution | Package Manager | Tested Status |
| :--- | :--- | :--- |
| **Arch Linux / CachyOS / Manjaro / EndeavourOS** | `pacman` | Fully Tested |
| **Ubuntu 22.04 / 24.04 / Pop!_OS / Linux Mint / Debian 12** | `apt` | Fully Supported |
| **Fedora 39 / 40 / 41 / Nobara** | `dnf` | Fully Supported |
| **openSUSE Tumbleweed / Leap** | `zypper` | Fully Supported |

### Hardware Acceleration (GPU Compatibility)

The engine automatically detects and prioritizes hardware encoders at runtime:

- **NVIDIA GeForce (GTX 900+ / RTX 20 / 30 / 40 Series)**: Uses NVIDIA NVENC (`nvh264enc`) with zero-copy ultra-low-latency encoding (~1.2ms per frame).
- **AMD Radeon (RX 400+ / 5000 / 6000 / 7000 Series / Ryzen iGPUs)**: Uses AMD VA-API (`vaapih264enc` / `vah264enc`) for hardware encoding.
- **Intel Core (6th–14th Gen / Iris Xe / Intel Arc)**: Uses Intel QuickSync VA-API (`vaapih264enc`) with low CPU overhead.
- **CPU Software Fallback**: If no supported hardware encoder is detected, the engine falls back to multi-threaded `x264enc` (ultrafast zero-latency profile).

---

## 2. INSTALLATION BY DISTRIBUTION

Run the single command matching your host distribution to install all required sandbox, audio, display, and media pipeline dependencies:

### Arch Linux / CachyOS / Manjaro
```bash
sudo pacman -S --needed \
  bubblewrap weston xorg-server-xwayland \
  pipewire pipewire-pulse wireplumber \
  gstreamer gst-plugins-base gst-plugins-good gst-plugins-bad gst-libav \
  python python-gobject python-aiohttp \
  sdl2 glu mesa-utils gcc
```

### Ubuntu (22.04 / 24.04 LTS) / Linux Mint / Pop!_OS / Debian 12
```bash
sudo apt update && sudo apt install -y \
  bubblewrap weston xwayland \
  pipewire pipewire-pulse wireplumber \
  gstreamer1.0-tools gstreamer1.0-plugins-base gstreamer1.0-plugins-good \
  gstreamer1.0-plugins-bad gstreamer1.0-plugins-ugly gstreamer1.0-libav gstreamer1.0-vaapi \
  libgstreamer1.0-0 libgstreamer-plugins-bad1.0-0 \
  gir1.2-gstreamer-1.0 gir1.2-gst-plugins-base-1.0 gir1.2-gst-plugins-bad-1.0 \
  python3 python3-aiohttp python3-gi python3-gi-cairo \
  libsdl2-dev libglu1-mesa-dev gcc
```

### Fedora 39 / 40 / 41 / Nobara
```bash
sudo dnf install -y \
  bubblewrap weston xorg-x11-server-Xwayland \
  pipewire pipewire-pulseaudio wireplumber \
  gstreamer1-plugins-base gstreamer1-plugins-good gstreamer1-plugins-bad-free \
  gstreamer1-plugins-ugly-free gstreamer1-vaapi \
  python3 python3-aiohttp python3-gobject \
  SDL2-devel mesa-libGLU-devel gcc
```

### openSUSE Tumbleweed / Leap
```bash
sudo zypper install -y \
  bubblewrap weston xwayland \
  pipewire pipewire-pulseaudio wireplumber \
  gstreamer-plugins-base gstreamer-plugins-good gstreamer-plugins-bad \
  gstreamer-plugins-ugly gstreamer-plugins-vaapi \
  python3 python3-aiohttp python3-gobject \
  libSDL2-devel Mesa-libGLU-devel gcc
```

---

## 3. STARTING THE CLOUD GAMING SERVER

### Option A: Standard Interactive Run
```bash
./start.sh
```
This automatically:
1. Compiles the built-in 3D game ([`CyberArena 3D`](file:///home/vansh/Projects/Home_Cloud_Gaming/engine/test_game/arena3d.c)) if not already built.
2. Clears conflicting background instances on port 8080.
3. Detects your machine's LAN IP address.
4. Starts the server and displays the connection URLs and administrator credentials:

```text
+----------------------------------------------------------------------------+
| ACCESS ENDPOINTS                                                           |
|   Local PC     : http://localhost:8080                                     |
|   Home Wi-Fi   : http://192.168.1.5:8080                                   |
|                                                                            |
| ADMIN CREDENTIALS                                                          |
|   Username     : vansh                                                     |
|   Password     : ryoku-admin-2026                                          |
+----------------------------------------------------------------------------+
```

### Option B: Run in Background (Daemon Mode)
```bash
./start.sh --background
```
- Logs are stored in `data/logs/server.log`.
- To check live status: `./start.sh --status`
- To stop the server: `./start.sh --stop`

### Option C: Auto-Start on System Boot (Headless Console Setup)
To make your laptop or PC start the cloud gaming server automatically when powered on:
```bash
./start.sh --install-service
```
This registers a `systemd` service (`ryoku-cloud-gaming.service`) running under your user account.

---

## 4. PLAYING FROM ANY DEVICE

Connect any device on your local Wi-Fi or Ethernet:
1. Open Google Chrome, Safari, Edge, Firefox, or Brave on your client device (phone, tablet, laptop, or Smart TV).
2. Browse to `http://<HOST-IP>:8080` (e.g. `http://192.168.1.5:8080`).
3. Log in with your admin credentials.
4. Click **PLAY NOW** on CyberArena 3D or any linked Steam game.

### Input Support
- **Keyboard & Mouse**: Click into the video stream to engage 3D Pointer Lock. Press `Esc` to unlock.
- **Physical Gamepad**: Plug in an Xbox, PlayStation, or generic controller via USB or Bluetooth. The browser Gamepad API automatically activates.
- **Touch Controls**: Mobile devices automatically display on-screen virtual analog thumbsticks and action buttons.

---

## 5. REMOTE PLAY (OUTSIDE HOME WI-FI)

To stream games over cellular data (4G/5G) or outside Wi-Fi:

### Method A: Tailscale (Fastest & Simplest — No Domain or Port Forwarding)
1. Install [Tailscale](https://tailscale.com) on your gaming PC/laptop:
   ```bash
   curl -fsSL https://tailscale.com/install.sh | sh
   sudo tailscale up
   ```
2. Install the free Tailscale app on your phone, tablet, or secondary laptop and sign in to the same account.
3. Open `http://<TAILSCALE-IP>:8080` in your browser. WebRTC connects peer-to-peer over an encrypted wireguard tunnel.

### Method B: Cloudflare Tunnel + Free TURN Relay
1. Create a free Cloudflare Tunnel pointing to `http://localhost:8080`.
2. Add free TURN relay credentials (e.g., from [Metered.ca OpenRelay](https://www.metered.ca/tools/openrelay/)) in `.env` (`TURN_URL`, `TURN_USERNAME`, `TURN_PASSWORD`).
3. Run `./start.sh --check-turn` to verify relay readiness.

---

## 6. LAPTOP-SPECIFIC CONFIGURATION

### Prevent Laptop from Sleeping When Lid Is Closed
If you are using a laptop as a closed-lid headless server, prevent Linux from sleeping on lid close:

1. Edit `/etc/systemd/logind.conf`:
   ```ini
   [Login]
   HandleLidSwitch=ignore
   HandleLidSwitchExternalPower=ignore
   HandleLidSwitchDocked=ignore
   ```
2. Restart the login daemon:
   ```bash
   sudo systemctl restart systemd-logind
   ```

### Hybrid / Dual GPU Laptops (NVIDIA Optimus / AMD iGPU + dGPU)
If your laptop has both an integrated GPU (Intel/AMD) and a discrete GPU (NVIDIA RTX):
- The server automatically binds `/dev/dri/renderD128` and `/dev/nvidia*`.
- Ensure NVIDIA proprietary drivers (`nvidia`, `nvidia-utils`) are installed so NVENC hardware encoding is available to GStreamer.
- Verify hardware acceleration with:
  ```bash
  gst-inspect-1.0 nvh264enc
  ```

---

## 7. VERIFICATION & HEALTH CHECKS

To verify your installation before streaming:

```bash
# 1. Check GStreamer WebRTC and audio plugins:
gst-inspect-1.0 webrtcbin
gst-inspect-1.0 pulsesrc

# 2. Check Bubblewrap unprivileged sandbox capability:
bwrap --ro-bind / / --dev /dev --proc /proc echo "Sandbox OK"

# 3. Run the automated test suite:
python3 -m unittest tests.test_phase1.TestPhase1IsolatedStreaming
python3 -m unittest tests.test_phase4.TestPhase4ProductWebAppAndHUD
```

