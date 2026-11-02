/** Ryoku Cloud Gaming player portal. */

const CONFIG = {
  streamUrl: '/stream',
  healthUrl: '/api/health',
  statusUrl: '/api/status',
  accountUrl: '/api/account',
  adminAccountsUrl: '/api/admin/accounts',
  adminSessionUrl: '/api/admin/session',
  adminEndSessionUrl: '/api/admin/session/end',
  registerUrl: '/api/auth/register',
  loginUrl: '/api/auth/login',
  signOutUrl: '/api/account/logout',
  acquireUrl: '/api/session/acquire',
  moonlightValidateUrl: '/api/auth/validate',
  moonlightLogoutUrl: '/api/auth/logout',
  heartbeatUrl: '/api/session/heartbeat',
  releaseUrl: '/api/session/release'
};

const STREAM_PRESETS = {
  '1080p60': { height: 1080, fps: 60, bitrate: 25000 },
  '1080p60-hq': { height: 1080, fps: 60, bitrate: 35000 },
  '1080p120': { height: 1080, fps: 120, bitrate: 40000 },
  '1440p60': { height: 1440, fps: 60, bitrate: 45000 },
  '720p60': { height: 720, fps: 60, bitrate: 15000 }
};

const modal = document.getElementById('stream-modal');
const streamFrame = document.getElementById('moonlight-frame');
streamFrame?.addEventListener('load', () => window.applyRyokuStreamBranding?.(streamFrame));
const activeGameTitle = document.getElementById('active-game-title');
const statusText = document.getElementById('node-status-text');
const statusPill = document.getElementById('node-status-pill');
const heroConnection = document.querySelector('.hero-connection');
const heroStatusText = document.getElementById('hero-status-text');
const accountName = document.getElementById('account-name');
const userAvatar = document.getElementById('user-avatar');
const signInPanel = document.getElementById('sign-in-panel');
const signInStatus = document.getElementById('sign-in-status');
const gameLibrary = document.getElementById('library');
const sessionNotice = document.getElementById('session-notice');
const signOutLink = document.getElementById('sign-out-link');
const browseGamesLink = document.getElementById('browse-games-link');
const adminPanel = document.getElementById('admin-panel');
const adminAccountList = document.getElementById('admin-account-list');
const adminStatus = document.getElementById('admin-status');
const adminRefresh = document.getElementById('admin-refresh');
const adminSessionStatus = document.getElementById('admin-session-status');
const adminEndSession = document.getElementById('admin-end-session');
const authForm = document.getElementById('local-auth-form');
const authUsername = document.getElementById('auth-username');
const authPassword = document.getElementById('auth-password');
const authSubmit = document.getElementById('auth-submit');
const authModeToggle = document.getElementById('auth-mode-toggle');
const streamPresetSelect = document.getElementById('stream-preset-select');
const streamCodecSelect = document.getElementById('stream-codec-select');
const streamTransportSelect = document.getElementById('stream-transport-select');
const gamepadStatusPill = document.getElementById('gamepad-status-pill');
const adminToggleBtn = document.getElementById('admin-toggle-btn');
const consoleClock = document.getElementById('console-clock');
const spotlightIndex = document.getElementById('spotlight-index');
const spotlightBadge = document.getElementById('spotlight-badge');
const spotlightTitle = document.getElementById('spotlight-title');
const spotlightDesc = document.getElementById('spotlight-desc');
const spotlightEnv = document.getElementById('spotlight-env');
const spotlightLaunchBtn = document.getElementById('spotlight-launch-btn');
const consoleBlades = Array.from(document.querySelectorAll('.console-blade'));
let selectedTileIndex = 0;
let sessionId = null;
let sessionHeartbeat = null;
let sessionActive = false;
let authMode = 'login';
let homepageVideoVisible = false;

function initHomepageVideo() {
  const video = document.getElementById('homepage-video');
  const source = video?.querySelector('source[data-src]');
  if (!video || !source || window.matchMedia('(prefers-reduced-motion: reduce)').matches) return;
  if (!('IntersectionObserver' in window)) return;

  let loaded = false;
  const playPreview = () => {
    if (!homepageVideoVisible || document.hidden || (modal && !modal.classList.contains('hidden'))) return;
    if (!loaded) {
      source.src = source.dataset.src;
      source.removeAttribute('data-src');
      video.load();
      loaded = true;
    }
    video.play().catch(() => {});
  };

  const videoObserver = new IntersectionObserver((entries) => {
    homepageVideoVisible = entries.some((entry) => entry.isIntersecting);
    if (homepageVideoVisible) playPreview();
    else video.pause();
  }, { rootMargin: '120px' });
  videoObserver.observe(video);

  document.addEventListener('visibilitychange', () => {
    if (document.hidden) video.pause();
    else playPreview();
  });
}

try {
  initHomepageVideo();
} catch (_error) {
  // The optional homepage preview must not block sign-in or health updates.
}

function getSessionId() {
  if (sessionId) return sessionId;
  try {
    sessionId = sessionStorage.getItem('ryoku-session-id');
    if (!sessionId) {
      sessionId = crypto.randomUUID();
      sessionStorage.setItem('ryoku-session-id', sessionId);
    }
  } catch (_error) {
    sessionId = crypto.randomUUID();
  }
  return sessionId;
}

function showNotice(message, isError = false) {
  if (!sessionNotice) return;
  sessionNotice.textContent = message;
  sessionNotice.classList.toggle('error', isError);
  sessionNotice.classList.remove('hidden');
}

function clearNotice() {
  if (!sessionNotice) return;
  sessionNotice.textContent = '';
  sessionNotice.classList.add('hidden');
  sessionNotice.classList.remove('error');
}

function setClearStreamDefaults() {
  const settingsKey = 'mw-streaming-settings';
  const presetKey = streamPresetSelect?.value || localStorage.getItem('ryoku-stream-preset') || '1080p60';
  const codecKey = streamCodecSelect?.value || localStorage.getItem('ryoku-stream-codec') || 'auto';
  const transportKey = streamTransportSelect?.value || localStorage.getItem('ryoku-stream-transport') || 'all';
  const preset = STREAM_PRESETS[presetKey] || STREAM_PRESETS['1080p60'];
  try {
    if (window.indexedDB) {
      window.indexedDB.deleteDatabase('mw-pairing');
    }
  } catch (_error) {
    // Ignore IndexedDB cleanup errors.
  }
  try {
    localStorage.removeItem('mw_hevc_failed');
    localStorage.setItem('ryoku-stream-preset', presetKey);
    localStorage.setItem('ryoku-stream-codec', codecKey);
    localStorage.setItem('ryoku-stream-transport', transportKey);
    const stored = JSON.parse(localStorage.getItem(settingsKey) || '{}');
    const settings = stored && typeof stored === 'object' && !Array.isArray(stored) ? stored : {};
    Object.assign(settings, {
      stream_resolution: 'fixed',
      stream_height: preset.height,
      stream_bitrate: preset.bitrate,
      stream_bitrate_auto: false,
      stream_fps: preset.fps,
      stream_aspect: '16:9',
      stream_aspect_forced: true,
      transport_mode: transportKey,
      gaming_mode: true,
      video_codec: codecKey,
      video_enhancement: 'off',
      power_save: false
    });
    localStorage.setItem(settingsKey, JSON.stringify(settings));
  } catch (_error) {
    // MoonlightWeb still loads with its own settings if browser storage is unavailable.
  }
}

function initStreamSettingsControls() {
  try {
    const savedPreset = localStorage.getItem('ryoku-stream-preset');
    const savedCodec = localStorage.getItem('ryoku-stream-codec');
    const savedTransport = localStorage.getItem('ryoku-stream-transport');
    if (streamPresetSelect && savedPreset && STREAM_PRESETS[savedPreset]) {
      streamPresetSelect.value = savedPreset;
    }
    if (streamCodecSelect && savedCodec && ['auto', 'hevc', 'av1', 'h264'].includes(savedCodec)) {
      streamCodecSelect.value = savedCodec;
    }
    if (streamTransportSelect && savedTransport && ['all', 'webrtc-dc-udp', 'webrtc-media-udp', 'webrtc-dc-tcp', 'wss'].includes(savedTransport)) {
      streamTransportSelect.value = savedTransport;
    }
  } catch (_error) {
    // Ignore storage access errors.
  }
  streamPresetSelect?.addEventListener('change', setClearStreamDefaults);
  streamCodecSelect?.addEventListener('change', setClearStreamDefaults);
  streamTransportSelect?.addEventListener('change', setClearStreamDefaults);
  setClearStreamDefaults();
}

initStreamSettingsControls();

async function loadAccount() {
  try {
    const response = await fetch(CONFIG.accountUrl, { cache: 'no-store', credentials: 'same-origin' });
    if (!response.ok) {
      setSignedIn(false);
      return;
    }
    const account = await response.json();
    setSignedIn(true, account.username, account.role);
  } catch (_error) {
    setSignedIn(false);
    setSignInStatus('Could not reach the local sign-in service. Refresh and try again.');
  }
}

function setSignedIn(isSignedIn, username = '', role = 'player') {
  signInPanel?.classList.toggle('hidden', isSignedIn);
  gameLibrary?.classList.toggle('hidden', !isSignedIn);
  signOutLink?.classList.toggle('hidden', !isSignedIn);
  browseGamesLink?.classList.toggle('hidden', !isSignedIn);
  const isAdmin = isSignedIn && role === 'admin';
  adminToggleBtn?.classList.toggle('hidden', !isAdmin);
  if (!isAdmin) adminPanel?.classList.add('hidden');
  if (accountName) accountName.textContent = isSignedIn ? `${username}${role === 'admin' ? ' // ADMIN' : ''}` : 'LOCKED';
  if (userAvatar) userAvatar.textContent = isSignedIn ? (username.trim().charAt(0) || 'P') : 'P';
  if (isAdmin) {
    loadAdminAccounts();
    loadAdminSession();
  }
}

adminToggleBtn?.addEventListener('click', () => {
  if (!adminPanel) return;
  const hidden = adminPanel.classList.toggle('hidden');
  if (!hidden) {
    loadAdminAccounts();
    loadAdminSession();
  }
});

function selectTile(index) {
  if (!consoleBlades.length) return;
  selectedTileIndex = (index + consoleBlades.length) % consoleBlades.length;
  consoleBlades.forEach((blade, idx) => {
    const isActive = idx === selectedTileIndex;
    blade.classList.toggle('active', isActive);
    blade.setAttribute('aria-selected', isActive ? 'true' : 'false');
    if (isActive) {
      if (blade.dataset.accent) document.body.dataset.themeAccent = blade.dataset.accent;
      if (spotlightIndex && blade.dataset.index) spotlightIndex.textContent = blade.dataset.index;
      if (spotlightBadge && blade.dataset.badge) spotlightBadge.textContent = blade.dataset.badge;
      if (spotlightTitle && blade.dataset.title) spotlightTitle.textContent = blade.dataset.title;
      if (spotlightDesc && blade.dataset.desc) spotlightDesc.textContent = blade.dataset.desc;
      if (spotlightEnv && blade.dataset.env) spotlightEnv.textContent = blade.dataset.env;
      if (spotlightLaunchBtn) {
        spotlightLaunchBtn.textContent = 'Play';
      }
      blade.scrollIntoView({ behavior: 'smooth', block: 'nearest', inline: 'nearest' });
    }
  });
}

function launchSelectedTile() {
  const activeBlade = consoleBlades[selectedTileIndex];
  const appName = activeBlade?.dataset.appName || 'Steam';
  launchGame(appName);
}

consoleBlades.forEach((blade, idx) => {
  blade.addEventListener('click', () => selectTile(idx));
  blade.addEventListener('dblclick', () => {
    selectTile(idx);
    launchSelectedTile();
  });
  blade.addEventListener('focus', () => selectTile(idx));
});
selectTile(0);

async function loadAdminAccounts() {
  if (!adminAccountList || !adminStatus) return;
  adminStatus.textContent = 'Loading accounts…';
  try {
    const response = await fetch(CONFIG.adminAccountsUrl, { cache: 'no-store', credentials: 'same-origin' });
    if (!response.ok) throw new Error('Could not load accounts. Sign in again and retry.');
    const data = await response.json();
    adminAccountList.replaceChildren();
    for (const account of data.accounts || []) {
      const row = document.createElement('tr');
      for (const value of [account.username, account.id, account.role, new Date(account.created_at * 1000).toLocaleDateString()]) {
        const cell = document.createElement('td');
        cell.textContent = value;
        row.append(cell);
      }
      adminAccountList.append(row);
    }
    adminStatus.textContent = `${(data.accounts || []).length} account(s)`;
  } catch (error) {
    adminStatus.textContent = error.message || 'Could not load accounts.';
  }
}

async function loadAdminSession() {
  if (!adminSessionStatus || !adminEndSession) return;
  adminSessionStatus.textContent = 'Checking game session…';
  adminEndSession.classList.add('hidden');
  try {
    const response = await fetch(CONFIG.adminSessionUrl, { cache: 'no-store', credentials: 'same-origin' });
    if (!response.ok) throw new Error('Could not load the active game session.');
    const session = await response.json();
    if (!session.active) {
      adminSessionStatus.textContent = 'No active game session.';
      return;
    }
    const expiresAt = new Date(session.expires_at * 1000).toLocaleTimeString();
    adminSessionStatus.textContent = `${session.username} is using the game server. Lease expires at ${expiresAt}.`;
    adminEndSession.classList.remove('hidden');
  } catch (error) {
    adminSessionStatus.textContent = error.message || 'Could not load the active game session.';
  }
}

adminRefresh?.addEventListener('click', () => {
  loadAdminAccounts();
  loadAdminSession();
});
setInterval(() => {
  if (adminPanel && !adminPanel.classList.contains('hidden')) loadAdminSession();
}, 20000);

adminEndSession?.addEventListener('click', async () => {
  if (!window.confirm('End the active player session? Their stream will close.')) return;
  adminEndSession.disabled = true;
  adminSessionStatus.textContent = 'Ending active session…';
  try {
    const response = await fetch(CONFIG.adminEndSessionUrl, {
      method: 'POST',
      credentials: 'same-origin',
      cache: 'no-store'
    });
    if (!response.ok) throw new Error('Could not end the active session. Refresh and try again.');
    adminSessionStatus.textContent = 'The active session has ended.';
    adminEndSession.classList.add('hidden');
  } catch (error) {
    adminSessionStatus.textContent = error.message || 'Could not end the active session.';
  } finally {
    adminEndSession.disabled = false;
  }
});

function setSignInStatus(message) {
  if (signInStatus) signInStatus.textContent = message;
}

function setAuthMode(mode) {
  authMode = mode;
  const creatingAccount = mode === 'register';
  if (authSubmit) authSubmit.textContent = creatingAccount ? 'CREATE PROFILE' : 'AUTHENTICATE';
  if (authModeToggle) authModeToggle.textContent = creatingAccount ? 'EXISTING PROFILE' : 'NEW PROFILE';
  const signInTitle = document.getElementById('sign-in-title');
  if (signInTitle) signInTitle.textContent = creatingAccount ? 'PROVISION PROFILE' : 'UNLOCK CONSOLE';
  if (authPassword) authPassword.autocomplete = creatingAccount ? 'new-password' : 'current-password';
  setSignInStatus(creatingAccount
    ? 'SPECIFY 3-32 CHAR CALLSIGN AND 12+ CHAR PASSKEY.'
    : 'READY FOR OPERATOR INPUT.');
}

async function submitLocalAuth(event) {
  event.preventDefault();
  if (!authUsername || !authPassword) return;
  const endpoint = authMode === 'register' ? CONFIG.registerUrl : CONFIG.loginUrl;
  setSignInStatus(authMode === 'register' ? 'Creating your account…' : 'Signing in…');
  if (authSubmit) authSubmit.disabled = true;
  try {
    const response = await fetch(endpoint, {
      method: 'POST',
      credentials: 'same-origin',
      cache: 'no-store',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ username: authUsername.value, password: authPassword.value })
    });
    if (!response.ok) {
      const message = (await response.text()).trim();
      throw new Error(message || 'Sign-in failed. Check your details and try again.');
    }
    const account = await response.json();
    authPassword.value = '';
    setSignedIn(true, account.username, account.role);
    clearNotice();
  } catch (error) {
    setSignInStatus(error.message || 'Sign-in failed. Please try again.');
  } finally {
    if (authSubmit) authSubmit.disabled = false;
  }
}

authForm?.addEventListener('submit', submitLocalAuth);
authModeToggle?.addEventListener('click', () => setAuthMode(authMode === 'login' ? 'register' : 'login'));

async function acquireSession() {
  const response = await fetch(CONFIG.acquireUrl, {
    method: 'POST',
    credentials: 'same-origin',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ session_id: getSessionId() })
  });

  if (response.status === 409) {
    throw new Error('The game server is being used by another player. Please try again shortly.');
  }
  if (response.status === 503) {
    throw new Error('The private player profile is unavailable right now. Please try again later.');
  }
  if (!response.ok) {
    throw new Error('Your local account session expired. Sign in again and retry.');
  }

  sessionActive = true;
  startHeartbeat();

  const loginResponse = await fetch(CONFIG.moonlightValidateUrl, {
    method: 'POST',
    cache: 'no-store',
    credentials: 'same-origin',
    headers: { 'Content-Type': 'application/json' },
    body: '{}'
  });
  if (!loginResponse.ok) {
    throw new Error('Could not authenticate the streaming service. Please retry or contact the host.');
  }
}

function startHeartbeat() {
  if (sessionHeartbeat) clearInterval(sessionHeartbeat);
  sessionHeartbeat = setInterval(async () => {
    if (!sessionActive) return;
    try {
      const response = await fetch(CONFIG.heartbeatUrl, {
        method: 'POST',
        credentials: 'same-origin',
        cache: 'no-store'
      });
      if (!response.ok) {
        sessionActive = false;
        clearInterval(sessionHeartbeat);
        sessionHeartbeat = null;
        if (modal) modal.classList.add('hidden');
        if (streamFrame) streamFrame.src = 'about:blank';
        showNotice('Your game session expired. Reopen a launcher to continue.', true);
      }
    } catch (_error) {
      // A short network interruption should not immediately end a game session.
    }
  }, 20000);
}

async function releaseSession() {
  sessionActive = false;
  if (sessionHeartbeat) clearInterval(sessionHeartbeat);
  sessionHeartbeat = null;
  try {
    await fetch(CONFIG.moonlightLogoutUrl, {
      method: 'POST',
      credentials: 'same-origin',
      cache: 'no-store',
      keepalive: true
    });
  } catch (_error) {
    // The Moonlight auth session expires automatically if logout is unreachable.
  }
  try {
    await fetch(CONFIG.releaseUrl, {
      method: 'POST',
      credentials: 'same-origin',
      cache: 'no-store',
      keepalive: true
    });
  } catch (_error) {
    // The server lease expires automatically if the browser disappears.
  }
}

async function launchGame(appName) {
  if (!modal || !streamFrame) return;
  clearNotice();

  try {
    await acquireSession();
  } catch (error) {
    if (sessionActive) await releaseSession();
    showNotice(error.message || 'Could not reserve a game session.', true);
    return;
  }

  activeGameTitle.textContent = appName;
  modal.classList.remove('hidden');
  document.getElementById('homepage-video')?.pause();
  setClearStreamDefaults();
  try {
    sessionStorage.setItem('ryoku-launch-app', appName);
    localStorage.setItem('ryoku-last-app', appName);
  } catch (_error) {
    // Auto-launch falls back to manual click if sessionStorage is unavailable.
  }
  streamFrame.src = CONFIG.streamUrl;
  setTimeout(() => {
    try {
      streamFrame.contentWindow?.focus();
    } catch (_error) {
      // Focus can be restricted by the browser.
    }
  }, 400);
}

function toggleStreamStats() {
  try {
    streamFrame?.contentWindow?.postMessage({ type: 'ryoku-toggle-stats' }, window.location.origin);
    streamFrame?.contentWindow?.focus();
  } catch (_error) {
    // Ignore cross-frame messaging errors.
  }
}

window.addEventListener('message', (event) => {
  if (event.origin !== window.location.origin) return;
  if (event.data?.type === 'ryoku-stream-quit') {
    closeStream();
  }
});

function closeStream() {
  try {
    sessionStorage.removeItem('ryoku-launch-app');
  } catch (_error) {
    // Ignore storage errors.
  }
  if (modal) modal.classList.add('hidden');
  if (streamFrame) streamFrame.src = 'about:blank';
  if (document.fullscreenElement) document.exitFullscreen().catch(() => {});
  if (sessionActive) releaseSession();
  const video = document.getElementById('homepage-video');
  if (video && homepageVideoVisible && !document.hidden) video.play().catch(() => {});
}

document.getElementById('stream-popout-btn')?.addEventListener('click', () => {
  sessionActive = false;
  if (sessionHeartbeat) clearInterval(sessionHeartbeat);
  sessionHeartbeat = null;
  if (modal) modal.classList.add('hidden');
  if (streamFrame) streamFrame.src = 'about:blank';
  if (document.fullscreenElement) document.exitFullscreen().catch(() => {});
  showNotice('Stream opened in a new tab. Close that tab when finished to release your session.');
});

function toggleFullscreen() {
  if (!document.fullscreenElement) {
    const target = modal || streamFrame;
    if (target?.requestFullscreen) target.requestFullscreen().catch(() => {});
  } else {
    document.exitFullscreen().catch(() => {});
  }
}

document.addEventListener('keydown', (event) => {
  if (event.key === 'Escape' && modal && !modal.classList.contains('hidden') && !document.fullscreenElement) {
    closeStream();
    return;
  }
  if (event.ctrlKey && event.altKey && event.shiftKey && event.key.toLowerCase() === 'q') {
    closeStream();
    return;
  }
  const activeTag = document.activeElement?.tagName;
  if (activeTag === 'INPUT' || activeTag === 'SELECT' || activeTag === 'TEXTAREA') return;
  if (!gameLibrary || gameLibrary.classList.contains('hidden')) return;
  if (modal && !modal.classList.contains('hidden')) return;
  if (event.key === 'ArrowLeft') {
    event.preventDefault();
    selectTile(selectedTileIndex - 1);
  } else if (event.key === 'ArrowRight') {
    event.preventDefault();
    selectTile(selectedTileIndex + 1);
  } else if (event.key === 'Enter' && document.activeElement?.tagName !== 'BUTTON') {
    event.preventDefault();
    launchSelectedTile();
  }
});

async function checkHostHealth() {
  try {
    const startedAt = performance.now();
    const response = await fetch(CONFIG.statusUrl, { cache: 'no-store', credentials: 'same-origin' });
    if (!response.ok) throw new Error('Status endpoint returned an error');
    const rttMs = Math.max(1, Math.round(performance.now() - startedAt));
    const data = await response.json();
    const online = Boolean(data.online);
    const busyOther = online && Boolean(data.busy) && !data.you;
    const state = !online ? 'offline' : (busyOther ? 'busy' : 'online');
    if (statusText) {
      statusText.textContent = !online
        ? 'NODE OFFLINE'
        : (busyOther ? `BUSY // ${rttMs} MS` : `ONLINE // ${rttMs} MS`);
    }
    if (heroStatusText) {
      heroStatusText.textContent = !online
        ? 'LINK OFFLINE'
        : (busyOther
          ? `SLOT LOCKED // ${rttMs} MS`
          : (data.you ? `ACTIVE LEASE // ${rttMs} MS` : `SLOT READY // ${rttMs} MS`));
    }
    if (statusPill) statusPill.dataset.state = state;
    if (heroConnection) heroConnection.dataset.state = state;
  } catch (_error) {
    if (statusText) statusText.textContent = 'TELEMETRY LOST';
    if (heroStatusText) heroStatusText.textContent = 'LINK OFFLINE';
    if (statusPill) statusPill.dataset.state = 'offline';
    if (heroConnection) heroConnection.dataset.state = 'offline';
  }
}

if (signOutLink) {
  signOutLink.addEventListener('click', async (event) => {
    event.preventDefault();
    if (sessionActive) await releaseSession();
    try {
      await fetch(CONFIG.signOutUrl, { method: 'POST', credentials: 'same-origin', cache: 'no-store' });
    } finally {
      sessionActive = false;
      setSignedIn(false);
      if (authPassword) authPassword.value = '';
    }
  });
}

window.addEventListener('pagehide', () => {
  if (sessionActive) {
    fetch(CONFIG.releaseUrl, { method: 'POST', credentials: 'same-origin', keepalive: true }).catch(() => {});
  }
});

function updateGamepadStatus() {
  if (!gamepadStatusPill || typeof navigator.getGamepads !== 'function') return;
  try {
    const pads = Array.from(navigator.getGamepads() || []).filter(Boolean);
    gamepadStatusPill.dataset.connected = pads.length > 0 ? 'true' : 'false';
  } catch (_error) {
    // Ignore gamepad query errors.
  }
}

let lastPadNavAt = 0;
function pollGamepadConsoleNav() {
  if (typeof navigator.getGamepads === 'function'
      && gameLibrary && !gameLibrary.classList.contains('hidden')
      && (!modal || modal.classList.contains('hidden'))) {
    try {
      const pad = Array.from(navigator.getGamepads() || []).find(Boolean);
      const now = performance.now();
      if (pad && now - lastPadNavAt > 240) {
        const leftPressed = pad.buttons?.[14]?.pressed || (pad.axes?.[0] ?? 0) < -0.6;
        const rightPressed = pad.buttons?.[15]?.pressed || (pad.axes?.[0] ?? 0) > 0.6;
        const aPressed = pad.buttons?.[0]?.pressed;
        if (leftPressed) {
          selectTile(selectedTileIndex - 1);
          lastPadNavAt = now;
        } else if (rightPressed) {
          selectTile(selectedTileIndex + 1);
          lastPadNavAt = now;
        } else if (aPressed) {
          lastPadNavAt = now + 600;
          launchSelectedTile();
        }
      }
    } catch (_error) {
      // Ignore gamepad read errors.
    }
  }
  requestAnimationFrame(pollGamepadConsoleNav);
}

function updateConsoleClock() {
  if (!consoleClock) return;
  const now = new Date();
  const hours = String(now.getHours()).padStart(2, '0');
  const mins = String(now.getMinutes()).padStart(2, '0');
  consoleClock.textContent = `${hours}:${mins}`;
}

window.addEventListener('gamepadconnected', updateGamepadStatus);
window.addEventListener('gamepaddisconnected', updateGamepadStatus);
updateGamepadStatus();
updateConsoleClock();
setInterval(updateConsoleClock, 10000);
requestAnimationFrame(pollGamepadConsoleNav);

loadAccount();
checkHostHealth();
setInterval(checkHostHealth, 20000);
