/**
 * Ryoku Cloud Gaming — Always-On Cloudflare Edge Worker (Phase 6)
 *
 * Attach this Worker to your custom domain route (e.g. `play.yourdomain.com/*`).
 *
 * Behavior:
 * 1. When your home gaming PC (CachyOS + RTX 4060) is powered on and `cloudflared` tunnel is up,
 *    all HTTP & WebSocket requests (`/ws`, `/api/*`, `/`) pass straight through with zero overhead.
 * 2. When your gaming PC is turned off, asleep, or restarting (Cloudflare Tunnel returns
 *    502, 503, 521, 522, 523, 524, or 530), this Worker keeps the website online:
 *    - Requests to `/api/health` return a clean JSON `{"ok": false, "online": false, "status": "pc_offline"}`.
 *    - Browser page requests receive the polished Ryoku Cloud "Gaming PC is Offline" status page,
 *      which automatically polls `/api/health` every 5 seconds and redirects to the Game Library
 *      the moment your PC powers on.
 */

const OFFLINE_STATUS_CODES = new Set([502, 503, 521, 522, 523, 524, 530]);

const OFFLINE_HTML = `<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1.0" />
  <title>Ryoku Cloud — Gaming PC Offline</title>
  <style>
    :root {
      --bg-0: #060913;
      --bg-1: #0d1326;
      --card: rgba(17, 25, 48, 0.88);
      --border: rgba(99, 125, 195, 0.24);
      --text: #eef2ff;
      --muted: #94a3b8;
      --accent: #38bdf8;
      --amber: #f59e0b;
      --emerald: #10b981;
    }
    * { box-sizing: border-box; margin: 0; padding: 0; }
    body {
      min-height: 100vh;
      font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Inter, sans-serif;
      background: linear-gradient(160deg, var(--bg-0) 0%, var(--bg-1) 100%);
      color: var(--text);
      display: flex;
      align-items: center;
      justify-content: center;
      padding: 24px;
    }
    .offline-card {
      max-width: 540px;
      width: 100%;
      background: var(--card);
      border: 1px solid var(--border);
      border-radius: 20px;
      padding: 36px 32px;
      box-shadow: 0 24px 60px rgba(0, 0, 0, 0.55);
      text-align: center;
    }
    .brand-row {
      display: inline-flex;
      align-items: center;
      gap: 10px;
      margin-bottom: 22px;
      padding: 6px 14px;
      border-radius: 999px;
      background: rgba(255, 255, 255, 0.04);
      border: 1px solid rgba(255, 255, 255, 0.08);
      font-size: 13px;
      font-weight: 700;
      letter-spacing: 0.08em;
      text-transform: uppercase;
      color: var(--accent);
    }
    .status-badge {
      display: inline-flex;
      align-items: center;
      gap: 10px;
      padding: 8px 16px;
      border-radius: 999px;
      background: rgba(245, 158, 11, 0.14);
      border: 1px solid rgba(245, 158, 11, 0.38);
      color: #fcd34d;
      font-size: 13px;
      font-weight: 600;
      margin-bottom: 20px;
    }
    .status-dot {
      width: 10px;
      height: 10px;
      border-radius: 50%;
      background: var(--amber);
      box-shadow: 0 0 12px var(--amber);
    }
    h1 { font-size: 26px; font-weight: 800; margin-bottom: 12px; }
    p.lead { color: var(--muted); font-size: 15px; line-height: 1.6; margin-bottom: 24px; }
    button.btn {
      cursor: pointer;
      padding: 11px 20px;
      border-radius: 10px;
      font-size: 14px;
      font-weight: 600;
      border: 1px solid rgba(56, 189, 248, 0.4);
      background: linear-gradient(135deg, #0284c7, #2563eb);
      color: #fff;
    }
    .poll-note { margin-top: 18px; font-size: 12px; color: var(--muted); }
  </style>
</head>
<body>
  <main class="offline-card">
    <div class="brand-row">⚡ RYOKU CLOUD GAMING</div>
    <div>
      <div class="status-badge">
        <span class="status-dot"></span>
        <span id="status-badge-text">HOST PC OFFLINE / SLEEPING</span>
      </div>
    </div>
    <h1 id="headline">Gaming PC is Currently Powered Off</h1>
    <p class="lead">
      The Ryoku Cloud web portal is online at the Cloudflare Edge, but the home gaming PC
      (NVIDIA GeForce RTX 4060) is currently powered off. This page will automatically
      connect you to the Game Library as soon as the PC turns on.
    </p>
    <button class="btn" onclick="checkNow()">Check Host Status Now</button>
    <div class="poll-note" id="last-checked">Checking every 5 seconds...</div>
  </main>
  <script>
    async function checkNow() {
      try {
        const res = await fetch('/api/health', { cache: 'no-store' });
        const data = await res.json();
        if (res.ok && data && data.online === true) {
          window.location.href = '/';
          return;
        }
      } catch (_e) {}
      document.getElementById('last-checked').textContent =
        'Last checked: ' + new Date().toLocaleTimeString() + ' — Gaming PC is powered off.';
    }
    setInterval(checkNow, 5000);
  </script>
</body>
</html>`;

export default {
  async fetch(request) {
    const url = new URL(request.url);
    const isApi = url.pathname.startsWith("/api/");

    try {
      const response = await fetch(request);
      if (OFFLINE_STATUS_CODES.has(response.status)) {
        return buildOfflineResponse(isApi);
      }
      return response;
    } catch (_err) {
      return buildOfflineResponse(isApi);
    }
  },
};

function buildOfflineResponse(isApi) {
  if (isApi) {
    return new Response(
      JSON.stringify({
        ok: false,
        online: false,
        status: "pc_offline",
        server_name: "Ryoku Cloud Gaming PC",
        message: "The home gaming PC is currently powered off or offline.",
      }),
      {
        status: 503,
        headers: {
          "Content-Type": "application/json; charset=utf-8",
          "Cache-Control": "no-store",
        },
      }
    );
  }
  return new Response(OFFLINE_HTML, {
    status: 503,
    headers: {
      "Content-Type": "text/html; charset=utf-8",
      "Cache-Control": "no-store",
    },
  });
}

