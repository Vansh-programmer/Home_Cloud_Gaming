/**
 * Ryoku Cloud Gaming — Always-On Cloudflare Edge Worker (Phase 6)
 *
 * Sits in front of the Cloudflare Tunnel.
 * When the Gaming PC is OFF / sleeping, intercepts 502/503/521 errors
 * and serves the offline dashboard with ESP8266 remote power-on capability.
 */

const OFFLINE_STATUS_CODES = new Set([502, 503, 521, 522, 523, 524, 530]);
const TUNNEL_ORIGIN_HOST = "play.vanshdev.online";

export default {
  async fetch(request, env) {
    const url = new URL(request.url);
    const isApi = url.pathname.startsWith("/api/") || url.pathname.startsWith("/cloudgaming/api/");

    // Handle Edge Power-On proxy so browsers don't encounter ad-block or CORS issues
    if (request.method === "POST" && (url.pathname.endsWith("/api/power_on") || url.pathname.endsWith("/api/power"))) {
      try {
        const body = await request.json();
        const token = body.token || (env && env.TELEGRAM_BOT_TOKEN);
        const chatId = body.chat_id || (env && env.TELEGRAM_CHAT_ID);
        const command = body.command || "/power";

        if (!token || !chatId) {
          return new Response(JSON.stringify({ ok: false, error: "Missing bot token or chat ID" }), {
            status: 400,
            headers: { "Content-Type": "application/json", "Access-Control-Allow-Origin": "*" }
          });
        }

        const tgUrl = `https://api.telegram.org/bot${encodeURIComponent(token)}/sendMessage?chat_id=${encodeURIComponent(chatId)}&text=${encodeURIComponent(command)}`;
        const tgRes = await fetch(tgUrl);
        const tgData = await tgRes.json();

        return new Response(JSON.stringify({ ok: tgRes.ok, telegram: tgData }), {
          status: tgRes.ok ? 200 : 500,
          headers: { "Content-Type": "application/json", "Access-Control-Allow-Origin": "*" }
        });
      } catch (err) {
        return new Response(JSON.stringify({ ok: false, error: err.message }), {
          status: 500,
          headers: { "Content-Type": "application/json", "Access-Control-Allow-Origin": "*" }
        });
      }
    }

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

const OFFLINE_HTML = `<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1.0" />
  <title>RYOKU // HOST OFFLINE</title>
  <style>
    :root {
      --bg-base: #090a0d;
      --bg-panel: #111318;
      --bg-input: #0c0e12;
      --border-dim: #222631;
      --border-bright: #3a4154;
      --accent: #c8ff00;
      --accent-glow: rgba(200, 255, 0, 0.25);
      --warn: #ffb800;
      --warn-glow: rgba(255, 184, 0, 0.2);
      --danger: #ff3344;
      --ok: #00e676;
      --ok-glow: rgba(0, 230, 118, 0.25);
      --text-main: #f1f5f9;
      --text-sub: #94a3b8;
      --font-ui: "Inter", -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
      --font-mono: "JetBrains Mono", monospace;
    }
    * { box-sizing: border-box; margin: 0; padding: 0; }
    body {
      min-height: 100vh;
      font-family: var(--font-ui);
      background: var(--bg-base);
      color: var(--text-main);
      display: flex;
      align-items: center;
      justify-content: center;
      padding: 20px;
      line-height: 1.4;
    }
    .offline-card {
      max-width: 480px;
      width: 100%;
      background: var(--bg-panel);
      border: 1px solid var(--border-dim);
      border-top: 3px solid var(--warn);
      padding: 28px;
      box-shadow: 0 16px 36px rgba(0, 0, 0, 0.5);
    }
    .brand-row {
      display: flex;
      align-items: center;
      justify-content: space-between;
      margin-bottom: 16px;
    }
    .brand-title {
      font-family: var(--font-mono);
      font-size: 11px;
      font-weight: 800;
      letter-spacing: 0.12em;
      color: var(--accent);
    }
    .settings-btn {
      background: transparent;
      border: 1px solid var(--border-dim);
      color: var(--text-sub);
      cursor: pointer;
      font-family: var(--font-mono);
      font-size: 11px;
      padding: 3px 8px;
    }
    .status-badge {
      display: inline-flex;
      align-items: center;
      gap: 8px;
      padding: 4px 10px;
      background: var(--bg-input);
      border: 1px solid var(--warn);
      color: var(--warn);
      font-family: var(--font-mono);
      font-size: 11px;
      font-weight: 800;
      margin-bottom: 16px;
    }
    .status-dot {
      width: 7px;
      height: 7px;
      background: var(--warn);
      box-shadow: 0 0 8px var(--warn-glow);
      animation: pulse 2s infinite ease-in-out;
    }
    @keyframes pulse {
      0%, 100% { opacity: 1; transform: scale(1); }
      50% { opacity: 0.4; transform: scale(0.85); }
    }
    .status-badge.booting {
      border-color: var(--accent);
      color: var(--accent);
    }
    .status-badge.booting .status-dot {
      background: var(--accent);
      box-shadow: 0 0 10px var(--accent-glow);
    }
    .status-badge.online {
      border-color: var(--ok);
      color: var(--ok);
    }
    .status-badge.online .status-dot {
      background: var(--ok);
      box-shadow: 0 0 10px var(--ok-glow);
      animation: none;
    }
    h1 {
      font-size: 22px;
      font-weight: 900;
      text-transform: uppercase;
      letter-spacing: -0.02em;
      margin-bottom: 6px;
    }
    p.lead {
      color: var(--text-sub);
      font-family: var(--font-mono);
      font-size: 11px;
      letter-spacing: 0.04em;
      margin-bottom: 20px;
    }
    .specs-box {
      background: var(--bg-input);
      border: 1px solid var(--border-dim);
      padding: 12px 14px;
      margin-bottom: 20px;
      display: grid;
      grid-template-columns: 1fr 1fr;
      gap: 10px;
      font-family: var(--font-mono);
      font-size: 11px;
    }
    .spec-item span.label {
      display: block;
      color: var(--text-sub);
      font-size: 10px;
      margin-bottom: 2px;
      text-transform: uppercase;
    }
    .spec-item span.value {
      font-weight: 700;
      color: var(--text-main);
    }
    .actions-grid {
      display: flex;
      flex-direction: column;
      gap: 10px;
      margin-bottom: 16px;
    }
    button.btn {
      cursor: pointer;
      width: 100%;
      padding: 12px 16px;
      font-family: var(--font-mono);
      font-size: 12px;
      font-weight: 800;
      letter-spacing: 0.08em;
      text-transform: uppercase;
      border: 1px solid transparent;
      display: flex;
      align-items: center;
      justify-content: center;
      gap: 8px;
    }
    button.btn-primary {
      background: var(--accent);
      color: #000;
      border-color: var(--accent);
    }
    button.btn-primary:hover {
      box-shadow: 0 0 16px var(--accent-glow);
    }
    button.btn-outline {
      background: transparent;
      border-color: var(--border-bright);
      color: var(--text-main);
    }
    button.btn-danger-outline {
      background: transparent;
      border-color: rgba(255, 51, 68, 0.4);
      color: var(--danger);
      font-size: 10px;
      padding: 8px 12px;
    }
    .status-log {
      background: var(--bg-input);
      border: 1px solid var(--border-dim);
      padding: 10px 12px;
      font-family: var(--font-mono);
      font-size: 11px;
      color: var(--text-sub);
      min-height: 38px;
      display: flex;
      align-items: center;
      word-break: break-all;
    }
    .status-log.highlight {
      color: var(--accent);
      border-color: rgba(200, 255, 0, 0.4);
    }
    .status-log.error {
      color: var(--danger);
      border-color: rgba(255, 51, 68, 0.4);
    }
    .config-panel {
      display: none;
      background: var(--bg-input);
      border: 1px solid var(--border-dim);
      padding: 16px;
      margin-top: 14px;
      margin-bottom: 14px;
    }
    .config-panel.open { display: block; }
    .config-title {
      font-family: var(--font-mono);
      font-size: 11px;
      font-weight: 800;
      color: var(--accent);
      text-transform: uppercase;
      margin-bottom: 10px;
    }
    .config-field { margin-bottom: 12px; }
    .config-field label {
      display: block;
      font-family: var(--font-mono);
      font-size: 10px;
      color: var(--text-sub);
      text-transform: uppercase;
      margin-bottom: 4px;
    }
    .config-field input {
      width: 100%;
      background: #000;
      border: 1px solid var(--border-dim);
      color: var(--text-main);
      padding: 8px 10px;
      font-family: var(--font-mono);
      font-size: 11px;
      outline: none;
    }
    .config-actions { display: flex; gap: 8px; margin-top: 10px; }
  </style>
</head>
<body>
  <main class="offline-card">
    <div class="brand-row">
      <span class="brand-title">RYOKU // CLOUD CLIENT</span>
      <button class="settings-btn" id="toggle-config-btn" type="button">⚙️ SWITCH CONFIG</button>
    </div>

    <div>
      <div id="status-badge" class="status-badge">
        <span class="status-dot"></span>
        <span id="status-badge-text">HOST NODE OFFLINE</span>
      </div>
    </div>

    <h1 id="headline">Gaming PC is Powered Off</h1>
    <p class="lead" id="subtext">PRESS TURN ON TO BOOT VIA HARDWARE SWITCH.</p>

    <div class="config-panel" id="config-panel">
      <div class="config-title">⚡ ESP8266 Switch Settings</div>
      <div class="config-field">
        <label for="cfg-bot-token">Telegram Bot Token</label>
        <input type="password" id="cfg-bot-token" placeholder="123456789:ABCdefGhIJKlmNoPQRsTUVwxyZ" autocomplete="off" />
      </div>
      <div class="config-field">
        <label for="cfg-chat-id">Telegram Chat ID (Numeric)</label>
        <input type="text" id="cfg-chat-id" placeholder="987654321" autocomplete="off" />
      </div>
      <div class="config-actions">
        <button class="btn btn-primary" id="save-config-btn" type="button" style="padding:8px 12px; font-size:11px;">SAVE SETTINGS</button>
      </div>
    </div>

    <div class="specs-box">
      <div class="spec-item">
        <span class="label">Hardware Switch</span>
        <span class="value">ESP8266 (DIRECT)</span>
      </div>
      <div class="spec-item">
        <span class="label">Poll Interval</span>
        <span class="value" id="poll-counter">5 SECONDS</span>
      </div>
    </div>

    <div class="actions-grid">
      <button class="btn btn-primary" id="power-on-btn" type="button">
        <span id="power-btn-text">⚡ TURN ON PC</span>
      </button>

      <div style="display:grid; grid-template-columns: 1fr 1fr; gap:10px;">
        <button class="btn btn-outline" id="check-now-btn" type="button">PING HOST NOW</button>
        <button class="btn btn-danger-outline" id="force-off-btn" type="button">⚠️ FORCE 5s OFF</button>
      </div>
    </div>

    <div class="status-log" id="last-checked">READY. WAITING FOR COMMAND...</div>
  </main>

  <script>
    (function () {
      const STORAGE_KEY_TOKEN = "ryoku_esp_bot_token";
      const STORAGE_KEY_CHAT  = "ryoku_esp_chat_id";

      const badge = document.getElementById("status-badge");
      const badgeText = document.getElementById("status-badge-text");
      const headline = document.getElementById("headline");
      const subtext = document.getElementById("subtext");
      const lastChecked = document.getElementById("last-checked");
      const checkBtn = document.getElementById("check-now-btn");
      const powerBtn = document.getElementById("power-on-btn");
      const powerBtnText = document.getElementById("power-btn-text");
      const forceOffBtn = document.getElementById("force-off-btn");
      const toggleConfigBtn = document.getElementById("toggle-config-btn");
      const configPanel = document.getElementById("config-panel");
      const cfgBotToken = document.getElementById("cfg-bot-token");
      const cfgChatId = document.getElementById("cfg-chat-id");
      const saveConfigBtn = document.getElementById("save-config-btn");
      const pollCounter = document.getElementById("poll-counter");

      let pollTimer = null;
      let isBooting = false;
      let bootStartTimestamp = 0;
      const basePrefix = window.location.pathname.startsWith("/cloudgaming") ? "/cloudgaming" : "";

      function loadSettings() {
        const savedToken = localStorage.getItem(STORAGE_KEY_TOKEN) || "";
        const savedChat = localStorage.getItem(STORAGE_KEY_CHAT) || "";
        if (savedToken) cfgBotToken.value = savedToken;
        if (savedChat) cfgChatId.value = savedChat;
        return { token: savedToken, chatId: savedChat };
      }

      function saveSettings() {
        const token = cfgBotToken.value.trim();
        const chatId = cfgChatId.value.trim();
        if (!token || !chatId) {
          logMessage("Please enter both Bot Token and Chat ID.", "error");
          return false;
        }
        localStorage.setItem(STORAGE_KEY_TOKEN, token);
        localStorage.setItem(STORAGE_KEY_CHAT, chatId);
        logMessage("✓ Switch settings saved!", "highlight");
        configPanel.classList.remove("open");
        return true;
      }

      function logMessage(msg, type = "normal") {
        lastChecked.textContent = msg;
        lastChecked.className = "status-log " + (type === "highlight" ? "highlight" : type === "error" ? "error" : "");
      }

      async function checkHealth() {
        try {
          const res = await fetch(basePrefix + "/api/health", { cache: "no-store" });
          const data = await res.json();
          if (res.ok && data && data.online === true) {
            badge.className = "status-badge online";
            badgeText.textContent = "HOST ONLINE";
            headline.textContent = "HOST NODE ONLINE";
            subtext.textContent = "REDIRECTING...";
            logMessage("✓ Host node is reachable! Redirecting...", "highlight");
            clearInterval(pollTimer);
            setTimeout(() => { window.location.href = basePrefix || "/"; }, 500);
            return;
          }
        } catch (_err) {}

        const now = new Date().toLocaleTimeString();
        if (isBooting) {
          const elapsedSec = Math.floor((Date.now() - bootStartTimestamp) / 1000);
          logMessage('BOOTING PC... WAITING FOR HOST (' + elapsedSec + 's) // CHECKED ' + now);
        } else {
          logMessage('CHECKED ' + now + ' // HOST OFFLINE');
        }
      }

      function setPollRate(ms) {
        pollCounter.textContent = (ms / 1000).toFixed(0) + ' SECONDS';
        if (pollTimer) clearInterval(pollTimer);
        pollTimer = setInterval(checkHealth, ms);
      }

      async function sendTelegramCommand(commandText, userFeedback) {
        const { token, chatId } = loadSettings();
        if (!token || !chatId) {
          configPanel.classList.add("open");
          logMessage("⚠️ Enter Telegram Bot Token & Chat ID first.", "error");
          return false;
        }

        logMessage("Relaying command [" + commandText + "] to ESP8266...", "highlight");
        try {
          let delivered = false;
          try {
            const edgeRes = await fetch(basePrefix + "/api/power_on", {
              method: "POST",
              headers: { "Content-Type": "application/json" },
              body: JSON.stringify({ token, chat_id: chatId, command: commandText })
            });
            if (edgeRes.ok) delivered = true;
          } catch (_edgeErr) {}

          if (!delivered) {
            const tgUrl = 'https://api.telegram.org/bot' + encodeURIComponent(token) + '/sendMessage?chat_id=' + encodeURIComponent(chatId) + '&text=' + encodeURIComponent(commandText);
            await fetch(tgUrl, { mode: "no-cors" });
          }
          logMessage(userFeedback, "highlight");
          return true;
        } catch (err) {
          logMessage("Error sending command: " + err.message, "error");
          return false;
        }
      }

      toggleConfigBtn.addEventListener("click", () => configPanel.classList.toggle("open"));
      saveConfigBtn.addEventListener("click", saveSettings);

      powerBtn.addEventListener("click", async () => {
        const { token, chatId } = loadSettings();
        if (!token || !chatId) {
          configPanel.classList.add("open");
          logMessage("⚠️ Enter your Bot Token & Chat ID below first.", "error");
          return;
        }

        powerBtn.disabled = true;
        powerBtnText.textContent = "SIGNALING...";

        const success = await sendTelegramCommand("/power", "⚡ Power pulse sent to ESP8266! Host PC is powering on...");
        if (success) {
          isBooting = true;
          bootStartTimestamp = Date.now();
          badge.className = "status-badge booting";
          badgeText.textContent = "BOOT SIGNAL SENT";
          headline.textContent = "Powering Up Gaming PC...";
          subtext.textContent = "PULSED MOTHERBOARD PWR_SW. AUTO-CONNECTING...";
          setPollRate(2000);
        }

        setTimeout(() => {
          powerBtn.disabled = false;
          powerBtnText.textContent = "⚡ TURN ON PC (RE-PULSE)";
        }, 6000);
      });

      forceOffBtn.addEventListener("click", async () => {
        if (!confirm("⚠️ Force power-off cuts power immediately (5s hold). Proceed?")) return;
        await sendTelegramCommand("/force_off", "⚠️ Force power-off signal sent (5s hold).");
      });

      checkBtn.addEventListener("click", () => {
        logMessage("PINGING HOST NODE...");
        checkHealth();
      });

      loadSettings();
      setPollRate(5000);
      checkHealth();
    })();
  </script>
</body>
</html>`;

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
