/** Rebrand visible Moonlight Web chrome inside the same-origin stream frame. */
(() => {
  const brandText = (value) => value.replace(/Moonlight\s*Web|Moonlight/gi, 'Ryoku');

  function updateText(node) {
    if (node.nodeType !== Node.TEXT_NODE || !node.parentElement) return;
    if (node.parentElement.closest('script, style, noscript')) return;
    if (node.parentElement.matches('.app-footer [data-i18n="footer.tagline"]')) {
      if (node.nodeValue !== 'Ryoku Cloud Gaming') node.nodeValue = 'Ryoku Cloud Gaming';
      return;
    }
    const updated = brandText(node.nodeValue || '');
    if (updated !== node.nodeValue) node.nodeValue = updated;
  }

  function updateAttributes(element) {
    if (!element || element.nodeType !== 1) return;
    for (const attribute of ['title', 'aria-label', 'alt', 'placeholder']) {
      const value = element.getAttribute(attribute);
      if (value) {
        const updated = brandText(value);
        if (updated !== value) element.setAttribute(attribute, updated);
      }
    }
  }

  function updateNode(node, doc) {
    if (node.nodeType === Node.TEXT_NODE) {
      updateText(node);
      return;
    }
    if (node.nodeType !== 1) return;
    updateAttributes(node);
    const walker = doc.createTreeWalker(node, doc.defaultView.NodeFilter.SHOW_TEXT);
    while (walker.nextNode()) updateText(walker.currentNode);
    for (const element of node.querySelectorAll('[title], [aria-label], [alt], [placeholder]')) {
      updateAttributes(element);
    }
  }

  function injectDeepEmbedStyles(doc) {
    if (!doc?.head || doc.getElementById('ryoku-deep-embed-style')) return;
    const style = doc.createElement('style');
    style.id = 'ryoku-deep-embed-style';
    style.textContent = `
      * {
        border-radius: 0 !important;
      }
      html, body, #app {
        background: #04070f !important;
        overflow: hidden !important;
      }
      .app-header,
      .app-footer,
      .discord-fab,
      #btn-bmc,
      .stream-header {
        display: none !important;
      }
      .hosts-view {
        opacity: 0 !important;
        pointer-events: none !important;
        position: fixed !important;
        inset: 0 !important;
        z-index: -1 !important;
      }
      .stream-view,
      .stream-stage,
      .stream-video-container,
      #stream-video {
        width: 100vw !important;
        height: 100vh !important;
        max-width: 100vw !important;
        max-height: 100vh !important;
        margin: 0 !important;
        padding: 0 !important;
        background: #000 !important;
      }
      #stream-stats-overlay {
        top: 52px !important;
        left: 18px !important;
        background: rgba(5, 8, 17, 0.88) !important;
        border: 1px solid rgba(255, 255, 255, 0.18) !important;
        backdrop-filter: blur(16px) !important;
      }
      #ryoku-boot-splash {
        position: fixed;
        inset: 0;
        z-index: 5;
        display: flex;
        flex-direction: column;
        align-items: center;
        justify-content: center;
        gap: 14px;
        background: radial-gradient(circle at 50% 35%, rgba(0, 112, 209, 0.22), #04070f 65%);
        color: #f8fafc;
        font-family: Inter, -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
        letter-spacing: 0.08em;
        text-transform: uppercase;
        font-size: 0.82rem;
        font-weight: 600;
        pointer-events: none;
      }
      #ryoku-boot-splash .ryoku-boot-bar {
        width: 220px;
        height: 3px;
        background: rgba(255, 255, 255, 0.14);
        position: relative;
        overflow: hidden;
      }
      #ryoku-boot-splash .ryoku-boot-bar::after {
        content: '';
        position: absolute;
        inset: 0;
        width: 45%;
        background: #0070d1;
        box-shadow: 0 0 12px #0070d1;
        animation: ryokuSlide 1.1s infinite ease-in-out;
      }
      @keyframes ryokuSlide {
        0% { transform: translateX(-110%); }
        100% { transform: translateX(250%); }
      }
    `;
    doc.head.appendChild(style);

    if (doc.body && !doc.getElementById('ryoku-boot-splash')) {
      const splash = doc.createElement('div');
      splash.id = 'ryoku-boot-splash';
      splash.innerHTML = '<span>INITIALIZING RYOKU STREAM LINK</span><div class="ryoku-boot-bar"></div>';
      doc.body.appendChild(splash);
    }
  }

  function syncBootSplash(doc) {
    const splash = doc?.getElementById('ryoku-boot-splash');
    if (!splash) return;
    const hasStream = Boolean(doc.querySelector('.stream-view, #stream-video, .stream-startup-loader'));
    splash.style.display = hasStream ? 'none' : 'flex';
  }

  function attemptAutoLaunch(doc) {
    syncBootSplash(doc);
    if (!doc || doc.__ryokuAutoLaunched) return;
    let targetApp = '';
    try {
      targetApp = (sessionStorage.getItem('ryoku-launch-app') || '').trim().toLowerCase();
    } catch (_error) {
      return;
    }
    if (!targetApp) return;
    if (doc.querySelector('.stream-view, .app-card--launching')) return;
    const cards = doc.querySelectorAll('.host-apps[data-loaded="1"] .app-card');
    if (!cards.length) return;
    let keyword = targetApp;
    if (targetApp.includes('heroic')) keyword = 'heroic';
    else if (targetApp.includes('steam')) keyword = 'steam';
    else if (targetApp.includes('tux racer')) keyword = 'extreme tux racer';
    else if (targetApp.includes('supertux')) keyword = 'supertux';
    else if (targetApp.includes('luanti') || targetApp.includes('minetest')) keyword = 'luanti';
    for (const card of cards) {
      const text = (card.textContent || '').toLowerCase();
      if (text.includes(keyword)) {
        doc.__ryokuAutoLaunched = true;
        try {
          sessionStorage.removeItem('ryoku-launch-app');
        } catch (_error) {
          // Ignore storage removal errors.
        }
        card.click();
        return;
      }
    }
  }

  function stabilizeStreamTransport(win) {
    if (!win || win.__ryokuTransportStabilized) return;
    win.__ryokuTransportStabilized = true;
    try {
      if (win.indexedDB) {
        win.indexedDB.deleteDatabase('mw-pairing');
      }
      win.localStorage?.removeItem('mw_hevc_failed');
    } catch (_error) {
      // Ignore storage access errors.
    }
    try {
      win.eval(`
        import('/js/ui/StreamView.js').then(({ StreamView }) => {
          if (!StreamView || !StreamView.prototype) return;
          StreamView.prototype._recordCongestionEvent = function() {};
          Object.defineProperty(StreamView.prototype, 'onCongestion', {
            configurable: true,
            get() { return null; },
            set() {}
          });
        }).catch(() => {});

        import('/js/app.js').then(({ MoonlightApp }) => {
          if (!MoonlightApp || MoonlightApp.__ryokuHooked) return;
          MoonlightApp.__ryokuHooked = true;
          const origQuit = MoonlightApp._onStreamingQuit?.bind(MoonlightApp);
          MoonlightApp._onStreamingQuit = function(...args) {
            const res = origQuit ? origQuit(...args) : undefined;
            try {
              window.parent?.postMessage({ type: 'ryoku-stream-quit' }, window.location.origin);
            } catch (_e) {}
            return res;
          };
          window.addEventListener('message', (event) => {
            if (event.origin !== window.location.origin) return;
            const msg = event.data;
            if (!msg || typeof msg !== 'object') return;
            if (msg.type === 'ryoku-toggle-stats') {
              const sv = MoonlightApp.streamView;
              if (sv && sv._overlayEl) {
                sv._showPerfStats = !sv._showPerfStats;
                sv._statsClosed = !sv._showPerfStats;
                sv._overlayEl.style.display = sv._showPerfStats ? '' : 'none';
              }
            }
          });
        }).catch(() => {});
      `);
    } catch (_error) {
      // Ignore if frame context is not ready yet.
    }
  }

  window.applyRyokuStreamBranding = (frame) => {
    try {
      const doc = frame.contentDocument;
      const app = doc?.querySelector('#app');
      if (!doc?.documentElement || !app) return;
      if (doc.__ryokuBrandingApplied) {
        attemptAutoLaunch(doc);
        return;
      }
      doc.__ryokuBrandingApplied = true;

      injectDeepEmbedStyles(doc);
      stabilizeStreamTransport(frame.contentWindow);
      doc.title = 'Ryoku | Cloud Gaming';
      updateNode(app, doc);
      attemptAutoLaunch(doc);

      const favicon = doc.querySelector('link[rel~="icon"]');
      if (favicon) {
        favicon.href = '/portal-assets/ryoku-mark.svg';
        favicon.type = 'image/svg+xml';
      }
      const appleIcon = doc.querySelector('link[rel="apple-touch-icon"]');
      if (appleIcon) appleIcon.href = '/portal-assets/ryoku-mark.svg';
      const manifest = doc.querySelector('link[rel="manifest"]');
      if (manifest) manifest.href = '/portal-assets/ryoku-manifest.webmanifest';
      const mobileTitle = doc.querySelector('meta[name="apple-mobile-web-app-title"]');
      if (mobileTitle) mobileTitle.content = 'Ryoku';

      const observer = new MutationObserver((records) => {
        for (const record of records) {
          if (record.type === 'characterData') updateText(record.target);
          if (record.type === 'childList') {
            for (const node of record.addedNodes) updateNode(node, doc);
          }
          if (record.type === 'attributes') updateAttributes(record.target);
        }
        attemptAutoLaunch(doc);
      });
      observer.observe(app, {
        subtree: true,
        childList: true,
        characterData: true,
        attributes: true,
        attributeFilter: ['title', 'aria-label', 'alt', 'placeholder', 'data-loaded']
      });

      const titleNode = doc.querySelector('title');
      if (titleNode) {
        observer.observe(titleNode, { childList: true, characterData: true, subtree: true });
      }
    } catch (_error) {
      // The frame can be navigating or blocked; the stream itself remains usable.
    }
  };
})();
