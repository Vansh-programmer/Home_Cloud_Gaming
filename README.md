# RYOKU // CLOUD GAMING PLATFORM (CONTAINER ARCHITECTURE)

```text
+-----------------------------------------------------------------------------------+
|  RYOKU CLOUD GAMING  //  HEADLESS CLOUD GAMING INFRASTRUCTURE                     |
|  ARCHITECTURE : DOCKER CONTAINER ON-DEMAND + GAMES ON WHALES (WOLF)               |
|  TARGET GPU   : NVIDIA GEFORCE RTX 4060 (NVENC HEVC/H.264 + OPUS AUDIO)           |
|  SECURITY     : 100% CONTAINER ISOLATION (ZERO HOST DESKTOP / ZERO HOST FILES)   |
|  CLIENTS      : MOONLIGHT (WINDOWS / MACOS / LINUX / ANDROID / IOS) + WEBRTC      |
+-----------------------------------------------------------------------------------+
```

> **Note on Architecture Evolution**:
> The previous custom Bubblewrap + Weston + GStreamer prototype is archived on the **`legacy-v1`** branch.
> Starting with this branch (`main`), Ryoku Cloud Gaming is built as a **true multi-tenant Cloud Gaming Platform** powered by **Games on Whales (Wolf)**.

---

## 1. Cloud Gaming vs Personal Streaming Architecture

Unlike a traditional personal game streaming setup (which streams your physical desktop and relies on your personal Steam login), Ryoku operates as a **Cloud Gaming Compute Node**:

| Feature | Personal Streaming (Old) | Ryoku Cloud Gaming (Current) |
| :--- | :--- | :--- |
| **Host Desktop Security** | Exposes host screen, wallpaper, and files | **Zero host presence**; containers have no desktop |
| **Isolation Boundary** | User process on host session | **Docker OCI container** with dedicated cgroups |
| **Crash Protection** | Reverts to host desktop if game crashes | **Container exits cleanly**; client never sees host |
| **Storage Model** | Mounts host personal Steam library | **Dedicated named volumes** (`ryoku-cloud-storage`) |
| **Multi-Tenant / Ephemeral** | Single physical user only | Ephemeral on-demand session containers |

---

## 2. Platform Architecture

```mermaid
flowchart TD
    subgraph Clients ["Remote Clients (LAN / Tailscale / Internet)"]
        ML["Moonlight Client (Windows / Android / iOS / Mac)"]
        WB["Browser Web Client (WebRTC / Wolf-Den)"]
    end

    subgraph Host_Hypervisor ["Host Machine (Bare-Metal GPU Compute Node)"]
        TS["Tailscale Mesh (100.89.198.41)"]
        DK["Docker Engine (nvidia-container-toolkit)"]
        NV["NVIDIA RTX 4060 Driver (615.78.08 via nvidia-driver-vol)"]
        HD["Host Desktop (Hyprland / HDMI-A-1) — 100% UNTOUCHED & INVISIBLE"]
    end

    subgraph Container_Stack ["Cloud Gaming Containers (Isolated & Ephemeral)"]
        WOLF["Wolf Streaming Server (ghcr.io/games-on-whales/wolf)"]
        WD["Wolf-Den Admin Console (Port 8080)"]
        
        subgraph Session_Containers ["On-Demand Game Sessions"]
            STM["Steam Cloud Container (ghcr.io/games-on-whales/steam:edge)"]
            RET["RetroArch Container (ghcr.io/games-on-whales/retroarch:edge)"]
        end
    end

    ML <==|"RTSP/RTP Video & Input"| WOLF
    WB <==|"HTTP / Admin / Pairing"| WD
    
    WOLF -->|"Docker Socket Provisioning"| DK
    DK -->|"Spawns"| STM
    DK -->|"Spawns"| RET
    
    NV -.->|"Hardware NVENC & Vulkan"| WOLF
    NV -.->|"Hardware NVENC & Vulkan"| STM
    
    STM -->|"Isolated Virtual Display (Sway/Gamescope)"| WOLF
```

---

## 3. Quickstart: Compute Node Provisioning

### Step 1: Host Prerequisites (One-time)
Run the following on your Linux host terminal to enable Docker and user permissions:
```bash
sudo systemctl enable --now docker && sudo usermod -aG docker $USER
```

### Step 2: Initialize Cloud Gaming Node
Run the automated setup script to verify NVIDIA DRM modeset, generate the driver volume for driver `615.78.08`, and pull the base cloud images:
```bash
./deploy/setup_cloud_node.sh
```

### Step 3: Start Cloud Gaming Stack
```bash
docker compose up -d
```

### Step 4: Connect with Moonlight
1. Open Moonlight on any remote client device.
2. Add your host's Tailscale IP: `100.89.198.41`.
3. Open `http://100.89.198.41:8080` in your browser to approve the pairing PIN.
4. Select **Steam Cloud Gaming** or **RetroArch** to stream directly at 1080p 60/120 FPS.
