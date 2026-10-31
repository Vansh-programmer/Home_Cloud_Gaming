/** Apply Ryoku labels to the same-origin Moonlight Web stream frame. */
(() => {
  const observers = new WeakMap();

  window.applyRyokuStreamBranding = (frame) => {
    try {
      const doc = frame.contentDocument;
      if (!doc?.documentElement) return;

      const updateLabels = () => {
        if (doc.title !== 'Ryoku | Cloud Gaming') doc.title = 'Ryoku | Cloud Gaming';

        const heading = doc.querySelector('.app-header h1');
        if (heading && heading.textContent !== 'Ryoku') heading.textContent = 'Ryoku';

        const tagline = doc.querySelector('.app-footer [data-i18n="footer.tagline"]');
        if (tagline && tagline.textContent !== 'Ryoku Cloud Gaming') {
          tagline.textContent = 'Ryoku Cloud Gaming';
        }

        const mobileTitle = doc.querySelector('meta[name="apple-mobile-web-app-title"]');
        if (mobileTitle && mobileTitle.content !== 'Ryoku') mobileTitle.content = 'Ryoku';
      };

      observers.get(frame)?.disconnect();
      updateLabels();

      const observer = new MutationObserver(updateLabels);
      for (const target of [doc.querySelector('.app-header'), doc.querySelector('.app-footer'), doc.querySelector('title')]) {
        if (target) observer.observe(target, { childList: true, characterData: true, subtree: true });
      }
      observers.set(frame, observer);
    } catch (_error) {
      // The stream frame may still be navigating; try again on its next load.
    }
  };
})();
