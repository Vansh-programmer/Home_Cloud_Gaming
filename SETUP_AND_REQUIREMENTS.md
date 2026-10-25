# Setup, Requirements & Deployment Guide (This PC & Any Linux PC)

This guide covers everything needed to install, configure, and run **Ryoku Cloud Gaming** both on **your current gaming PC (`ryoku`)** and on **any other Linux PC** (Arch/CachyOS, Ubuntu/Debian, or Fedora).

---

## 1. Requirements Overview

### Hardware Requirements (Host Gaming PC)

| Component | Minimum Requirement | Recommended (Your Current PC `ryoku`) |
| :--- | :--- | :--- |
| **OS** | Linux (Kernel 5.15+ with User Namespaces enabled) | **CachyOS / Arch Linux** (Kernel `7.2.7-1-cachyos`) |
| **CPU** | 4 Cores / 8 Threads (x86_64) | **Intel Core i5-11400** (6 Cores / 12 Threads) |
| **RAM** | 8 GB | **16 GB DDR4** |
| **GPU** | NVIDIA GTX 10-series+ (NVENC) or AMD/Intel GPU (with CPU `x264enc` fallback) | **NVIDIA GeForce RTX 4060 (8 GB VRAM)** with hardware `nvh264enc` |
| **Disk Space** | 25 GB free for OS + container runtime + saves | **176 GB free** (Shared read-only Steam library + per-user overlays) |

### Client Requirements (Devices That Can Play)
- **Zero installation required on client devices.**
- Any modern browser with WebRTC support (`Chrome`, `Chromium`, `Brave`, `Edge`, `Firefox`, `Safari`) on **Desktop, Laptop, Android, iPhone, or iPad**.

---

## 2. Running on THIS PC (`ryoku` — CachyOS + RTX 4060)

### 2.1 What Is Already Installed & Verified on Your PC
During our hardware check and test runs on your PC (`ryoku`), all core dependencies were verified as installed and working:
- **NVIDIA Driver & NVENC**: `615.71.09` (`/dev/dri/renderD128`, `/dev/nvidia0`, `nvh264enc` GStreamer element, `nvidia-smi`)
- **Container & Display**: `bubblewrap` (`/usr/bin/bwrap`), `weston`, `Xwayland`, `gamescope`
- **Audio**: `pipewire`, `pipewire-pulse`, `wireplumber`, `pactl`
- **WebRTC & Media**: `gstreamer`, `gst-plugins-base`, `gst-plugins-good`, `gst-plugins-bad` (`webrtcbin`, `nvh264enc`, `opusenc`), `libnice`
- **Input & Native Game**: `libX11`, `libXtst`, `sdl2`, `gcc`, `steam`
- **Python Stack**: `python3` (3.14), `python-gobject` (`gi`), `python-aiohttp`

*(Optional for external WAN/5G access outside your home Wi-Fi)*:
If you want to expose your server on a custom domain with Cloudflare Tunnel and a local TURN server, install `cloudflared` and `coturn`:
```bash
sudo pacman -S --needed cloudflared coturn
```

### 2.2 Step-by-Step: How to Run on This PC Right Now

1. **Open a terminal in the project folder**:
   ```bash
   cd /home/vansh/Projects/Home_Cloud_Gaming
   ```

2. **Start the Full Cloud Gaming Server**:
   ```bash
   python3 engine/launch_phase6.py --host 0.0.0.0 --port 8080 --admin-user vansh --admin-password ryoku-admin-2026
   ```

3. **Play on This PC or Any Device on Your Home Wi-Fi**:
   - **On this PC**: Open **`http://localhost:8080`** in your browser.
   - **On your phone/laptop on the same Wi-Fi**: Find your PC's LAN IP (`ip -4 addr show | grep inet`) and open **`http://<YOUR_PC_LAN_IP>:8080`**.
   - Log in with:
     - **Username**: `vansh`
     - **Password**: `ryoku-admin-2026`

4. **Invite Friends**:
   - Click the **Admin Console** tab at the top.
   - Enter a friend's name in the invite note box and click **+ Generate Single-Use Invite**.
   - Click **Copy** next to the `RYOKU-XXXX-XXXXXX` code and send it to your friend so they can create their own isolated account via the **Redeem Invite Code** tab on the login page.

5. **Add Your Steam Games to the Shared Library**:
   - Option A (**Log into Steam inside the stream**): In the Game Library, launch **Steam Big Picture** (`AppID 7`). Type your Steam login inside the video stream. Your login token is saved inside `data/users/<username>/home/` for future sessions.
   - Option B (**Expose existing installed Steam games read-only**): Symlink or copy your installed `appmanifest_<AppID>.acf` and `common/<GameFolder>` into `data/shared_steam_library/steamapps/`:
     ```bash
     ln -s ~/.local/share/Steam/steamapps/appmanifest_*.acf /home/vansh/Projects/Home_Cloud_Gaming/data/shared_steam_library/steamapps/
     ln -s ~/.local/share/Steam/steamapps/common/* /home/vansh/Projects/Home_Cloud_Gaming/data/shared_steam_library/steamapps/common/
     ```
   - Refresh the Game Library page—all your installed Steam games will automatically appear with cover art and a **Launch Game** button!

---

## 3. Running on ANY Other Linux PC (Fresh Setup Guide)

If you clone or copy this project onto another Linux PC, follow these steps for your distribution.

### 3.1 Install Required System Packages

#### Option A: Arch Linux / CachyOS / Manjaro / EndeavourOS
Enable `[multilib]` in `/etc/pacman.conf` (required for Steam), then run:
```bash
sudo pacman -Syu --needed \
  python python-pip python-gobject python-aiohttp \
  bubblewrap weston xorg-server-xwayland gamescope \
  pipewire pipewire-pulse wireplumber libpulse \
  gstreamer gst-plugins-base gst-plugins-good gst-plugins-bad gst-plugins-ugly gst-libav libnice \
  libx11 libxtst sdl2 mesa glu gcc pkgconf \
  steam cloudflared coturn
```
*For NVIDIA GPUs on Arch/CachyOS, ensure `nvidia-utils` and `lib32-nvidia-utils` are installed so `nvh264enc` and Vulkan work inside the container.*

#### Option B: Ubuntu 24.04+ / Debian 12+ / Pop!_OS / Linux Mint
```bash
sudo dpkg --add-architecture i386
sudo apt update
sudo apt install -y \
  python3 python3-pip python3-gi python3-gst-1.0 python3-aiohttp \
  gir1.2-gst-plugins-bad-1.0 gir1.2-gst-plugins-base-1.0 \
  bubblewrap weston xwayland gamescope \
  pipewire pipewire-pulse wireplumber pulseaudio-utils \
  gstreamer1.0-tools gstreamer1.0-plugins-base gstreamer1.0-plugins-good \
  gstreamer1.0-plugins-bad gstreamer1.0-plugins-ugly gstreamer1.0-libav gstreamer1.0-nice \
  libx11-6 libxtst6 libsdl2-dev libgl1-mesa-dev libglu1-mesa-dev build-essential \
  coturn
```

#### Option C: Fedora 40+ / Nobara / Bazzite
```bash
sudo dnf install -y \
  python3 python3-gobject python3-gstreamer1 python3-aiohttp \
  bubblewrap weston xorg-x11-server-Xwayland gamescope \
  pipewire pipewire-pulseaudio wireplumber pulseaudio-utils \
  gstreamer1 gstreamer1-plugins-base gstreamer1-plugins-good \
  gstreamer1-plugins-bad-free gstreamer1-plugins-bad-free-extras libnice-gstreamer1 \
  libX11 libXtst SDL2-devel mesa-libGL-devel mesa-libGLU-devel gcc \
  steam coturn
```

---

### 3.2 Verify Unprivileged User Namespaces (Required for Bubblewrap Isolation)
Bubblewrap (`bwrap`) uses unprivileged user namespaces to isolate each session without needing `root` or `--privileged`.
Check that unprivileged user namespaces are enabled on the target PC:
```bash
bwrap --unshare-user --ro-bind /usr /usr --symlink usr/lib /lib --symlink usr/lib /lib64 --symlink usr/bin /bin --proc /proc --dev /dev /usr/bin/true && echo "Bubblewrap OK"
```
*(Note: On Ubuntu 24.04+, if AppArmor blocks unprivileged `bwrap`, run `sudo sysctl -w kernel.apparmor_restrict_unprivileged_userns=0` or install the standard `bwrap` AppArmor profile).*

---

### 3.3 Compile the Built-in 60 FPS OpenGL Test Game (`CyberArena 3D`)
When moving to a new PC (or if `engine/test_game/arena3d` needs to be rebuilt against the local system's SDL2/OpenGL libraries), compile [`engine/test_game/arena3d.c`](file:///home/vansh/Projects/Home_Cloud_Gaming/engine/test_game/arena3d.c):
```bash
gcc -O2 engine/test_game/arena3d.c -o engine/test_game/arena3d $(sdl2-config --cflags --libs) -lGL -lGLU -lm
```

---

### 3.4 Run the Verification Test Suites on the New PC
Run the 6 automated test suites to confirm that Bubblewrap isolation, headless Weston/Xwayland, PipeWire virtual audio, hardware/software H.264 encoding, SQLite auth, and WebRTC streaming all pass on the new machine:
```bash
python3 tests/test_phase1.py
python3 tests/test_phase2.py
python3 tests/test_phase3.py
python3 tests/test_phase4.py
python3 tests/test_phase5.py
python3 tests/test_phase6.py
```
*(Note: If the new PC has an AMD or Intel GPU instead of an NVIDIA GPU, [`engine/webrtc_streamer.py`](file:///home/vansh/Projects/Home_Cloud_Gaming/engine/webrtc_streamer.py#L86-L96) automatically detects that `nvh264enc` is absent and falls back to ultra-low-latency `x264enc` without requiring any code changes!)*

---

## 4. Deploying on Your Domain (`https://vanshdev.online/cloudgaming`)

The backend ([`backend/server.py`](file:///home/vansh/Projects/Home_Cloud_Gaming/backend/server.py)) and frontend ([`web/assets/app.js`](file:///home/vansh/Projects/Home_Cloud_Gaming/web/assets/app.js)) natively support the `/cloudgaming` subpath—so all pages, static assets (`/cloudgaming/assets/...`), REST API calls (`/cloudgaming/api/...`), and WebSocket streams (`wss://vanshdev.online/cloudgaming/api/sessions/current/ws`) work automatically without interfering with anything else hosted at the root of `vanshdev.online`.

### Step 1: Install & Authenticate Cloudflare Tunnel (`cloudflared`)
1. Install `cloudflared` on your CachyOS PC if not installed yet:
   ```bash
   sudo pacman -S --needed cloudflared
   ```
2. Log into your Cloudflare account (select `vanshdev.online` in the browser prompt):
   ```bash
   cloudflared tunnel login
   ```
3. Create the tunnel (or fetch the credentials JSON file if the tunnel already exists in your Cloudflare account):
   ```bash
   # If creating a brand-new tunnel:
   cloudflared tunnel create vansh-cloud-gaming

   # OR if reusing your existing vansh-cloud-gaming tunnel (UUID: 43a598d8-3099-49ff-8e65-a28b63cafa05):
   mkdir -p ~/.cloudflared
   cloudflared tunnel token --cred-file ~/.cloudflared/43a598d8-3099-49ff-8e65-a28b63cafa05.json vansh-cloud-gaming
   ```

### Step 2: Configure the `/cloudgaming` Subpath Route
You can configure the `/cloudgaming` path either via the **Cloudflare Zero Trust Dashboard** (easiest if `vanshdev.online` already hosts another site) or via [`deploy/cloudflared-config.yml`](file:///home/vansh/Projects/Home_Cloud_Gaming/deploy/cloudflared-config.yml):

- **Option A — Via Cloudflare Zero Trust Dashboard (Recommended if `vanshdev.online` is already live)**:
  1. Go to **Cloudflare Zero Trust Dashboard** → **Networks** → **Tunnels** → select `ryoku-cloud-gaming` → **Public Hostname** → **Add a public hostname**:
     - **Subdomain**: *(leave blank)*
     - **Domain**: `vanshdev.online`
     - **Path**: `cloudgaming`
     - **Service Type**: `HTTP`
     - **URL**: `127.0.0.1:8080`
  2. Start the tunnel on your PC:
     ```bash
     cloudflared tunnel run ryoku-cloud-gaming
     ```

- **Option B — Via Local Config File ([`deploy/cloudflared-config.yml`](file:///home/vansh/Projects/Home_Cloud_Gaming/deploy/cloudflared-config.yml))**:
  1. Open [`deploy/cloudflared-config.yml`](file:///home/vansh/Projects/Home_Cloud_Gaming/deploy/cloudflared-config.yml) and replace `TUNNEL_UUID` with your actual Tunnel UUID.
  2. Route DNS and run the tunnel:
     ```bash
     cloudflared tunnel route dns ryoku-cloud-gaming vanshdev.online
     cloudflared tunnel --config deploy/cloudflared-config.yml run
     ```

### Step 3: Start the Ryoku Cloud Gaming Server on Your PC
```bash
python3 engine/launch_phase6.py \
  --host 0.0.0.0 \
  --port 8080 \
  --public-domain vanshdev.online/cloudgaming \
  --admin-user vansh \
  --admin-password ryoku-admin-2026
```
You and your invited friends can now open **`https://vanshdev.online/cloudgaming`** from any desktop or mobile browser!

### Step 4: Deploy the Always-On PC-Offline Cloudflare Worker for `vanshdev.online/cloudgaming*`
1. In your Cloudflare Dashboard → **Workers & Pages**, create a new Worker (e.g. `ryoku-offline-gateway`) and paste the contents of [`deploy/cloudflare_worker.js`](file:///home/vansh/Projects/Home_Cloud_Gaming/deploy/cloudflare_worker.js).
2. In your `vanshdev.online` zone → **Workers Routes** → **Add route**:
   - **Route**: `vanshdev.online/cloudgaming*`
   - **Worker**: `ryoku-offline-gateway`
3. Now, whenever your gaming PC is turned off, anyone visiting **`https://vanshdev.online/cloudgaming`** will see the **Ryoku Cloud — Gaming PC is Currently Powered Off** page, which automatically polls `/cloudgaming/api/health` and redirects into the Game Library the moment your PC boots up.

### Step 3: Enable TURN Relay for Strict Cellular/5G Networks (Optional)
1. Edit [`deploy/turnserver.conf`](file:///home/vansh/Projects/Home_Cloud_Gaming/deploy/turnserver.conf) and set a strong `static-auth-secret`.
2. Start `coturn`:
   ```bash
   turnserver -c deploy/turnserver.conf
   ```
3. In the Ryoku Cloud Gaming **Admin Console** → **External HTTPS Domain, Cloudflare Tunnel & STUN/TURN Traversal**, enter your `TURN SERVER URL` (`turn:turn.yourdomain.com:3478`) and `COTURN HMAC AUTH SECRET`, then click **Save Network & TURN**.

### Step 5: Auto-Start Both Server & Cloudflare Tunnel on Boot with `systemd` (Optional)
To have both Ryoku Cloud Gaming and your Cloudflare Tunnel start automatically in the background whenever your PC boots:
```bash
sudo cp /home/vansh/Projects/Home_Cloud_Gaming/deploy/ryoku-cloud-gaming.service /etc/systemd/system/
sudo cp /home/vansh/Projects/Home_Cloud_Gaming/deploy/ryoku-cloudflare-tunnel.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now ryoku-cloud-gaming.service ryoku-cloudflare-tunnel.service
```
Check live logs anytime with:
```bash
journalctl -u ryoku-cloud-gaming.service -u ryoku-cloudflare-tunnel.service -f
```

