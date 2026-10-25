/**
 * Ryoku Cloud Gaming — Always-On Cloudflare Edge Worker (Phase 6)
 */

const OFFLINE_STATUS_CODES = new Set([502, 503, 521, 522, 523, 524, 530]);
const TUNNEL_ORIGIN_HOST = "play.vanshdev.online";

const OFFLINE_HTML = `<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1.0" />
  <title>RYOKU // HOST OFFLINE</title>
  <style>
    :root {
      --bg-base: #07080a;
      --bg-panel: #0e1014;
      --bg-input: #090a0d;
      --border-dim: #252a36;
      --volt: #c8ff00;
      --amber: #ffb800;
      --fg-0: #f8fafc;
      --fg-1: #94a3b8;
      --font-ui: "Inter", -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
      --font-mono: "JetBrains Mono", ui-monospace, monospace;
    }
    * { box-sizing: border-box; margin: 0; padding: 0; border-radius: 0 !important; }
    body {
      min-height: 100vh;
      font-family: var(--font-ui);
      background: var(--bg-base);
      color: var(--fg-0);
      display: flex;
      align-items: center;
      justify-content: center;
      padding: 24px;
    }
    .offline-card {
      max-width: 440px;
      width: 100%;
      background: var(--bg-panel);
      border: 1px solid var(--border-dim);
      border-left: 4px solid var(--amber);
      padding: 28px;
    }
    .brand-row {
      font-family: var(--font-mono);
      font-size: 11px;
      font-weight: 900;
      letter-spacing: 0.14em;
      color: var(--volt);
      margin-bottom: 14px;
    }
    .status-badge {
      display: inline-flex;
      align-items: center;
      gap: 8px;
      padding: 4px 10px;
      background: var(--bg-input);
      border: 1px solid var(--amber);
      color: var(--amber);
      font-family: var(--font-mono);
      font-size: 11px;
      font-weight: 800;
      margin-bottom: 16px;
    }
    .status-dot { width: 7px; height: 7px; background: var(--amber); }
    h1 { font-size: 20px; font-weight: 900; text-transform: uppercase; margin-bottom: 8px; }
    p.lead { font-family: var(--font-mono); color: var(--fg-1); font-size: 11px; margin-bottom: 20px; }
    button.btn {
      cursor: pointer;
      width: 100%;
      padding: 11px 16px;
      font-family: var(--font-mono);
      font-size: 12px;
      font-weight: 900;
      letter-spacing: 0.1em;
      text-transform: uppercase;
      border: 1px solid var(--volt);
      background: var(--volt);
      color: #000;
    }
    .poll-note { margin-top: 12px; font-family: var(--font-mono); font-size: 11px; color: var(--fg-1); }
  </style>
</head>
<body>
  <main class="offline-card">
    <div class="brand-row">RYOKU // CLIENT</div>
    <div>
      <div class="status-badge">
        <span class="status-dot"></span>
        <span id="status-badge-text">HOST NODE OFFLINE</span>
      </div>
    </div>
    <h1 id="headline">Gaming PC is Currently Powered Off</h1>
    <p class="lead">AUTO-CONNECTS WHEN HOST BOOTS.</p>
    <button class="btn" onclick="checkNow()">PING HOST NOW</button>
    <div class="poll-note" id="last-checked">POLLING EVERY 5S...</div>
  </main>
  <script>
    const basePrefix = window.location.pathname.startsWith('/cloudgaming') ? '/cloudgaming' : '';
    async function checkNow() {
      try {
        const res = await fetch(basePrefix + '/api/health', { cache: 'no-store' });
        const data = await res.json();
        if (res.ok && data && data.online === true) {
          window.location.href = basePrefix || '/';
          return;
        }
      } catch (_e) {}
      document.getElementById('last-checked').textContent =
        'CHECKED ' + new Date().toLocaleTimeString() + ' // OFFLINE';
    }
    setInterval(checkNow, 5000);
  </script>
</body>
</html>`;

export default {
  async fetch(request) {
    const url = new URL(request.url);
    const isApi = url.pathname.startsWith("/api/") || url.pathname.startsWith("/cloudgaming/api/");

    try {
      let upstreamRequest = request;
      if (url.hostname === "vanshdev.online" || url.hostname === "www.vanshdev.online") {
        const targetUrl = new URL(request.url);
        targetUrl.hostname = TUNNEL_ORIGIN_HOST;
        upstreamRequest = new Request(targetUrl.toString(), request);
      }

      const response = await fetch(upstreamRequest);
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
