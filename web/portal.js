/** Ryoku Cloud Gaming player portal. */

const CONFIG = {
  streamUrl: '/stream',
  healthUrl: '/api/health',
  accountUrl: '/api/account',
  adminAccountsUrl: '/api/admin/accounts',
  registerUrl: '/api/auth/register',
  loginUrl: '/api/auth/login',
  signOutUrl: '/api/account/logout',
  acquireUrl: '/api/session/acquire',
  moonlightValidateUrl: '/api/auth/validate',
  moonlightLogoutUrl: '/api/auth/logout',
  heartbeatUrl: '/api/session/heartbeat',
  releaseUrl: '/api/session/release'
};

const modal = document.getElementById('stream-modal');
const streamFrame = document.getElementById('moonlight-frame');
const activeGameTitle = document.getElementById('active-game-title');
const statusText = document.getElementById('node-status-text');
const accountName = document.getElementById('account-name');
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
const authForm = document.getElementById('local-auth-form');
const authUsername = document.getElementById('auth-username');
const authPassword = document.getElementById('auth-password');
const authSubmit = document.getElementById('auth-submit');
const authModeToggle = document.getElementById('auth-mode-toggle');
let sessionId = null;
let sessionHeartbeat = null;
let sessionActive = false;
let authMode = 'login';

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
  const configuredKey = 'ryoku-low-latency-default-v2';
  try {
    if (localStorage.getItem(configuredKey) === '1') return;
    const stored = JSON.parse(localStorage.getItem(settingsKey) || '{}');
    const settings = stored && typeof stored === 'object' && !Array.isArray(stored) ? stored : {};
    const has1080p60Quality = settings.stream_resolution === 'fixed'
      && Number(settings.stream_height) >= 1080
      && Number(settings.stream_fps) >= 60;
    if (!has1080p60Quality) {
      Object.assign(settings, {
        stream_resolution: 'fixed',
        stream_height: 1080,
        stream_bitrate: 20000,
        stream_fps: 60
      });
    }
    Object.assign(settings, {
      stream_bitrate_auto: true,
      video_enhancement: 'off'
    });
    localStorage.setItem(settingsKey, JSON.stringify(settings));
    localStorage.setItem(configuredKey, '1');
  } catch (_error) {
    // MoonlightWeb still loads with its own settings if browser storage is unavailable.
  }
}

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
  adminPanel?.classList.toggle('hidden', !isSignedIn || role !== 'admin');
  if (accountName) accountName.textContent = isSignedIn ? `${username}${role === 'admin' ? ' · Admin' : ''}` : 'Signed out';
  if (isSignedIn && role === 'admin') loadAdminAccounts();
}

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

adminRefresh?.addEventListener('click', loadAdminAccounts);

function setSignInStatus(message) {
  if (signInStatus) signInStatus.textContent = message;
}

function setAuthMode(mode) {
  authMode = mode;
  const creatingAccount = mode === 'register';
  if (authSubmit) authSubmit.textContent = creatingAccount ? 'Create Account' : 'Sign In';
  if (authModeToggle) authModeToggle.textContent = creatingAccount ? 'Back to sign in' : 'Create an account';
  if (authPassword) authPassword.autocomplete = creatingAccount ? 'new-password' : 'current-password';
  setSignInStatus(creatingAccount
    ? 'Choose a 3-32 character username and a password with at least 12 characters.'
    : 'Sign in with your local player account.');
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

  activeGameTitle.textContent = `Select ${appName} in the stream menu`;
  modal.classList.remove('hidden');
  setClearStreamDefaults();
  streamFrame.src = CONFIG.streamUrl;
  setTimeout(() => {
    try {
      streamFrame.contentWindow?.focus();
    } catch (_error) {
      // Focus can be restricted by the browser.
    }
  }, 400);
}

function closeStream() {
  if (modal) modal.classList.add('hidden');
  if (streamFrame) streamFrame.src = 'about:blank';
  if (document.fullscreenElement) document.exitFullscreen().catch(() => {});
  if (sessionActive) releaseSession();
}

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
  }
  if (event.ctrlKey && event.altKey && event.shiftKey && event.key.toLowerCase() === 'q') {
    closeStream();
  }
});

window.addEventListener('gamepadconnected', () => {
  if (statusText) statusText.textContent = 'Controller ready';
});

window.addEventListener('gamepaddisconnected', () => {
  if (statusText) statusText.textContent = 'Online';
});

async function checkHostHealth() {
  try {
    const response = await fetch(CONFIG.healthUrl, { cache: 'no-store' });
    if (!response.ok) return;
    const data = await response.json();
    if (statusText) statusText.textContent = data.online ? 'Online' : 'Offline';
  } catch (_error) {
    if (statusText) statusText.textContent = 'Status unavailable';
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

loadAccount();
checkHostHealth();
setInterval(checkHostHealth, 20000);
