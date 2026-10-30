/**
 * Ryoku Cloud Gaming - Web Portal Controller
 * Domain: vanshdev.online
 */

const CONFIG = {
  // Directly use the /stream endpoint proxied by Caddy
  streamUrl: '/stream',
  domain: 'vanshdev.online'
};

const modal = document.getElementById('stream-modal');
const streamFrame = document.getElementById('moonlight-frame');
const activeGameTitle = document.getElementById('active-game-title');

/**
 * Launch an in-browser streaming session
 * @param {string} appName - e.g. "Steam Cloud Gaming", "Heroic Games Launcher", "Test ball"
 */
function launchGame(appName) {
  if (!modal || !streamFrame) return;

  activeGameTitle.textContent = appName;
  modal.classList.remove('hidden');

  // Load Moonlight Web inside the iframe
  // If the frame is already pointing to the stream, don't reload completely
  if (!streamFrame.src || streamFrame.src === 'about:blank' || !streamFrame.src.includes(window.location.hostname)) {
    streamFrame.src = CONFIG.streamUrl;
  }

  // Request pointer lock / focus
  setTimeout(() => {
    try {
      streamFrame.contentWindow?.focus();
    } catch (e) {
      // Cross-origin iframe focus restriction fallback
    }
  }, 500);
}

/**
 * Close active stream modal
 */
function closeStream() {
  if (!modal) return;
  modal.classList.add('hidden');
  if (document.fullscreenElement) {
    document.exitFullscreen().catch(() => {});
  }
}

/**
 * Toggle browser fullscreen for gaming immersion
 */
function toggleFullscreen() {
  if (!document.fullscreenElement) {
    modal.requestFullscreen().catch((err) => {
      console.warn('Fullscreen request failed:', err);
    });
  } else {
    document.exitFullscreen().catch(() => {});
  }
}

// Global hotkeys (ESC to exit fullscreen, Ctrl+Alt+Shift+Q to close stream)
document.addEventListener('keydown', (e) => {
  if (e.key === 'Escape' && !modal.classList.contains('hidden')) {
    if (!document.fullscreenElement) {
      closeStream();
    }
  }
  if (e.ctrlKey && e.altKey && e.shiftKey && (e.key === 'Q' || e.key === 'q')) {
    closeStream();
  }
});

// Gamepad API Listener
window.addEventListener('gamepadconnected', (e) => {
  console.log('Gamepad connected:', e.gamepad.id);
  const statusIndicator = document.querySelector('.status-text');
  if (statusIndicator) {
    statusIndicator.textContent = `RTX 4060 READY (GAMEPAD CONNECTED)`;
  }
});

window.addEventListener('gamepaddisconnected', (e) => {
  console.log('Gamepad disconnected:', e.gamepad.id);
  const statusIndicator = document.querySelector('.status-text');
  if (statusIndicator) {
    statusIndicator.textContent = `RTX 4060 NODE ONLINE`;
  }
});

console.log('Ryoku Cloud Gaming web portal initialized for', CONFIG.domain);
