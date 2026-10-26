/* ==========================================================================
   Ryoku Cloud Gaming — Unified Product Web App & In-Stream WebRTC Client (Phase 4)
   ========================================================================== */

(() => {
  const BASE_PREFIX = window.location.pathname.startsWith('/cloudgaming') ? '/cloudgaming' : '';
  const _origFetch = window.fetch.bind(window);
  window.fetch = (input, init) => {
    init = init || {};
    if (typeof input === 'string' && input.startsWith('/api/')) {
      input = BASE_PREFIX + input;
    }
    const token = localStorage.getItem('ryoku_auth_token');
    if (token) {
      init.headers = init.headers || {};
      if (init.headers instanceof Headers) {
        if (!init.headers.has('Authorization')) {
          init.headers.set('Authorization', `Bearer ${token}`);
        }
      } else if (Array.isArray(init.headers)) {
        if (!init.headers.some(([k]) => k.toLowerCase() === 'authorization')) {
          init.headers.push(['Authorization', `Bearer ${token}`]);
        }
      } else if (typeof init.headers === 'object' && !init.headers['Authorization']) {
        init.headers['Authorization'] = `Bearer ${token}`;
      }
    }
    return _origFetch(input, init);
  };

  // Top-level Views
  const authView = document.getElementById('auth-view');
  const appView = document.getElementById('app-view');
  const navCenter = document.getElementById('nav-center');
  const navRight = document.getElementById('nav-right');
  const navUsername = document.getElementById('nav-username');
  const serverDot = document.getElementById('server-dot');
  const serverPillText = document.getElementById('server-pill-text');
  const btnResumeNav = document.getElementById('btn-resume-nav');

  // Navigation Tabs & Sections
  const tabBtnLibrary = document.getElementById('nav-tab-library');
  const tabBtnProfile = document.getElementById('nav-tab-profile');
  const tabBtnAdmin = document.getElementById('nav-tab-admin');
  const secLibrary = document.getElementById('section-library');
  const secProfile = document.getElementById('section-profile');
  const secAdmin = document.getElementById('section-admin');

  // Auth Elements
  const authTabLogin = document.getElementById('auth-tab-login');
  const authTabInvite = document.getElementById('auth-tab-invite');
  const formLogin = document.getElementById('form-login');
  const formInvite = document.getElementById('form-invite');
  const authError = document.getElementById('auth-error');

  // Hero & Library Elements
  const heroTitle = document.getElementById('hero-title');
  const heroTag = document.getElementById('hero-tag');
  const heroDesc = document.getElementById('hero-desc');
  const heroBtnPlay = document.getElementById('hero-btn-play');
  const launchResolution = document.getElementById('launch-resolution');
  const launchQuality = document.getElementById('launch-quality');
  const heroBadgeUser = document.getElementById('hero-badge-user');
  const heroBadgeSteam = document.getElementById('hero-badge-steam');
  const heroBadgeSave = document.getElementById('hero-badge-save');

  const searchInput = document.getElementById('game-search-input');
  const filterChips = document.querySelectorAll('.filter-chip');
  const gamesGrid = document.getElementById('games-grid');

  // Profile Elements
  const profileDetails = document.getElementById('profile-details');

  // Admin Elements
  const btnGenInvite = document.getElementById('btn-gen-invite');
  const btnForceStop = document.getElementById('btn-force-stop');
  const formAddUser = document.getElementById('form-add-user');
  const adminGpuStats = document.getElementById('admin-gpu-stats');
  const adminInvitesList = document.getElementById('admin-invites-list');
  const adminUsersList = document.getElementById('admin-users-list');
  const adminHistoryList = document.getElementById('admin-history-list');

  // In-Stream Viewport & Floating HUD Elements
  const streamViewport = document.getElementById('stream-viewport');
  const videoEl = document.getElementById('stream-video');
  const hudPillHandle = document.getElementById('hud-pill-handle');
  const hudPillSummary = document.getElementById('hud-pill-summary');
  const hudBar = document.getElementById('hud-bar');
  const btnHudLockMouse = document.getElementById('btn-hud-lock-mouse');
  const btnHudMute = document.getElementById('btn-hud-mute');
  const selectHudQuality = document.getElementById('select-hud-quality');
  const btnHudStats = document.getElementById('btn-hud-stats');
  const btnHudTouch = document.getElementById('btn-hud-touch');
  const btnHudFullscreen = document.getElementById('btn-hud-fullscreen');
  const btnHudMinimize = document.getElementById('btn-hud-minimize');
  const btnHudQuit = document.getElementById('btn-hud-quit');

  // Stats Overlay Elements
  const statsOverlay = document.getElementById('stream-stats-overlay');
  const stState = document.getElementById('st-state');
  const stRoute = document.getElementById('st-route');
  const stRtt = document.getElementById('st-rtt');
  const stJitter = document.getElementById('st-jitter');
  const stFps = document.getElementById('st-fps');
  const stBitrate = document.getElementById('st-bitrate');
  const stRes = document.getElementById('st-res');
  const stLoss = document.getElementById('st-loss');
  const stInputMode = document.getElementById('st-input-mode');
  const stUser = document.getElementById('st-user');
  const stSave = document.getElementById('st-save');
  const stSteam = document.getElementById('st-steam');
  const stIsoBox = document.getElementById('st-iso-box');

  // Session Progress Stepper Modal
  const stageModal = document.getElementById('session-stage-modal');
  const stageTitle = document.getElementById('stage-title');
  const stageDesc = document.getElementById('stage-desc');
  const step1 = document.getElementById('step-1');
  const step2 = document.getElementById('step-2');
  const step3 = document.getElementById('step-3');
  const step4 = document.getElementById('step-4');
  const stageActions = document.getElementById('stage-actions');
  const btnStageRetry = document.getElementById('btn-stage-retry');
  const btnStageLibrary = document.getElementById('btn-stage-library');

  // Touch Overlay Elements
  const touchOverlay = document.getElementById('stream-touch-overlay');
  const stickZone = document.getElementById('stick-zone');
  const stickNub = document.getElementById('stick-nub');

  // State
  let currentUser = null;
  let allGames = [];
  let selectedGame = null;
  let activeCategory = 'all';
  let searchQuery = '';

  let activeSessionId = null;
  let streamOpen = false;
  let streamReplaced = false;
  let ws = null;
  let pc = null;
  let dc = null;
  let wsConnectingForSession = null;
  let reconnectTimer = null;
  let lastBytesReceived = 0;
  let lastStatsTs = performance.now();
  let latestRttMs = null;
  let latestFps = 0;

  // --------------------------------------------------------------------------
  // Helper: Fallback Cover SVG Data URI for Offline Steam Games
  // --------------------------------------------------------------------------
  function makeFallbackCoverSvg(title, appId) {
    const safeTitle = (title || 'Steam Game').replace(/[<>&"']/g, '');
    const svg = `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 600 900">
      <rect width="600" height="900" fill="#0b1528"/>
      <circle cx="300" cy="360" r="220" fill="#1e3a8a" fill-opacity="0.35"/>
      <text x="300" y="420" fill="#38bdf8" font-family="sans-serif" font-size="34" font-weight="800" text-anchor="middle">${safeTitle.slice(0, 22)}</text>
      <text x="300" y="475" fill="#94a3b8" font-family="sans-serif" font-size="20" font-weight="600" text-anchor="middle">STEAM APP #${appId}</text>
    </svg>`;
    return 'data:image/svg+xml;utf8,' + encodeURIComponent(svg);
  }

  function formatBytes(bytes) {
    if (!bytes || bytes <= 0) return 'Cloud Ready';
    const gb = bytes / (1024 * 1024 * 1024);
    if (gb >= 0.1) return gb.toFixed(1) + ' GB';
    const mb = bytes / (1024 * 1024);
    return Math.max(1, Math.round(mb)) + ' MB';
  }

  // --------------------------------------------------------------------------
  // Navigation Tabs
  // --------------------------------------------------------------------------
  function switchTab(tabName) {
    tabBtnLibrary.classList.toggle('active', tabName === 'library');
    tabBtnProfile.classList.toggle('active', tabName === 'profile');
    tabBtnAdmin.classList.toggle('active', tabName === 'admin');

    secLibrary.style.display = tabName === 'library' ? 'block' : 'none';
    secProfile.style.display = tabName === 'profile' ? 'block' : 'none';
    secAdmin.style.display = tabName === 'admin' ? 'block' : 'none';
  }

  tabBtnLibrary.onclick = () => switchTab('library');
  tabBtnProfile.onclick = () => switchTab('profile');
  tabBtnAdmin.onclick = () => switchTab('admin');

  // --------------------------------------------------------------------------
  // Authentication Flows
  // --------------------------------------------------------------------------
  function showAuthError(msg) {
    authError.textContent = msg || '';
    authError.style.display = msg ? 'block' : 'none';
  }

  authTabLogin.onclick = () => {
    authTabLogin.classList.add('active');
    authTabInvite.classList.remove('active');
    formLogin.style.display = 'block';
    formInvite.style.display = 'none';
    showAuthError('');
  };

  authTabInvite.onclick = () => {
    authTabInvite.classList.add('active');
    authTabLogin.classList.remove('active');
    formInvite.style.display = 'block';
    formLogin.style.display = 'none';
    showAuthError('');
  };

  formLogin.onsubmit = async (e) => {
    e.preventDefault();
    showAuthError('');
    const res = await fetch('/api/auth/login', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        username: document.getElementById('login-user').value,
        password: document.getElementById('login-pass').value,
      }),
    });
    const data = await res.json();
    if (!res.ok || !data.ok) {
      showAuthError(data.error || 'Invalid credentials');
      return;
    }
    if (data.token) {
      localStorage.setItem('ryoku_auth_token', data.token);
    }
    await bootstrapAuthenticatedApp();
  };

  formInvite.onsubmit = async (e) => {
    e.preventDefault();
    showAuthError('');
    const res = await fetch('/api/auth/redeem-invite', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        invite_code: document.getElementById('inv-code').value,
        username: document.getElementById('inv-user').value,
        password: document.getElementById('inv-pass').value,
      }),
    });
    const data = await res.json();
    if (!res.ok || !data.ok) {
      showAuthError(data.error || 'Could not redeem invite');
      return;
    }
    if (data.token) {
      localStorage.setItem('ryoku_auth_token', data.token);
    }
    await bootstrapAuthenticatedApp();
  };

  document.getElementById('btn-logout').onclick = async () => {
    closeStreamViewport();
    localStorage.removeItem('ryoku_auth_token');
    await fetch('/api/auth/logout', { method: 'POST' });
    currentUser = null;
    authView.style.display = 'block';
    appView.style.display = 'none';
    navCenter.style.display = 'none';
    navRight.style.display = 'none';
  };

  // --------------------------------------------------------------------------
  // Game Library, Search, Filter & Hero Spotlight
  // --------------------------------------------------------------------------
  function selectHeroGame(game) {
    selectedGame = game;
    if (!game) return;
    heroTitle.textContent = game.title;
    if (game.app_id === '0') {
      heroTag.textContent = 'NATIVE // 60 FPS OPENGL';
      heroDesc.textContent = 'Direct NVENC stream • Low-latency input • Persistent saves.';
    } else if (game.app_id === '7') {
      heroTag.textContent = 'VALVE // STEAM CLIENT';
      heroDesc.textContent = 'Direct in-stream Steam login • Persistent session token.';
    } else {
      heroTag.textContent = `STEAM // APPID ${game.app_id}`;
      heroDesc.textContent = `${formatBytes(game.size_bytes)} • Shared library mount • Private save profile.`;
    }
    heroBtnPlay.onclick = () => startOrResumeGame(game.app_id, game.title);
  }

  function renderGamesGrid() {
    gamesGrid.innerHTML = '';
    const q = searchQuery.trim().toLowerCase();
    const filtered = allGames.filter((g) => {
      if (activeCategory === 'steam' && (g.category !== 'steam' || g.app_id === '7')) return false;
      if (activeCategory === 'builtin' && g.category !== 'builtin') return false;
      if (activeCategory === 'account' && g.app_id !== '7') return false;
      if (q && !g.title.toLowerCase().includes(q) && !String(g.app_id).includes(q)) return false;
      return true;
    });

    if (filtered.length === 0) {
      gamesGrid.innerHTML = `<div style="grid-column:1/-1; color:var(--text-muted); padding:24px; text-align:center; background:var(--bg-panel); border:1px solid var(--border-dim); font-family:var(--font-mono); font-size:12px;">
        NO MATCHING TITLES
      </div>`;
      return;
    }

    for (const g of filtered) {
      const card = document.createElement('div');
      card.className = 'game-card';
      const catLabel = g.app_id === '0'
        ? 'NATIVE 3D'
        : (g.app_id === '7' ? 'STEAM CLIENT' : 'STEAM');

      const coverSrc = (g.cover_url && g.cover_url.startsWith('/assets/'))
        ? (BASE_PREFIX + g.cover_url)
        : g.cover_url;

      card.innerHTML = `
        <div class="game-cover-wrap">
          <img alt="${g.title}" src="${coverSrc}" />
          <div class="game-cover-overlay">
            <div class="game-card-cat">${catLabel}</div>
            <div class="game-card-title">${g.title}</div>
            <div class="game-card-meta">
              <span>#${g.app_id}</span>
              <span>${formatBytes(g.size_bytes)}</span>
            </div>
            <button class="btn btn-primary" style="width:100%;">▶ PLAY</button>
          </div>
        </div>
      `;

      const img = card.querySelector('img');
      img.onerror = () => {
        img.onerror = null;
        img.src = makeFallbackCoverSvg(g.title, g.app_id);
      };

      card.onclick = (ev) => {
        if (ev.target.tagName.toLowerCase() === 'button') {
          ev.stopPropagation();
          selectHeroGame(g);
          startOrResumeGame(g.app_id, g.title);
        } else {
          selectHeroGame(g);
        }
      };

      gamesGrid.appendChild(card);
    }
  }

  searchInput.oninput = () => {
    searchQuery = searchInput.value;
    renderGamesGrid();
  };

  filterChips.forEach((chip) => {
    chip.onclick = () => {
      filterChips.forEach((c) => c.classList.remove('active'));
      chip.classList.add('active');
      activeCategory = chip.dataset.filter || 'all';
      renderGamesGrid();
    };
  });

  async function loadGamesLibrary() {
    const res = await fetch('/api/games');
    if (!res.ok) return;
    const data = await res.json();
    allGames = data.games || [];
    if (!selectedGame && allGames.length > 0) {
      selectHeroGame(allGames[0]);
    }
    renderGamesGrid();
  }

  // --------------------------------------------------------------------------
  // Launching & Managing Sessions + Progress Stepper
  // --------------------------------------------------------------------------
  function setStepperState(state, message, isError = false) {
    step1.className = 'stage-step done';
    if (state === 'starting') {
      stageModal.classList.remove('hidden');
      stageTitle.textContent = 'Starting Isolated Gaming Session...';
      stageDesc.textContent = message || 'Preparing Bubblewrap container & RTX 4060 display...';
      step2.className = 'stage-step active';
      step3.className = 'stage-step';
      step4.className = 'stage-step';
      stageActions.style.display = 'none';
    } else if (state === 'ready') {
      stageModal.classList.remove('hidden');
      stageTitle.textContent = 'Connecting WebRTC Video & Audio...';
      stageDesc.textContent = message || 'Negotiating hardware NVENC H.264 & Opus stream...';
      step2.className = 'stage-step done';
      step3.className = 'stage-step done';
      step4.className = 'stage-step active';
      stageActions.style.display = 'none';
    } else if (state === 'playing') {
      step2.className = 'stage-step done';
      step3.className = 'stage-step done';
      step4.className = 'stage-step done';
      stageModal.classList.add('hidden');
    } else if (state === 'ended' || isError) {
      stageModal.classList.remove('hidden');
      stageTitle.textContent = isError ? 'Stream Connection Notice' : 'Session Ended';
      stageDesc.textContent = message || 'Your isolated container has been destroyed.';
      stageActions.style.display = 'flex';
    }
  }

  async function startOrResumeGame(appId, title) {
    const [w, h] = (launchResolution.value || '1280x720').split('x').map(Number);
    const quality = launchQuality.value || 'high';
    selectHudQuality.value = quality;

    streamOpen = true;
    streamReplaced = false;
    streamViewport.classList.add('visible');
    // Pre-unlock video playback on mobile/safari browsers during direct click gesture
    videoEl.play().catch(() => {});
    setStepperState('starting', `Launching ${title || 'game'} in isolated sandbox...`);

    const res = await fetch('/api/sessions/start', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        app_id: String(appId),
        quality,
        width: w || 1280,
        height: h || 720,
        fps: 60,
      }),
    });
    const data = await res.json();
    if (!res.ok || !data.ok) {
      setStepperState('ended', data.error || 'Could not start session.', true);
      return;
    }

    const session = data.session;
    activeSessionId = session.session_id;
    handleSessionStateUpdate(session);
  }

  let currentSessionAppId = '0';

  function handleSessionStateUpdate(s) {
    if (!s) return;
    currentSessionAppId = String(s.app_id ?? '0');
    stState.textContent = (s.state || 'unknown').toUpperCase();
    stUser.textContent = `${s.username || 'player'} • App ${s.app_id}`;
    if (s.savegame) {
      stSave.textContent = `${s.savegame.high_score || 0} pts (Run #${s.savegame.sessions_played || 1})`;
    }
    stSteam.textContent = s.steam_login_remembered ? 'Remembered ✓' : 'In-Stream Only';
    if (s.isolation && s.isolation.all_passed) {
      stIsoBox.innerHTML = '<strong>ISOLATION VERIFIED ✓</strong><br/>Host Home, Host Desktop, Physical Inputs &amp; Host Audio Blocked';
    }

    if (!streamOpen || streamReplaced) return;

    if (s.state === 'starting') {
      setStepperState('starting', s.stage_message);
    } else if (s.state === 'ready' || s.state === 'playing') {
      if (wsConnectingForSession !== s.session_id) {
        setStepperState('ready', s.stage_message);
        connectStreamWebSocket(s.session_id);
      }
    } else if (s.state === 'ended') {
      teardownWebRTC();
      setStepperState('ended', s.stage_message);
    }
  }

  // --------------------------------------------------------------------------
  // Direct Integrated WebRTC + RTCDataChannel Client
  // --------------------------------------------------------------------------
  function teardownWebRTC() {
    clearTimeout(reconnectTimer);
    wsConnectingForSession = null;
    if (dc) {
      try { dc.close(); } catch (_) {}
      dc = null;
    }
    if (pc) {
      try { pc.close(); } catch (_) {}
      pc = null;
    }
    if (ws) {
      try { ws.onclose = null; ws.close(); } catch (_) {}
      ws = null;
    }
    if (document.pointerLockElement === videoEl) {
      document.exitPointerLock();
    }
  }

  function closeStreamViewport() {
    streamOpen = false;
    pointerLockPreferred = true;
    teardownWebRTC();
    if (document.fullscreenElement) {
      document.exitFullscreen().catch(() => {});
    }
    streamViewport.classList.remove('visible');
  }

  function sendInputPacket(payload) {
    if (!streamOpen || streamReplaced) return;
    if (dc && dc.readyState === 'open') {
      // If network backpressure occurs, drop stale high-frequency mouse movements to prevent input lag backlog
      if (payload.type === 'mousemove' && dc.bufferedAmount > 16384) {
        return;
      }
      dc.send(JSON.stringify(payload));
    } else if (ws && ws.readyState === WebSocket.OPEN) {
      ws.send(JSON.stringify(payload));
    }
  }

  function bindDataChannel(channel) {
    dc = channel;
    dc.onopen = () => {
      setStepperState('playing');
    };
    dc.onmessage = (ev) => {
      try {
        const msg = JSON.parse(ev.data);
        if (msg.type === 'pong' && msg.client_ts) {
          latestRttMs = Math.max(1, Math.round(performance.now() - msg.client_ts));
          stRtt.textContent = latestRttMs + ' ms';
          updateHudPillSummary();
        }
      } catch (_) {}
    };
  }

  async function fetchIceServers() {
    try {
      const res = await fetch('/api/webrtc/ice-config', { cache: 'no-store' });
      if (res.ok) {
        const data = await res.json();
        if (Array.isArray(data.iceServers)) {
          window.CLOUD_ICE_SERVERS = data.iceServers;
          return data.iceServers;
        }
      }
    } catch (_) {}
    return window.CLOUD_ICE_SERVERS || [];
  }

  function connectStreamWebSocket(sessionId) {
    teardownWebRTC();
    wsConnectingForSession = sessionId;

    // Start prefetching ICE servers in parallel with WebSocket connection
    const iceServersPromise = fetchIceServers();
    let pendingRemoteCandidates = [];
    let remoteDescReady = false;

    const proto = location.protocol === 'https:' ? 'wss:' : 'ws:';
    const authToken = localStorage.getItem('ryoku_auth_token') || '';
    const tokenQuery = authToken ? `?token=${encodeURIComponent(authToken)}` : '';
    ws = new WebSocket(`${proto}//${location.host}${BASE_PREFIX}/api/sessions/current/ws${tokenQuery}`);

    ws.onmessage = async (ev) => {
      let msg;
      try {
        msg = JSON.parse(ev.data);
      } catch (_) {
        return;
      }

      if (msg.type === 'replaced') {
        streamReplaced = true;
        teardownWebRTC();
        setStepperState(
          'ended',
          msg.message || 'Stream was transferred to another device or browser tab.',
          true
        );
        return;
      }

      if (msg.type === 'status' && msg.status) {
        selectHudQuality.value = msg.status.quality || 'high';
        if (msg.status.state === 'ended') {
          setStepperState('ended', 'Session has ended.');
          return;
        }
      } else if (msg.type === 'offer') {
        if (pc) {
          try { pc.close(); } catch (_) {}
          pc = null;
        }
        const iceServers = await iceServersPromise;
        const hasRelay = iceServers.some((s) => {
          const urls = Array.isArray(s.urls) ? s.urls : [s.urls];
          return urls.some((u) => String(u).startsWith('turn:') || String(u).startsWith('turns:'));
        });
        try {
          pc = new RTCPeerConnection({ iceServers });
        } catch (err) {
          console.error('RTCPeerConnection rejected ICE servers', iceServers, err);
          const stunOnly = iceServers.filter((s) => {
            const urls = Array.isArray(s.urls) ? s.urls : [s.urls];
            return urls.every((u) => String(u).startsWith('stun:'));
          });
          try {
            pc = new RTCPeerConnection({ iceServers: stunOnly });
          } catch (_) {
            pc = new RTCPeerConnection({});
          }
          setStepperState(
            'ended',
            `Relay server settings are invalid (${err.message || err}). Fix TURN URL in .env / Admin Console (must look like turn:host:3478).`,
            true
          );
          return;
        }

        let mediaFlowing = false;
        const noMediaTimer = setTimeout(() => {
          if (!mediaFlowing && streamOpen && !streamReplaced) {
            setStepperState(
              'ended',
              hasRelay
                ? 'Video path could not be established. Check that the host PC has internet access and retry.'
                : 'No relay server configured: players outside the home network cannot receive video. Ask the admin to add Cloudflare TURN keys (Admin > External Gateway).',
              true
            );
          }
        }, 20000);

        const checkConnectedState = () => {
          if (!pc) return;
          const st = pc.iceConnectionState;
          if (st === 'connected' || st === 'completed') {
            mediaFlowing = true;
            clearTimeout(noMediaTimer);
            setStepperState('playing');
          } else if (st === 'failed') {
            clearTimeout(noMediaTimer);
            setStepperState(
              'ended',
              hasRelay
                ? 'Connection to the gaming PC failed (relay unreachable). Retry, or switch networks.'
                : 'Connection failed: no TURN relay is configured, so video cannot cross the internet. Ask the admin to add Cloudflare TURN keys.',
              true
            );
          }
        };

        pc.oniceconnectionstatechange = checkConnectedState;
        if ('onconnectionstatechange' in pc) {
          pc.onconnectionstatechange = () => {
            if (pc && (pc.connectionState === 'connected')) {
              mediaFlowing = true;
              clearTimeout(noMediaTimer);
              setStepperState('playing');
            }
          };
        }

        pc.ondatachannel = (event) => bindDataChannel(event.channel);

        pc.ontrack = (event) => {
          mediaFlowing = true;
          clearTimeout(noMediaTimer);
          try {
            if (event.receiver && 'playoutDelayHint' in event.receiver) {
              event.receiver.playoutDelayHint = 0;
            }
            if (event.receiver && 'jitterBufferTarget' in event.receiver) {
              event.receiver.jitterBufferTarget = 0;
            }
            if (pc && pc.getReceivers) {
              pc.getReceivers().forEach((r) => {
                if ('playoutDelayHint' in r) r.playoutDelayHint = 0;
                if ('jitterBufferTarget' in r) r.jitterBufferTarget = 0;
              });
            }
          } catch (_) {}
          if (event.streams && event.streams[0]) {
            if (videoEl.srcObject !== event.streams[0]) {
              videoEl.srcObject = event.streams[0];
            }
          } else if (event.track) {
            if (!videoEl.srcObject || !(videoEl.srcObject instanceof MediaStream)) {
              videoEl.srcObject = new MediaStream();
            }
            videoEl.srcObject.addTrack(event.track);
          }
          videoEl.play().catch(() => {
            // Autoplay with audio was blocked by browser policy; mute and retry automatically
            videoEl.muted = true;
            btnHudMute.textContent = 'UNMUTE';
            btnHudMute.classList.remove('active');
            videoEl.play().catch(() => {});
          });
          setStepperState('playing');
        };

        pc.onicecandidate = (event) => {
          if (event.candidate && ws && ws.readyState === WebSocket.OPEN) {
            ws.send(JSON.stringify({
              type: 'ice',
              candidate: event.candidate.candidate,
              sdpMLineIndex: event.candidate.sdpMLineIndex,
            }));
          }
        };

        await pc.setRemoteDescription({ type: 'offer', sdp: msg.sdp });
        remoteDescReady = true;

        // Flush all remote ICE candidates that arrived while setRemoteDescription was pending
        if (pendingRemoteCandidates.length > 0) {
          for (const cand of pendingRemoteCandidates) {
            try {
              await pc.addIceCandidate(new RTCIceCandidate(cand));
            } catch (_) {}
          }
          pendingRemoteCandidates = [];
        }

        const answer = await pc.createAnswer();
        await pc.setLocalDescription(answer);
        if (ws && ws.readyState === WebSocket.OPEN) {
          ws.send(JSON.stringify({ type: 'answer', sdp: answer.sdp }));
        }
      } else if (msg.type === 'ice' && msg.candidate) {
        const candData = {
          candidate: msg.candidate,
          sdpMLineIndex: msg.sdpMLineIndex || 0,
        };
        if (!pc || !remoteDescReady) {
          pendingRemoteCandidates.push(candData);
        } else {
          try {
            await pc.addIceCandidate(new RTCIceCandidate(candData));
          } catch (_) {}
        }
      } else if (msg.type === 'pong' && msg.client_ts) {
        latestRttMs = Math.max(1, Math.round(performance.now() - msg.client_ts));
        stRtt.textContent = latestRttMs + ' ms';
        updateHudPillSummary();
      }
    };

    ws.onclose = (ev) => {
      if (!streamOpen || streamReplaced || (ev && ev.code === 4001)) return;
      wsConnectingForSession = null;
      reconnectTimer = setTimeout(async () => {
        if (!streamOpen || streamReplaced) return;
        const r = await fetch('/api/sessions/current');
        if (!r.ok) return;
        const d = await r.json();
        if (d.session && d.session.state !== 'ended') {
          connectStreamWebSocket(d.session.session_id);
        } else if (d.session) {
          handleSessionStateUpdate(d.session);
        }
      }, 1500);
    };
  }

  function updateHudPillSummary() {
    const rttTxt = latestRttMs !== null ? `${latestRttMs} ms` : '-- ms';
    const fpsTxt = latestFps ? `${latestFps} FPS` : '60 FPS';
    const collapsed = hudBar.classList.contains('collapsed');
    hudPillSummary.textContent = `RYOKU HUD ${collapsed ? '▾' : '▴'} • ${fpsTxt} • ${rttTxt}`;
  }

  // --------------------------------------------------------------------------
  // In-Stream HUD Controls (Collapse, Pointer Lock, Mute, Quality, Stats, Touch, Fullscreen)
  // --------------------------------------------------------------------------
  hudPillHandle.onclick = (e) => {
    e.currentTarget.blur();
    hudBar.classList.toggle('collapsed');
    updateHudPillSummary();
  };

  let pointerLockPreferred = true;

  btnHudLockMouse.onclick = (e) => {
    e.currentTarget.blur();
    videoEl.muted = false;
    videoEl.play().catch(() => {});
    if (document.pointerLockElement === videoEl) {
      pointerLockPreferred = false;
      document.exitPointerLock();
    } else if (videoEl.requestPointerLock) {
      pointerLockPreferred = true;
      videoEl.requestPointerLock();
    }
  };

  document.addEventListener('pointerlockchange', () => {
    const locked = document.pointerLockElement === videoEl;
    btnHudLockMouse.textContent = locked ? 'UNLOCK (ESC)' : 'LOCK AIM';
    btnHudLockMouse.classList.toggle('active', locked);
    stInputMode.textContent = locked ? '3D POINTER LOCK' : 'FREE CURSOR';
  });

  btnHudMute.onclick = (e) => {
    e.currentTarget.blur();
    videoEl.muted = !videoEl.muted;
    btnHudMute.textContent = videoEl.muted ? 'UNMUTE' : 'AUDIO ON';
    btnHudMute.classList.toggle('active', !videoEl.muted);
  };

  selectHudQuality.onchange = async (e) => {
    e.currentTarget.blur();
    const q = selectHudQuality.value;
    sendInputPacket({ type: 'quality', quality: q });
    await fetch('/api/sessions/quality', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ quality: q }),
    }).catch(() => {});
  };

  btnHudStats.onclick = (e) => {
    if (e && e.currentTarget) e.currentTarget.blur();
    statsOverlay.classList.toggle('visible');
    btnHudStats.classList.toggle('active', statsOverlay.classList.contains('visible'));
  };

  btnHudTouch.onclick = (e) => {
    e.currentTarget.blur();
    touchOverlay.classList.toggle('visible');
    btnHudTouch.classList.toggle('active', touchOverlay.classList.contains('visible'));
  };

  if ('ontouchstart' in window || navigator.maxTouchPoints > 0) {
    touchOverlay.classList.add('visible');
    btnHudTouch.classList.add('active');
  }

  btnHudFullscreen.onclick = (e) => {
    e.currentTarget.blur();
    if (!document.fullscreenElement) {
      streamViewport.requestFullscreen().catch(() => {});
    } else {
      document.exitFullscreen().catch(() => {});
    }
  };

  btnHudMinimize.onclick = (e) => {
    e.currentTarget.blur();
    closeStreamViewport();
    pollServerState();
  };

  btnHudQuit.onclick = async (e) => {
    e.currentTarget.blur();
    await fetch('/api/sessions/stop', { method: 'POST' });
    closeStreamViewport();
    await pollServerState();
  };

  btnStageLibrary.onclick = () => {
    closeStreamViewport();
    pollServerState();
  };

  btnStageRetry.onclick = () => {
    if (selectedGame) {
      startOrResumeGame(selectedGame.app_id, selectedGame.title);
    }
  };

  // --------------------------------------------------------------------------
  // Keyboard, Mouse, Wheel, Gamepad & Mobile Touch Input Capture
  // --------------------------------------------------------------------------
  const GAME_KEYS = new Set([
    'KeyW', 'KeyA', 'KeyS', 'KeyD', 'KeyQ', 'KeyE', 'KeyF', 'KeyR',
    'Space', 'ShiftLeft', 'ShiftRight', 'ControlLeft', 'ControlRight',
    'ArrowUp', 'ArrowDown', 'ArrowLeft', 'ArrowRight', 'Enter', 'Backspace'
  ]);

  window.addEventListener('keydown', (e) => {
    if (!streamOpen || streamReplaced) return;
    const tag = document.activeElement ? document.activeElement.tagName : '';
    if (tag === 'INPUT' || tag === 'TEXTAREA') return;

    if (e.code === 'Tab') {
      e.preventDefault();
      btnHudStats.click();
      return;
    }
    if (e.code === 'Escape') {
      // Allow browser to exit Pointer Lock / Fullscreen without terminating the game process
      return;
    }
    if (GAME_KEYS.has(e.code) || document.pointerLockElement === videoEl) {
      e.preventDefault();
    }
    if (e.repeat) return;
    stInputMode.textContent = document.pointerLockElement === videoEl ? 'KB + 3D LOCK' : `KB (${e.code})`;
    sendInputPacket({ type: 'keydown', code: e.code, key: e.key });
  });

  window.addEventListener('keyup', (e) => {
    if (!streamOpen || streamReplaced) return;
    if (e.code === 'Escape' || e.code === 'Tab') return;
    if (GAME_KEYS.has(e.code) || document.pointerLockElement === videoEl) {
      e.preventDefault();
    }
    sendInputPacket({ type: 'keyup', code: e.code, key: e.key });
  });

  window.addEventListener('blur', () => {
    if (streamOpen) {
      sendInputPacket({ type: 'release_all' });
    }
  });

  document.addEventListener('visibilitychange', () => {
    if (document.hidden && streamOpen) {
      sendInputPacket({ type: 'release_all' });
    }
  });

  let lastClientX = null;
  let lastClientY = null;

  // Global Pointer Lock motion handler to capture all mouse movement smoothly
  document.addEventListener('mousemove', (e) => {
    if (!streamOpen || streamReplaced || document.pointerLockElement !== videoEl) return;
    const dx = e.movementX || 0;
    const dy = e.movementY || 0;
    // Filter out OS screen-edge wrap spikes from browser Pointer Lock (> 250px)
    if (Math.abs(dx) > 250 || Math.abs(dy) > 250) {
      return;
    }
    if (dx !== 0 || dy !== 0) {
      const stepX = Math.max(-100, Math.min(100, dx));
      const stepY = Math.max(-100, Math.min(100, dy));
      sendInputPacket({ type: 'mousemove', dx: stepX, dy: stepY });
    }
  });

  videoEl.addEventListener('mousemove', (e) => {
    if (!streamOpen || streamReplaced) return;
    if (document.pointerLockElement === videoEl) {
      // Handled by document listener above
      return;
    }

    const rect = videoEl.getBoundingClientRect();
    if (rect.width <= 0 || rect.height <= 0) return;

    // Do not clamp and send edge coords when pointer wanders outside video element (avoids 180 snap)
    if (e.clientX < rect.left || e.clientX > rect.right || e.clientY < rect.top || e.clientY > rect.bottom) {
      lastClientX = null;
      lastClientY = null;
      return;
    }

    const nx = Math.max(0, Math.min(1, (e.clientX - rect.left) / rect.width));
    const ny = Math.max(0, Math.min(1, (e.clientY - rect.top) / rect.height));

    let dx = e.movementX || 0;
    let dy = e.movementY || 0;
    if (dx === 0 && dy === 0 && lastClientX !== null && lastClientY !== null) {
      dx = Math.round(e.clientX - lastClientX);
      dy = Math.round(e.clientY - lastClientY);
    }
    lastClientX = e.clientX;
    lastClientY = e.clientY;

    if ((e.buttons > 0 || currentSessionAppId === '0') && (dx !== 0 || dy !== 0)) {
      if (Math.abs(dx) <= 250 && Math.abs(dy) <= 250) {
        sendInputPacket({
          type: 'mousemove',
          dx: Math.max(-100, Math.min(100, dx)),
          dy: Math.max(-100, Math.min(100, dy)),
        });
      }
    } else {
      sendInputPacket({ type: 'mousemove', x: nx, y: ny });
    }
  });

  videoEl.addEventListener('mouseleave', () => {
    lastClientX = null;
    lastClientY = null;
  });

  videoEl.addEventListener('mousedown', (e) => {
    if (!streamOpen || streamReplaced) return;
    if (document.activeElement && document.activeElement !== document.body) {
      document.activeElement.blur();
    }
    videoEl.muted = false;
    btnHudMute.textContent = 'AUDIO ON';
    btnHudMute.classList.add('active');
    videoEl.play().catch(() => {});

    if (document.pointerLockElement !== videoEl) {
      if (pointerLockPreferred && !touchOverlay.classList.contains('visible') && videoEl.requestPointerLock) {
        try { videoEl.requestPointerLock(); } catch (_) {}
      } else {
        const rect = videoEl.getBoundingClientRect();
        if (
          rect.width > 0 &&
          rect.height > 0 &&
          e.clientX >= rect.left &&
          e.clientX <= rect.right &&
          e.clientY >= rect.top &&
          e.clientY <= rect.bottom
        ) {
          sendInputPacket({
            type: 'mousemove',
            x: (e.clientX - rect.left) / rect.width,
            y: (e.clientY - rect.top) / rect.height,
          });
        }
      }
    }
    sendInputPacket({ type: 'mousedown', button: e.button });
  });

  window.addEventListener('mouseup', (e) => {
    if (!streamOpen || streamReplaced) return;
    sendInputPacket({ type: 'mouseup', button: e.button });
  });

  videoEl.addEventListener('contextmenu', (e) => e.preventDefault());

  videoEl.addEventListener('wheel', (e) => {
    if (!streamOpen || streamReplaced) return;
    e.preventDefault();
    sendInputPacket({ type: 'wheel', dy: e.deltaY < 0 ? 1 : -1 });
  }, { passive: false });

  // --------------------------------------------------------------------------
  // Native-Grade Mobile & Pointer Control Engine
  // - Floating Left Thumbstick with Auto-Sprint at >=78% forward deflection
  // - Sub-pixel Velocity-Accelerated Right Aim Trackpad with Tap-to-Fire
  // - Simultaneous Hold-to-Fire + Drag-to-Aim on Combat Buttons
  // --------------------------------------------------------------------------
  const touchLeftPad = document.getElementById('touch-left-pad') || stickZone;
  const stickSprintBadge = document.getElementById('stick-sprint-badge');
  const touchLookZone = document.getElementById('touch-look-zone');

  function pulseHaptic(ms = 10) {
    try {
      if (navigator.vibrate) navigator.vibrate(ms);
    } catch (_) {}
  }

  // Sub-pixel accumulator + velocity acceleration curve for 3D camera look
  let aimRemX = 0;
  let aimRemY = 0;
  function applyTouchAimDelta(rawDx, rawDy) {
    const speed = Math.hypot(rawDx, rawDy);
    if (speed === 0) return;
    // Precision curve: 1.25x for fine micro-aim, ramping up to 2.9x for fast flicks
    const accel = 1.25 + Math.min(1.65, speed * 0.045);
    aimRemX += rawDx * accel;
    aimRemY += rawDy * accel;
    const sendDx = Math.trunc(aimRemX);
    const sendDy = Math.trunc(aimRemY);
    if (sendDx !== 0 || sendDy !== 0) {
      aimRemX -= sendDx;
      aimRemY -= sendDy;
      sendInputPacket({ type: 'touch_look', dx: sendDx, dy: sendDy });
    }
  }

  // 1. Dynamic Floating Left Analog Thumbstick
  let stickPointerId = null;
  let stickOrigin = null;
  let wasAutoSprinting = false;

  const updateStickPosition = (clientX, clientY) => {
    if (!stickOrigin) return;
    const maxR = 48;
    let dx = clientX - stickOrigin.x;
    let dy = clientY - stickOrigin.y;
    const dist = Math.hypot(dx, dy);
    const normMag = Math.min(1.0, dist / maxR);
    if (dist > maxR) {
      dx = (dx / dist) * maxR;
      dy = (dy / dist) * maxR;
    }
    stickNub.style.transform = `translate(${dx.toFixed(1)}px, ${dy.toFixed(1)}px)`;

    const normX = Number((dx / maxR).toFixed(2));
    const normY = Number((dy / maxR).toFixed(2));
    const isSprinting = normMag >= 0.78 && normY < -0.30;

    if (isSprinting !== wasAutoSprinting) {
      wasAutoSprinting = isSprinting;
      stickZone.classList.toggle('sprinting', isSprinting);
      if (stickSprintBadge) {
        stickSprintBadge.textContent = isSprinting ? 'SPRINTING ▲' : 'SPRINT ▲';
      }
      if (isSprinting) pulseHaptic(12);
    }

    stInputMode.textContent = isSprinting ? 'STICK (SPRINT)' : 'VIRTUAL STICK';
    sendInputPacket({
      type: 'touch_move',
      x: normX,
      y: normY,
      sprint: isSprinting,
    });
  };

  touchLeftPad.addEventListener('pointerdown', (e) => {
    if (stickPointerId !== null) return;
    e.preventDefault();
    e.stopPropagation();
    videoEl.muted = false;
    stickPointerId = e.pointerId;
    try { touchLeftPad.setPointerCapture(e.pointerId); } catch (_) {}

    const padRect = touchLeftPad.getBoundingClientRect();
    const stickRadius = 68;
    // Dynamically float the stick base to the thumb position (clamped inside left pad)
    const relX = Math.max(stickRadius + 12, Math.min(padRect.width - stickRadius - 12, e.clientX - padRect.left));
    const relY = Math.max(stickRadius + 28, Math.min(padRect.height - stickRadius - 12, e.clientY - padRect.top));
    stickZone.style.left = `${relX - stickRadius}px`;
    stickZone.style.top = `${relY - stickRadius}px`;
    stickZone.style.bottom = 'auto';

    stickOrigin = { x: padRect.left + relX, y: padRect.top + relY };
    stickZone.classList.add('active');
    pulseHaptic(8);
    updateStickPosition(e.clientX, e.clientY);
  });

  touchLeftPad.addEventListener('pointermove', (e) => {
    if (e.pointerId !== stickPointerId || !stickOrigin) return;
    e.preventDefault();
    updateStickPosition(e.clientX, e.clientY);
  });

  const resetStick = (e) => {
    if (stickPointerId !== null && e && e.pointerId !== undefined && e.pointerId !== stickPointerId) return;
    if (e) e.preventDefault();
    stickPointerId = null;
    stickOrigin = null;
    wasAutoSprinting = false;
    stickZone.classList.remove('active', 'sprinting');
    if (stickSprintBadge) stickSprintBadge.textContent = 'SPRINT ▲';
    // Return stick to default resting corner
    stickZone.style.left = '28px';
    stickZone.style.top = 'auto';
    stickZone.style.bottom = '28px';
    stickNub.style.transform = 'translate(0px, 0px)';
    sendInputPacket({ type: 'touch_move', x: 0, y: 0, sprint: false });
  };
  touchLeftPad.addEventListener('pointerup', resetStick);
  touchLeftPad.addEventListener('pointercancel', resetStick);
  touchLeftPad.addEventListener('lostpointercapture', resetStick);

  // 2. Right-Half Velocity-Accelerated 3D Aim Trackpad + Tap-to-Fire
  let lookPointerId = null;
  let lookLastPos = null;
  let lookDownTs = 0;
  let lookTotalDist = 0;

  if (touchLookZone) {
    touchLookZone.addEventListener('pointerdown', (e) => {
      if (lookPointerId !== null) return;
      e.preventDefault();
      e.stopPropagation();
      videoEl.muted = false;
      lookPointerId = e.pointerId;
      lookLastPos = { x: e.clientX, y: e.clientY };
      lookDownTs = performance.now();
      lookTotalDist = 0;
      touchLookZone.classList.add('active');
      try { touchLookZone.setPointerCapture(e.pointerId); } catch (_) {}
    });

    touchLookZone.addEventListener('pointermove', (e) => {
      if (e.pointerId !== lookPointerId || !lookLastPos) return;
      e.preventDefault();
      const rawDx = e.clientX - lookLastPos.x;
      const rawDy = e.clientY - lookLastPos.y;
      lookLastPos = { x: e.clientX, y: e.clientY };
      lookTotalDist += Math.hypot(rawDx, rawDy);
      if (rawDx !== 0 || rawDy !== 0) {
        stInputMode.textContent = 'TOUCH AIM';
        applyTouchAimDelta(rawDx, rawDy);
      }
    });

    const resetLook = (e) => {
      if (lookPointerId !== null && e && e.pointerId !== undefined && e.pointerId !== lookPointerId) return;
      const tapElapsed = performance.now() - lookDownTs;
      if (e && e.type === 'pointerup' && tapElapsed < 175 && lookTotalDist < 10) {
        // Quick tap on right aim pad -> Instant Fire
        pulseHaptic(10);
        sendInputPacket({ type: 'keydown', code: 'KeyF', key: 'f' });
        setTimeout(() => sendInputPacket({ type: 'keyup', code: 'KeyF', key: 'f' }), 60);
      }
      lookPointerId = null;
      lookLastPos = null;
      touchLookZone.classList.remove('active');
    };
    touchLookZone.addEventListener('pointerup', resetLook);
    touchLookZone.addEventListener('pointercancel', resetLook);
    touchLookZone.addEventListener('lostpointercapture', resetLook);
  }

  // 3. Ergonomic Action Buttons with Simultaneous Hold + Drag-to-Aim
  document.querySelectorAll('.t-btn').forEach((btn) => {
    const code = btn.dataset.code;
    const allowAimDrag = btn.dataset.aimDrag === 'true';
    let btnPointerId = null;
    let btnLastPos = null;

    const pressBtn = (e) => {
      e.preventDefault();
      e.stopPropagation();
      videoEl.muted = false;
      btnPointerId = e.pointerId;
      btnLastPos = { x: e.clientX, y: e.clientY };
      try { btn.setPointerCapture(e.pointerId); } catch (_) {}
      btn.classList.add('pressed');
      pulseHaptic(12);
      stInputMode.textContent = allowAimDrag ? `FIRE + AIM` : `TOUCH (${code})`;
      sendInputPacket({ type: 'keydown', code, key: code });
    };

    const moveBtn = (e) => {
      if (!allowAimDrag || e.pointerId !== btnPointerId || !btnLastPos) return;
      e.preventDefault();
      const rawDx = e.clientX - btnLastPos.x;
      const rawDy = e.clientY - btnLastPos.y;
      btnLastPos = { x: e.clientX, y: e.clientY };
      if (rawDx !== 0 || rawDy !== 0) {
        applyTouchAimDelta(rawDx, rawDy);
      }
    };

    const releaseBtn = (e) => {
      if (btnPointerId !== null && e && e.pointerId !== undefined && e.pointerId !== btnPointerId) return;
      if (e) {
        e.preventDefault();
        e.stopPropagation();
      }
      btnPointerId = null;
      btnLastPos = null;
      if (!btn.classList.contains('pressed')) return;
      btn.classList.remove('pressed');
      sendInputPacket({ type: 'keyup', code, key: code });
    };

    btn.addEventListener('pointerdown', pressBtn);
    btn.addEventListener('pointermove', moveBtn);
    btn.addEventListener('pointerup', releaseBtn);
    btn.addEventListener('pointercancel', releaseBtn);
    btn.addEventListener('lostpointercapture', releaseBtn);
  });

  // W3C Gamepad API Polling (60Hz)
  let hadGamepadInput = false;
  function pollGamepads() {
    if (streamOpen && navigator.getGamepads) {
      const pads = navigator.getGamepads();
      for (const pad of pads) {
        if (!pad || !pad.connected) continue;
        const axes = pad.axes.slice(0, 4).map((v) => Math.abs(v) > 0.12 ? Number(v.toFixed(2)) : 0);
        const buttons = pad.buttons.slice(0, 16).map((b) => b.pressed);
        const active = axes.some((a) => a !== 0) || buttons.some(Boolean);
        if (active || hadGamepadInput) {
          sendInputPacket({ type: 'gamepad', axes, buttons });
          hadGamepadInput = active;
          if (active) stInputMode.textContent = `Gamepad (${pad.id.slice(0, 14)})`;
        }
        break;
      }
    }
    requestAnimationFrame(pollGamepads);
  }
  requestAnimationFrame(pollGamepads);

  // Real-time WebRTC Stats & RTT Ping Loop
  setInterval(async () => {
    if (!streamOpen || streamReplaced) return;
    sendInputPacket({ type: 'ping', client_ts: performance.now() });

    if (!pc) return;
    try {
      if (pc.getReceivers) {
        pc.getReceivers().forEach((r) => {
          if ('playoutDelayHint' in r) r.playoutDelayHint = 0;
        });
      }
      const report = await pc.getStats();
      const candMap = new Map();
      report.forEach((stat) => {
        if (stat.type === 'local-candidate' || stat.type === 'remote-candidate') {
          candMap.set(stat.id, stat);
        }
      });

      report.forEach((stat) => {
        if (stat.type === 'candidate-pair' && (stat.nominated || stat.state === 'succeeded')) {
          if (stat.currentRoundTripTime !== undefined) {
            const pairRtt = Math.round(stat.currentRoundTripTime * 1000);
            if (pairRtt > 0) {
              latestRttMs = pairRtt;
              stRtt.textContent = latestRttMs + ' ms';
            }
          }
          const local = candMap.get(stat.localCandidateId);
          const remote = candMap.get(stat.remoteCandidateId);
          if (stRoute) {
            if ((local && local.candidateType === 'relay') || (remote && remote.candidateType === 'relay')) {
              stRoute.textContent = 'TURN Relay (High Latency)';
              stRoute.style.color = '#ff9800';
            } else if ((local && local.candidateType === 'srflx') || (remote && remote.candidateType === 'srflx')) {
              stRoute.textContent = 'Direct STUN (Fast P2P)';
              stRoute.style.color = '#00ff88';
            } else {
              stRoute.textContent = 'Direct Host (Ultra Fast)';
              stRoute.style.color = '#00ff88';
            }
          }
        }
        if (stat.type === 'inbound-rtp' && stat.kind === 'video') {
          const now = performance.now();
          const dt = (now - lastStatsTs) / 1000;
          if (dt > 0 && stat.bytesReceived) {
            const kbps = Math.round(((stat.bytesReceived - lastBytesReceived) * 8) / 1000 / dt);
            stBitrate.textContent = (kbps / 1000).toFixed(2) + ' Mbps';
            lastBytesReceived = stat.bytesReceived;
            lastStatsTs = now;
          }
          if (stat.framesPerSecond !== undefined) {
            latestFps = Math.round(stat.framesPerSecond);
            stFps.textContent = latestFps + ' FPS';
          }
          if (stat.packetsLost !== undefined) {
            stLoss.textContent = String(stat.packetsLost);
          }
          if (stat.jitter !== undefined && stJitter) {
            stJitter.textContent = Math.round(stat.jitter * 1000) + ' ms';
          }
          if (stat.frameWidth && stat.frameHeight) {
            stRes.textContent = `${stat.frameWidth}x${stat.frameHeight}`;
          }
          updateHudPillSummary();
        }
      });
    } catch (_) {}
  }, 1000);

  // --------------------------------------------------------------------------
  // Admin Actions & Periodic Server Polling (Phase 5 Enhanced Portal)
  // --------------------------------------------------------------------------
  const adminActiveSessionBox = document.getElementById('admin-active-session-box');
  const adminGpuSparkline = document.getElementById('admin-gpu-sparkline');
  const adminHostStats = document.getElementById('admin-host-stats');
  const formAdminSettings = document.getElementById('form-admin-settings');
  const settingIdleSec = document.getElementById('setting-idle-sec');
  const settingGraceSec = document.getElementById('setting-grace-sec');
  const inviteNoteInput = document.getElementById('invite-note-input');
  const btnClearHistory = document.getElementById('btn-clear-history');
  const pcOfflineBanner = document.getElementById('pc-offline-banner');
  const formAdminNetwork = document.getElementById('form-admin-network');
  const netPublicDomain = document.getElementById('net-public-domain');
  const netStunUrl = document.getElementById('net-stun-url');
  const netTurnUrl = document.getElementById('net-turn-url');
  const netTurnSecret = document.getElementById('net-turn-secret');
  const btnToggleOfflineMode = document.getElementById('btn-toggle-offline-mode');
  const adminNetSummary = document.getElementById('admin-net-summary');
  let currentOfflineSimMode = false;

  if (formAdminNetwork) {
    formAdminNetwork.onsubmit = async (e) => {
      e.preventDefault();
      const payload = {
        public_domain: netPublicDomain ? netPublicDomain.value.trim() : '',
        stun_url: netStunUrl ? netStunUrl.value.trim() : '',
        turn_url: netTurnUrl ? netTurnUrl.value.trim() : '',
      };
      if (netTurnSecret && netTurnSecret.value.trim()) {
        payload.turn_secret = netTurnSecret.value.trim();
      }
      const cfKeyInput = document.getElementById('net-cf-turn-key-id');
      const turnUserInput = document.getElementById('net-turn-user');
      const turnPassInput = document.getElementById('net-turn-pass');
      if (turnUserInput && turnUserInput.value.trim()) {
        payload.turn_username = turnUserInput.value.trim();
      }
      if (turnPassInput && turnPassInput.value.trim()) {
        payload.turn_password = turnPassInput.value.trim();
      }
      const cfTokenInput = document.getElementById('net-cf-turn-token');
      if (cfKeyInput && cfKeyInput.value.trim()) {
        payload.cf_turn_key_id = cfKeyInput.value.trim();
      }
      if (cfTokenInput && cfTokenInput.value.trim()) {
        payload.cf_turn_api_token = cfTokenInput.value.trim();
      }
      const res = await fetch('/api/admin/network', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload),
      });
      if (res.ok) {
        if (netTurnSecret) netTurnSecret.value = '';
        const tpi = document.getElementById('net-turn-pass');
        if (tpi) tpi.value = '';
        if (cfTokenInput) cfTokenInput.value = '';
        await refreshAdminData();
      }
    };
  }

  if (btnToggleOfflineMode) {
    btnToggleOfflineMode.onclick = async () => {
      const res = await fetch('/api/admin/network', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ maintenance_offline_mode: !currentOfflineSimMode }),
      });
      if (res.ok) {
        await refreshAdminData();
        await pollServerState();
      }
    };
  }

  btnGenInvite.onclick = async () => {
    const note = inviteNoteInput ? inviteNoteInput.value.trim() : 'Friend Invite';
    const res = await fetch('/api/admin/invites', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ note: note || 'Friend Invite' }),
    });
    if (res.ok) {
      if (inviteNoteInput) inviteNoteInput.value = '';
      await refreshAdminData();
    }
  };

  btnForceStop.onclick = async () => {
    await fetch('/api/admin/sessions/force-stop', { method: 'POST' });
    await pollServerState();
  };

  if (btnClearHistory) {
    btnClearHistory.onclick = async () => {
      await fetch('/api/admin/history', { method: 'DELETE' });
      await refreshAdminData();
    };
  }

  if (formAdminSettings) {
    formAdminSettings.onsubmit = async (e) => {
      e.preventDefault();
      const res = await fetch('/api/admin/settings', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          idle_timeout_sec: Number(settingIdleSec.value),
          disconnect_grace_sec: Number(settingGraceSec.value),
        }),
      });
      if (res.ok) await refreshAdminData();
    };
  }

  if (formAddUser) {
    formAddUser.onsubmit = async (e) => {
      e.preventDefault();
      const u = document.getElementById('new-user-name').value;
      const p = document.getElementById('new-user-pass').value;
      const res = await fetch('/api/admin/users', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ username: u, password: p, role: 'player' }),
      });
      if (res.ok) {
        document.getElementById('new-user-name').value = '';
        document.getElementById('new-user-pass').value = '';
        await refreshAdminData();
      } else {
        const err = await res.json();
        alert(err.error || 'Could not add user');
      }
    };
  }

  function renderSparklineSvg(history) {
    if (!history || history.length < 2) {
      return '<div style="font-family:var(--font-mono); font-size:10px; color:var(--text-muted);">SAMPLING...</div>';
    }
    const w = 260;
    const h = 44;
    const pts = history.slice(-30);
    const step = w / Math.max(1, pts.length - 1);
    const gpuCoords = pts.map((p, idx) => `${(idx * step).toFixed(1)},${(h - (Math.min(100, p.gpu_util || 0) / 100) * (h - 8) - 4).toFixed(1)}`).join(' ');
    const encCoords = pts.map((p, idx) => `${(idx * step).toFixed(1)},${(h - (Math.min(100, p.enc_util || 0) / 100) * (h - 8) - 4).toFixed(1)}`).join(' ');
    return `
      <div style="font-family:var(--font-mono); font-size:10px; color:var(--text-muted); display:flex; justify-content:space-between; margin-bottom:3px;">
        <span>60S LOAD (<span style="color:#c8ff00;">■ 3D</span> // <span style="color:#00e676;">■ NVENC</span>)</span>
      </div>
      <svg viewBox="0 0 ${w} ${h}" width="100%" height="${h}" style="background:#060709; border:1px solid var(--border-dim);">
        <polyline fill="none" stroke="#c8ff00" stroke-width="1.8" points="${gpuCoords}" />
        <polyline fill="none" stroke="#00e676" stroke-width="1.5" stroke-dasharray="3,2" points="${encCoords}" />
      </svg>
    `;
  }

  async function refreshAdminData() {
    if (!currentUser || currentUser.role !== 'admin') return;
    const res = await fetch('/api/admin/overview');
    if (!res.ok) return;
    const data = await res.json();

    const act = data.active_session;
    btnForceStop.style.display = act ? 'inline-flex' : 'none';

    if (adminActiveSessionBox) {
      if (!act) {
        adminActiveSessionBox.innerHTML = `
          <div style="display:flex; justify-content:space-between; align-items:center; flex-wrap:wrap; gap:10px;">
            <div>
              <span class="badge-pill ok">STANDBY</span>
              <strong style="margin-left:8px; font-size:13px;">NO ACTIVE STREAM</strong>
            </div>
            <span style="font-family:var(--font-mono); font-size:11px; color:var(--text-muted);">SLOT: 0 / 1</span>
          </div>
        `;
      } else {
        const connBadge = act.client_connected
          ? '<span class="badge-pill ok">LIVE</span>'
          : `<span class="badge-pill warn">PAUSED (${Math.round(act.disconnect_remaining_sec || 0)}S)</span>`;
        adminActiveSessionBox.innerHTML = `
          <div style="display:flex; justify-content:space-between; align-items:center; flex-wrap:wrap; gap:12px;">
            <div>
              ${connBadge}
              <strong style="margin-left:8px; font-size:14px;">${act.username.toUpperCase()}</strong> // <strong>${act.game_title}</strong>
              <div style="font-family:var(--font-mono); font-size:11px; color:var(--text-sub); margin-top:4px;">
                ${act.width}x${act.height} ${act.fps}FPS (${act.quality.toUpperCase()}) • UP ${act.uptime_sec}S • IDLE ${Math.round(act.idle_remaining_sec)}S
              </div>
            </div>
            <button class="btn btn-danger" id="btn-inline-force-stop">KILL SESSION</button>
          </div>
        `;
        const inlineBtn = document.getElementById('btn-inline-force-stop');
        if (inlineBtn) inlineBtn.onclick = () => btnForceStop.click();
      }
    }

    const g = data.gpu || {};
    const gpuUtil = g.gpu_util_percent ?? 0;
    const encUtil = g.encoder_util_percent ?? 0;
    const vramPct = g.vram_percent ?? 0;
    const tempC = g.temperature_c ?? 0;
    const tempClass = tempC >= 82 ? 'hot' : (tempC >= 70 ? 'warm' : '');

    adminGpuStats.innerHTML = `
      <div class="list-item" style="margin-bottom:8px;">
        <span><strong>${g.name || 'RTX 4060'}</strong> (${g.driver_version || '—'})</span>
        <span class="badge-pill ${tempC >= 82 ? 'danger' : (tempC >= 70 ? 'warn' : 'ok')}">${tempC}°C // ${g.power_watts ? g.power_watts + 'W' : 'OK'}</span>
      </div>
      <div class="metric-bar-row">
        <div class="metric-bar-label"><span>3D ENGINE</span><strong>${gpuUtil}%</strong></div>
        <div class="metric-bar-track"><div class="metric-bar-fill" style="width:${Math.min(100, gpuUtil)}%;"></div></div>
      </div>
      <div class="metric-bar-row">
        <div class="metric-bar-label"><span>NVENC</span><strong>${encUtil}%</strong></div>
        <div class="metric-bar-track"><div class="metric-bar-fill" style="width:${Math.min(100, encUtil)}%;"></div></div>
      </div>
      <div class="metric-bar-row">
        <div class="metric-bar-label"><span>VRAM (${g.vram_used_mb ?? 0}/${g.vram_total_mb ?? 8188} MB)</span><strong>${vramPct}%</strong></div>
        <div class="metric-bar-track"><div class="metric-bar-fill ${tempClass}" style="width:${Math.min(100, vramPct)}%;"></div></div>
      </div>
    `;

    if (adminGpuSparkline) {
      adminGpuSparkline.innerHTML = renderSparklineSvg(data.gpu_history || []);
    }

    const h = data.host || {};
    if (adminHostStats) {
      adminHostStats.innerHTML = `
        <div class="metric-bar-row">
          <div class="metric-bar-label"><span>CPU (${h.cpu_cores || 12}T)</span><strong>${h.load_1m ?? 0} / ${h.load_5m ?? 0}</strong></div>
          <div class="metric-bar-track"><div class="metric-bar-fill" style="width:${Math.min(100, ((h.load_1m || 0) / (h.cpu_cores || 12)) * 100)}%;"></div></div>
        </div>
        <div class="metric-bar-row">
          <div class="metric-bar-label"><span>RAM (${h.ram_used_gb ?? 0}/${h.ram_total_gb ?? 16} GB)</span><strong>${h.ram_percent ?? 0}%</strong></div>
          <div class="metric-bar-track"><div class="metric-bar-fill" style="width:${Math.min(100, h.ram_percent || 0)}%;"></div></div>
        </div>
        <div class="metric-bar-row">
          <div class="metric-bar-label"><span>DISK (${h.disk_free_gb ?? 176} GB FREE)</span><strong>${h.disk_percent ?? 20}%</strong></div>
          <div class="metric-bar-track"><div class="metric-bar-fill" style="width:${Math.min(100, h.disk_percent || 0)}%;"></div></div>
        </div>
      `;
    }

    if (data.settings && document.activeElement !== settingIdleSec && document.activeElement !== settingGraceSec) {
      if (settingIdleSec) settingIdleSec.value = Math.round(data.settings.idle_timeout_sec || 600);
      if (settingGraceSec) settingGraceSec.value = Math.round(data.settings.disconnect_grace_sec || 300);
    }

    if (data.network) {
      const net = data.network;
      currentOfflineSimMode = Boolean(net.maintenance_offline_mode);
      if (btnToggleOfflineMode) {
        btnToggleOfflineMode.textContent = currentOfflineSimMode
          ? 'MAINTENANCE: ON (503)'
          : 'MAINTENANCE: OFF';
        btnToggleOfflineMode.className = currentOfflineSimMode ? 'btn btn-danger' : 'btn';
      }
      if (adminNetSummary) {
        const cfText = net.cloudflared_running ? 'TUNNEL: UP' : 'TUNNEL: STANDBY';
        const turnText = net.cloudflare_turn_configured
          ? (net.cloudflare_turn_error ? 'TURN: CF ERROR' : 'TURN: CLOUDFLARE')
          : (net.turn_configured ? 'TURN: HMAC' : 'TURN: NONE (REMOTE VIDEO BLOCKED)');
        const domainText = net.public_domain || 'LOCAL';
        adminNetSummary.textContent = `${domainText} // ${cfText} // ${turnText}`;
      }
      if (netPublicDomain && document.activeElement !== netPublicDomain) {
        netPublicDomain.value = net.public_domain || '';
      }
      if (netStunUrl && document.activeElement !== netStunUrl) {
        netStunUrl.value = net.stun_url || '';
      }
      if (netTurnUrl && document.activeElement !== netTurnUrl) {
        netTurnUrl.value = net.turn_url || '';
      }
    }

    adminInvitesList.innerHTML = (data.invites || []).slice(0, 8).map((inv) => {
      const canRevoke = !inv.used_by && !inv.revoked;
      return `
        <div class="list-item">
          <div>
            <span class="code-chip">${inv.code}</span>
            ${inv.note ? `<span style="font-size:11px; color:var(--text-muted); margin-left:6px;">${inv.note}</span>` : ''}
          </div>
          <div style="display:flex; align-items:center; gap:6px;">
            <span style="color:var(--text-muted); font-size:12px;">
              ${inv.used_by ? 'Used by ' + inv.used_by : (inv.revoked ? 'Revoked' : 'Available')}
            </span>
            ${canRevoke ? `<button class="btn" style="padding:2px 7px; font-size:11px;" data-copyinv="${inv.code}">Copy</button>` : ''}
            ${canRevoke ? `<button class="btn btn-danger" style="padding:2px 7px; font-size:11px;" data-revokeinv="${inv.code}">Revoke</button>` : ''}
          </div>
        </div>
      `;
    }).join('') || '<div style="color:var(--text-muted);font-size:12px;">No invite codes generated yet.</div>';

    adminInvitesList.querySelectorAll('[data-copyinv]').forEach((btn) => {
      btn.onclick = () => {
        navigator.clipboard.writeText(btn.dataset.copyinv).catch(() => {});
        btn.textContent = 'Copied!';
      };
    });

    adminInvitesList.querySelectorAll('[data-revokeinv]').forEach((btn) => {
      btn.onclick = async () => {
        await fetch(`/api/admin/invites/${btn.dataset.revokeinv}`, { method: 'DELETE' });
        await refreshAdminData();
      };
    });

    adminUsersList.innerHTML = (data.users || []).map((u) => `
      <div class="list-item">
        <div>
          <strong>${u.username}</strong>
          <span class="badge-pill ${u.active ? 'ok' : 'danger'}" style="margin-left:4px;">${u.active ? u.role : 'suspended'}</span>
          <div style="font-size:11px; color:var(--text-muted);">
            High Score: ${(u.cyberarena_save && u.cyberarena_save.high_score) || 0} • Steam: ${u.steam_login_remembered ? 'Remembered ✓' : '—'}
          </div>
        </div>
        ${u.username !== currentUser.username
          ? `<div style="display:flex; gap:5px;">
               <button class="btn" style="padding:3px 8px;font-size:11px;" data-toggleuser="${u.username}" data-active="${u.active}">${u.active ? 'Suspend' : 'Activate'}</button>
               <button class="btn btn-danger" style="padding:3px 8px;font-size:11px;" data-deluser="${u.username}">Remove</button>
             </div>`
          : '<span class="badge-pill ok">Owner</span>'}
      </div>
    `).join('');

    adminUsersList.querySelectorAll('[data-toggleuser]').forEach((btn) => {
      btn.onclick = async () => {
        const currentlyActive = btn.dataset.active === 'true';
        await fetch(`/api/admin/users/${btn.dataset.toggleuser}`, {
          method: 'PATCH',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ active: !currentlyActive }),
        });
        await refreshAdminData();
      };
    });

    adminUsersList.querySelectorAll('[data-deluser]').forEach((btn) => {
      btn.onclick = async () => {
        await fetch(`/api/admin/users/${btn.dataset.deluser}`, { method: 'DELETE' });
        await refreshAdminData();
      };
    });

    adminHistoryList.innerHTML = (data.session_history || []).slice(0, 12).map((h) => {
      const badgeType = h.state === 'playing' ? 'ok' : (h.end_reason === 'admin_force_ended' || h.end_reason === 'idle_timeout' ? 'warn' : 'ok');
      return `
        <div class="list-item">
          <div>
            <strong>${h.username}</strong> played <strong>${h.game_title}</strong>
            <span style="font-size:11px; color:var(--text-muted); margin-left:6px;">(${h.session_id} • ${h.quality.toUpperCase()})</span>
          </div>
          <div style="display:flex; align-items:center; gap:8px;">
            <span style="font-size:12px; color:var(--text-muted);">${h.duration_sec !== null && h.duration_sec !== undefined ? h.duration_sec + 's' : 'active'}</span>
            <span class="badge-pill ${badgeType}">${h.state === 'ended' ? (h.end_reason || 'ended') : h.state}</span>
          </div>
        </div>
      `;
    }).join('') || '<div style="color:var(--text-muted);font-size:12px;">No sessions recorded yet.</div>';
  }

  async function pollServerState() {
    if (!currentUser) return;
    let healthOnline = true;
    try {
      const hRes = await fetch('/api/health', { cache: 'no-store' });
      const hData = await hRes.json();
      healthOnline = Boolean(hRes.ok && hData && hData.online !== false);
    } catch (_) {
      healthOnline = false;
    }

    if (pcOfflineBanner) {
      pcOfflineBanner.style.display = healthOnline ? 'none' : 'block';
    }

    let res;
    try {
      res = await fetch('/api/auth/me');
    } catch (_) {
      serverDot.className = 'status-dot busy';
      serverPillText.textContent = 'Host PC Offline';
      return;
    }
    if (!res.ok) return;
    const data = await res.json();
    currentUser = data.user;

    const save = currentUser.cyberarena_save || {};
    heroBadgeUser.textContent = `USER: ${currentUser.username.toUpperCase()}`;
    heroBadgeSteam.textContent = `STEAM: ${currentUser.steam_login_remembered ? 'SAVED' : 'STREAM'}`;
    heroBadgeSave.textContent = `BEST: ${save.high_score || 0}`;

    profileDetails.innerHTML = `
      <div class="list-item"><span>USER</span><strong>${currentUser.username}</strong></div>
      <div class="list-item"><span>ROLE</span><strong>${currentUser.role.toUpperCase()}</strong></div>
      <div class="list-item"><span>MOUNT</span><code>data/users/${currentUser.username}/home/</code></div>
      <div class="list-item"><span>STEAM TOKEN</span><strong>${currentUser.steam_login_remembered ? 'SAVED (' + (currentUser.steam_account_hint || 'OK') + ')' : 'NOT LINKED'}</strong></div>
      <div class="list-item"><span>CYBERARENA BEST</span><strong>${save.high_score || 0} PTS (${save.sessions_played || 0} RUNS)</strong></div>
    `;

    const active = data.active_session;
    if (!healthOnline) {
      serverDot.className = 'status-dot busy';
      serverPillText.textContent = 'OFFLINE';
      btnResumeNav.style.display = 'none';
    } else if (!active) {
      serverDot.className = 'status-dot';
      serverPillText.textContent = 'READY';
      btnResumeNav.style.display = 'none';
    } else if (active.username === currentUser.username) {
      serverDot.className = 'status-dot';
      serverPillText.textContent = `ACTIVE // ${active.game_title.toUpperCase()}`;
      btnResumeNav.style.display = 'inline-flex';
      btnResumeNav.onclick = () => {
        streamOpen = true;
        streamReplaced = false;
        videoEl.play().catch(() => {});
        streamViewport.classList.add('visible');
        handleSessionStateUpdate(data.my_session);
      };
    } else {
      serverDot.className = 'status-dot busy';
      serverPillText.textContent = `BUSY // ${active.username.toUpperCase()}`;
      btnResumeNav.style.display = 'none';
    }

    if (data.my_session) {
      handleSessionStateUpdate(data.my_session);
    }

    if (currentUser.role === 'admin') {
      tabBtnAdmin.style.display = 'inline-block';
      await refreshAdminData();
    } else {
      tabBtnAdmin.style.display = 'none';
    }
  }

  async function bootstrapAuthenticatedApp() {
    const res = await fetch('/api/auth/me');
    if (!res.ok) {
      authView.style.display = 'block';
      appView.style.display = 'none';
      navCenter.style.display = 'none';
      navRight.style.display = 'none';
      return;
    }
    const data = await res.json();
    currentUser = data.user;
    authView.style.display = 'none';
    appView.style.display = 'block';
    navCenter.style.display = 'flex';
    navRight.style.display = 'flex';
    navUsername.textContent = `${currentUser.username}`;
    await loadGamesLibrary();
    await pollServerState();
  }

  setInterval(pollServerState, 2000);
  bootstrapAuthenticatedApp();
})();

