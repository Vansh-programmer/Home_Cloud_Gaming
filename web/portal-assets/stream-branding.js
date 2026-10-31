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

  window.applyRyokuStreamBranding = (frame) => {
    try {
      const doc = frame.contentDocument;
      const app = doc?.querySelector('#app');
      if (!doc?.documentElement || !app) return;

      doc.title = 'Ryoku | Cloud Gaming';
      updateNode(app, doc);

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
      });
      observer.observe(app, {
        subtree: true,
        childList: true,
        characterData: true,
        attributes: true,
        attributeFilter: ['title', 'aria-label', 'alt', 'placeholder']
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
