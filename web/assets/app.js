/* ==========================================================================
   Ryoku Cloud Gaming — Unified Product Web App & In-Stream WebRTC Client (Phase 4)
   ========================================================================== */

(() => {
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
  const stRtt = document.getElementById('st-rtt');
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
    await bootstrapAuthenticatedApp();
  };

  document.getElementById('btn-logout').onclick = async () => {
    closeStreamViewport();
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
      heroTag.textContent = 'FEATURED 60 FPS OPENGL ARENA';
      heroDesc.textContent =
        'Hardware-accelerated 3D arena running on your NVIDIA RTX 4060 inside an unprivileged Bubblewrap container. Includes real-time synth stereo audio and per-user persistent high score saves.';
    } else if (game.app_id === '7') {
      heroTag.textContent = 'ZERO-KNOWLEDGE STEAM LOGIN';
      heroDesc.textContent =
        'Launch Steam Big Picture UI inside your isolated container. Type your Steam password directly into Valve’s official UI—never seen by this website—and your login token is remembered for future sessions.';
    } else {
      heroTag.textContent = `STEAM LIBRARY • APPID ${game.app_id}`;
      heroDesc.textContent =
        `Stream ${game.title} from the read-only shared library (/steam_shared) with your personal Proton prefix and cloud saves mounted at /home/gamer.`;
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
      gamesGrid.innerHTML = `<div style="grid-column:1/-1; color:var(--text-muted); padding:28px; text-align:center; background:var(--bg-surface); border-radius:14px;">
        No games matched your filter. Try clearing the search box.
      </div>`;
      return;
    }

    for (const g of filtered) {
      const card = document.createElement('div');
      card.className = 'game-card';
      const catLabel = g.app_id === '0'
        ? 'Native 3D Arena'
        : (g.app_id === '7' ? 'Steam Account Login' : 'Steam Game');

      card.innerHTML = `
        <div class="game-cover-wrap">
          <img alt="${g.title}" src="${g.cover_url}" />
          <div class="game-cover-overlay">
            <div class="game-card-cat">${catLabel}</div>
            <div class="game-card-title">${g.title}</div>
            <div class="game-card-meta">
              <span>AppID ${g.app_id}</span>
              <span>${formatBytes(g.size_bytes)}</span>
            </div>
            <button class="btn btn-primary" style="width:100%;">▶ Play</button>
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
    streamViewport.classList.add('visible');
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

  function handleSessionStateUpdate(s) {
    if (!s) return;
    stState.textContent = (s.state || 'unknown').toUpperCase();
    stUser.textContent = `${s.username || 'player'} • App ${s.app_id}`;
    if (s.savegame) {
      stSave.textContent = `${s.savegame.high_score || 0} pts (Run #${s.savegame.sessions_played || 1})`;
    }
    stSteam.textContent = s.steam_login_remembered ? 'Remembered ✓' : 'In-Stream Only';
    if (s.isolation && s.isolation.all_passed) {
      stIsoBox.innerHTML = '<strong>ISOLATION VERIFIED ✓</strong><br/>Host Home, Host Desktop, Physical Inputs &amp; Host Audio Blocked';
    }

    if (!streamOpen) return;

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
    teardownWebRTC();
    if (document.fullscreenElement) {
      document.exitFullscreen().catch(() => {});
    }
    streamViewport.classList.remove('visible');
  }

  function sendInputPacket(payload) {
    if (!streamOpen) return;
    const raw = JSON.stringify(payload);
    if (dc && dc.readyState === 'open') {
      dc.send(raw);
    } else if (ws && ws.readyState === WebSocket.OPEN) {
      ws.send(raw);
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

  function connectStreamWebSocket(sessionId) {
    teardownWebRTC();
    wsConnectingForSession = sessionId;

    const proto = location.protocol === 'https:' ? 'wss:' : 'ws:';
    ws = new WebSocket(`${proto}//${location.host}/api/sessions/current/ws`);

    ws.onmessage = async (ev) => {
      let msg;
      try {
        msg = JSON.parse(ev.data);
      } catch (_) {
        return;
      }

      if (msg.type === 'status' && msg.status) {
        selectHudQuality.value = msg.status.quality || 'high';
        if (msg.status.state === 'ended') {
          setStepperState('ended', 'Session has ended.');
          return;
        }
      } else if (msg.type === 'offer') {
        if (pc) pc.close();
        pc = new RTCPeerConnection({ iceServers: window.CLOUD_ICE_SERVERS || [] });

        pc.ondatachannel = (event) => bindDataChannel(event.channel);

        pc.ontrack = (event) => {
          if (videoEl.srcObject !== event.streams[0]) {
            videoEl.srcObject = event.streams[0];
            videoEl.play().catch(() => {});
          }
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
        const answer = await pc.createAnswer();
        await pc.setLocalDescription(answer);
        ws.send(JSON.stringify({ type: 'answer', sdp: answer.sdp }));
      } else if (msg.type === 'ice' && msg.candidate && pc) {
        try {
          await pc.addIceCandidate(new RTCIceCandidate({
            candidate: msg.candidate,
            sdpMLineIndex: msg.sdpMLineIndex || 0,
          }));
        } catch (_) {}
      } else if (msg.type === 'pong' && msg.client_ts) {
        latestRttMs = Math.max(1, Math.round(performance.now() - msg.client_ts));
        stRtt.textContent = latestRttMs + ' ms';
        updateHudPillSummary();
      }
    };

    ws.onclose = () => {
      if (!streamOpen) return;
      wsConnectingForSession = null;
      reconnectTimer = setTimeout(async () => {
        if (!streamOpen) return;
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
  hudPillHandle.onclick = () => {
    hudBar.classList.toggle('collapsed');
    updateHudPillSummary();
  };

  btnHudLockMouse.onclick = () => {
    videoEl.muted = false;
    videoEl.play().catch(() => {});
    if (document.pointerLockElement === videoEl) {
      document.exitPointerLock();
    } else if (videoEl.requestPointerLock) {
      videoEl.requestPointerLock();
    }
  };

  document.addEventListener('pointerlockchange', () => {
    const locked = document.pointerLockElement === videoEl;
    btnHudLockMouse.textContent = locked ? 'Unlock Mouse (ESC)' : 'Lock Mouse (3D)';
    btnHudLockMouse.classList.toggle('active', locked);
    stInputMode.textContent = locked ? '3D Pointer Lock' : 'Normal UI Cursor';
  });

  btnHudMute.onclick = () => {
    videoEl.muted = !videoEl.muted;
    btnHudMute.textContent = videoEl.muted ? 'Unmute Audio' : 'Audio On';
    btnHudMute.classList.toggle('active', !videoEl.muted);
  };

  selectHudQuality.onchange = async () => {
    const q = selectHudQuality.value;
    sendInputPacket({ type: 'quality', quality: q });
    await fetch('/api/sessions/quality', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ quality: q }),
    }).catch(() => {});
  };

  btnHudStats.onclick = () => {
    statsOverlay.classList.toggle('visible');
    btnHudStats.classList.toggle('active', statsOverlay.classList.contains('visible'));
  };

  btnHudTouch.onclick = () => {
    touchOverlay.classList.toggle('visible');
    btnHudTouch.classList.toggle('active', touchOverlay.classList.contains('visible'));
  };

  if ('ontouchstart' in window || navigator.maxTouchPoints > 0) {
    touchOverlay.classList.add('visible');
    btnHudTouch.classList.add('active');
  }

  btnHudFullscreen.onclick = () => {
    if (!document.fullscreenElement) {
      streamViewport.requestFullscreen().catch(() => {});
    } else {
      document.exitFullscreen().catch(() => {});
    }
  };

  btnHudMinimize.onclick = () => {
    closeStreamViewport();
    pollServerState();
  };

  btnHudQuit.onclick = async () => {
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
  window.addEventListener('keydown', (e) => {
    if (!streamOpen) return;
    if (e.code === 'Tab') {
      e.preventDefault();
      btnHudStats.click();
      return;
    }
    e.preventDefault();
    sendInputPacket({ type: 'keydown', code: e.code, key: e.key });
  });

  window.addEventListener('keyup', (e) => {
    if (!streamOpen) return;
    e.preventDefault();
    sendInputPacket({ type: 'keyup', code: e.code, key: e.key });
  });

  videoEl.addEventListener('mousemove', (e) => {
    if (!streamOpen) return;
    if (document.pointerLockElement === videoEl) {
      sendInputPacket({ type: 'mousemove', dx: e.movementX, dy: e.movementY });
    } else {
      const rect = videoEl.getBoundingClientRect();
      if (rect.width > 0 && rect.height > 0) {
        const nx = Math.max(0, Math.min(1, (e.clientX - rect.left) / rect.width));
        const ny = Math.max(0, Math.min(1, (e.clientY - rect.top) / rect.height));
        sendInputPacket({ type: 'mousemove', x: nx, y: ny });
      }
    }
  });

  videoEl.addEventListener('mousedown', (e) => {
    if (!streamOpen) return;
    videoEl.muted = false;
    videoEl.play().catch(() => {});
    if (document.pointerLockElement !== videoEl) {
      const rect = videoEl.getBoundingClientRect();
      if (rect.width > 0 && rect.height > 0) {
        sendInputPacket({
          type: 'mousemove',
          x: Math.max(0, Math.min(1, (e.clientX - rect.left) / rect.width)),
          y: Math.max(0, Math.min(1, (e.clientY - rect.top) / rect.height)),
        });
      }
    }
    sendInputPacket({ type: 'mousedown', button: e.button });
  });

  window.addEventListener('mouseup', (e) => {
    if (!streamOpen) return;
    sendInputPacket({ type: 'mouseup', button: e.button });
  });

  videoEl.addEventListener('contextmenu', (e) => e.preventDefault());

  videoEl.addEventListener('wheel', (e) => {
    if (!streamOpen) return;
    e.preventDefault();
    sendInputPacket({ type: 'wheel', dy: e.deltaY < 0 ? 1 : -1 });
  }, { passive: false });

  // Virtual Analog Stick & Touch Buttons
  let stickOrigin = null;
  stickZone.addEventListener('touchstart', (e) => {
    e.preventDefault();
    const t = e.changedTouches[0];
    const r = stickZone.getBoundingClientRect();
    stickOrigin = { x: r.left + r.width / 2, y: r.top + r.height / 2 };
  }, { passive: false });

  stickZone.addEventListener('touchmove', (e) => {
    e.preventDefault();
    if (!stickOrigin) return;
    const t = e.changedTouches[0];
    const maxR = 45;
    let dx = t.clientX - stickOrigin.x;
    let dy = t.clientY - stickOrigin.y;
    const dist = Math.hypot(dx, dy);
    if (dist > maxR) {
      dx = (dx / dist) * maxR;
      dy = (dy / dist) * maxR;
    }
    stickNub.style.transform = `translate(${dx}px, ${dy}px)`;
    sendInputPacket({ type: 'touch_move', x: dx / maxR, y: dy / maxR });
  }, { passive: false });

  const resetStick = (e) => {
    e.preventDefault();
    stickOrigin = null;
    stickNub.style.transform = 'translate(0px, 0px)';
    sendInputPacket({ type: 'touch_move', x: 0, y: 0 });
  };
  stickZone.addEventListener('touchend', resetStick, { passive: false });
  stickZone.addEventListener('touchcancel', resetStick, { passive: false });

  document.querySelectorAll('.t-btn').forEach((btn) => {
    const code = btn.dataset.code;
    btn.addEventListener('touchstart', (e) => {
      e.preventDefault();
      videoEl.muted = false;
      sendInputPacket({ type: 'keydown', code, key: code });
    }, { passive: false });
    btn.addEventListener('touchend', (e) => {
      e.preventDefault();
      sendInputPacket({ type: 'keyup', code, key: code });
    }, { passive: false });
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
    if (!streamOpen) return;
    sendInputPacket({ type: 'ping', client_ts: performance.now() });

    if (!pc) return;
    try {
      const report = await pc.getStats();
      report.forEach((stat) => {
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
      return '<div style="font-size:11px; color:var(--text-muted);">Collecting live telemetry samples...</div>';
    }
    const w = 260;
    const h = 48;
    const pts = history.slice(-30);
    const step = w / Math.max(1, pts.length - 1);
    const gpuCoords = pts.map((p, idx) => `${(idx * step).toFixed(1)},${(h - (Math.min(100, p.gpu_util || 0) / 100) * (h - 8) - 4).toFixed(1)}`).join(' ');
    const encCoords = pts.map((p, idx) => `${(idx * step).toFixed(1)},${(h - (Math.min(100, p.enc_util || 0) / 100) * (h - 8) - 4).toFixed(1)}`).join(' ');
    return `
      <div style="font-size:10px; color:var(--text-muted); display:flex; justify-content:space-between; margin-bottom:3px;">
        <span>60s History (<span style="color:#38bdf8;">■ GPU Core</span> • <span style="color:#34d399;">■ NVENC</span>)</span>
      </div>
      <svg viewBox="0 0 ${w} ${h}" width="100%" height="${h}" style="background:rgba(2,6,23,0.65); border-radius:6px; border:1px solid rgba(148,163,184,0.12);">
        <polyline fill="none" stroke="#38bdf8" stroke-width="2" points="${gpuCoords}" />
        <polyline fill="none" stroke="#34d399" stroke-width="1.8" stroke-dasharray="3,2" points="${encCoords}" />
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
              <span class="badge-pill ok">GPU IDLE &amp; AVAILABLE</span>
              <strong style="margin-left:8px; font-size:14px;">No active gaming session on the server</strong>
            </div>
            <span style="font-size:12px; color:var(--text-muted);">Concurrency Lock: 0 / 1 Sessions Active</span>
          </div>
        `;
      } else {
        const connBadge = act.client_connected
          ? '<span class="badge-pill ok">LIVE WEBRTC STREAM</span>'
          : `<span class="badge-pill warn">DISCONNECTED (Grace: ${Math.round(act.disconnect_remaining_sec || 0)}s left)</span>`;
        adminActiveSessionBox.innerHTML = `
          <div style="display:flex; justify-content:space-between; align-items:center; flex-wrap:wrap; gap:12px;">
            <div>
              ${connBadge}
              <strong style="margin-left:8px; font-size:15px;">${act.username}</strong> is playing <strong>${act.game_title}</strong>
              <div style="font-size:12px; color:var(--text-muted); margin-top:4px;">
                Session <code>${act.session_id}</code> • ${act.width}x${act.height} @ ${act.fps}fps (${act.quality.toUpperCase()}) • Uptime: ${act.uptime_sec}s • Idle timeout in: ${Math.round(act.idle_remaining_sec)}s
              </div>
            </div>
            <button class="btn btn-danger" id="btn-inline-force-stop">⚡ Force-End Session Now</button>
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
        <span><strong>${g.name || 'NVIDIA RTX 4060'}</strong> (Driver ${g.driver_version || '—'})</span>
        <span class="badge-pill ${tempC >= 82 ? 'danger' : (tempC >= 70 ? 'warn' : 'ok')}">${tempC}°C • ${g.power_watts ? g.power_watts + 'W' : 'Optimal'}</span>
      </div>
      <div class="metric-bar-row">
        <div class="metric-bar-label"><span>3D Core Load</span><strong>${gpuUtil}%</strong></div>
        <div class="metric-bar-track"><div class="metric-bar-fill" style="width:${Math.min(100, gpuUtil)}%;"></div></div>
      </div>
      <div class="metric-bar-row">
        <div class="metric-bar-label"><span>NVENC Hardware Encoder</span><strong>${encUtil}%</strong></div>
        <div class="metric-bar-track"><div class="metric-bar-fill" style="width:${Math.min(100, encUtil)}%;"></div></div>
      </div>
      <div class="metric-bar-row">
        <div class="metric-bar-label"><span>VRAM (${g.vram_used_mb ?? 0} / ${g.vram_total_mb ?? 8188} MB)</span><strong>${vramPct}%</strong></div>
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
          <div class="metric-bar-label"><span>CPU Load (${h.cpu_cores || 12} Threads)</span><strong>${h.load_1m ?? 0} (1m) / ${h.load_5m ?? 0} (5m)</strong></div>
          <div class="metric-bar-track"><div class="metric-bar-fill" style="width:${Math.min(100, ((h.load_1m || 0) / (h.cpu_cores || 12)) * 100)}%;"></div></div>
        </div>
        <div class="metric-bar-row">
          <div class="metric-bar-label"><span>System RAM (${h.ram_used_gb ?? 0} / ${h.ram_total_gb ?? 16} GB)</span><strong>${h.ram_percent ?? 0}%</strong></div>
          <div class="metric-bar-track"><div class="metric-bar-fill" style="width:${Math.min(100, h.ram_percent || 0)}%;"></div></div>
        </div>
        <div class="metric-bar-row">
          <div class="metric-bar-label"><span>Storage Free (${h.disk_free_gb ?? 176} GB Free of ${h.disk_total_gb ?? 220} GB)</span><strong>${h.disk_percent ?? 20}% Used</strong></div>
          <div class="metric-bar-track"><div class="metric-bar-fill" style="width:${Math.min(100, h.disk_percent || 0)}%;"></div></div>
        </div>
      `;
    }

    if (data.settings && document.activeElement !== settingIdleSec && document.activeElement !== settingGraceSec) {
      if (settingIdleSec) settingIdleSec.value = Math.round(data.settings.idle_timeout_sec || 600);
      if (settingGraceSec) settingGraceSec.value = Math.round(data.settings.disconnect_grace_sec || 300);
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
    const res = await fetch('/api/auth/me');
    if (!res.ok) return;
    const data = await res.json();
    currentUser = data.user;

    const save = currentUser.cyberarena_save || {};
    heroBadgeUser.textContent = `User: ${currentUser.username}`;
    heroBadgeSteam.textContent = `Steam: ${currentUser.steam_login_remembered ? 'Remembered ✓' : 'In-Stream Login'}`;
    heroBadgeSave.textContent = `CyberArena High Score: ${save.high_score || 0} (Runs: ${save.sessions_played || 0})`;

    profileDetails.innerHTML = `
      <div class="list-item"><span>Account Username</span><strong>${currentUser.username}</strong></div>
      <div class="list-item"><span>Account Role</span><strong>${currentUser.role.toUpperCase()}</strong></div>
      <div class="list-item"><span>Isolated Storage Path</span><code>data/users/${currentUser.username}/home/</code></div>
      <div class="list-item"><span>Steam Session Token</span><strong>${currentUser.steam_login_remembered ? 'Remembered ✓ (' + (currentUser.steam_account_hint || 'Saved') + ')' : 'Not signed in yet (Launch Steam Big Picture)'}</strong></div>
      <div class="list-item"><span>CyberArena 3D High Score</span><strong>${save.high_score || 0} pts (${save.sessions_played || 0} sessions played)</strong></div>
    `;

    const active = data.active_session;
    if (!active) {
      serverDot.className = 'status-dot';
      serverPillText.textContent = 'GPU Ready • 0/1 Active';
      btnResumeNav.style.display = 'none';
    } else if (active.username === currentUser.username) {
      serverDot.className = 'status-dot';
      serverPillText.textContent = `Playing: ${active.game_title}`;
      btnResumeNav.style.display = 'inline-flex';
      btnResumeNav.onclick = () => {
        streamOpen = true;
        streamViewport.classList.add('visible');
        handleSessionStateUpdate(data.my_session);
      };
    } else {
      serverDot.className = 'status-dot busy';
      serverPillText.textContent = `In use by ${active.username} (${active.game_title})`;
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

