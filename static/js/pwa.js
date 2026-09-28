(() => {
  'use strict';

  const standalone = () =>
    window.matchMedia('(display-mode: standalone)').matches ||
    window.matchMedia('(display-mode: fullscreen)').matches ||
    window.navigator.standalone === true;

  const ua = navigator.userAgent || '';
  const isIOS = /iPad|iPhone|iPod/.test(ua) || (navigator.platform === 'MacIntel' && navigator.maxTouchPoints > 1);
  const isAndroid = /Android/i.test(ua);

  function applyModeClass() {
    const installed = standalone();
    document.documentElement.classList.toggle('pwa-standalone', installed);
    document.documentElement.dataset.pwaMode = installed ? 'standalone' : 'browser';
    window.CustosPWA = Object.assign(window.CustosPWA || {}, {
      isStandalone: installed,
      isIOS,
      isAndroid
    });
    return installed;
  }

  applyModeClass();
  window.matchMedia('(display-mode: standalone)').addEventListener?.('change', applyModeClass);
  window.matchMedia('(display-mode: fullscreen)').addEventListener?.('change', applyModeClass);

  if ('serviceWorker' in navigator) {
    window.addEventListener('load', () => {
      const revision = encodeURIComponent(window.CUSTOS_ASSET_REVISION || '1.0-goliathus-portable-r2');
      navigator.serviceWorker.register(`/sw.js?v=${revision}`, {scope: '/', updateViaCache: 'none'}).catch(() => {});
    });
  }

  let deferredInstallPrompt = null;
  const installButtons = () => [...document.querySelectorAll('[data-pwa-install]')];
  const installDialog = () => document.getElementById('pwaInstallDialog');

  function setInstallVisibility() {
    const installed = standalone();
    const shouldShow = !installed && (Boolean(deferredInstallPrompt) || isIOS || isAndroid);
    installButtons().forEach(btn => {
      btn.hidden = !shouldShow;
      btn.setAttribute('aria-hidden', shouldShow ? 'false' : 'true');
    });
    document.querySelectorAll('[data-pwa-installed]').forEach(el => {
      el.hidden = !installed;
    });
  }

  window.addEventListener('beforeinstallprompt', event => {
    event.preventDefault();
    deferredInstallPrompt = event;
    setInstallVisibility();
  });

  window.addEventListener('appinstalled', () => {
    deferredInstallPrompt = null;
    applyModeClass();
    setInstallVisibility();
  });

  function showInstallGuide() {
    const dialog = installDialog();
    if (!dialog) return;
    const ios = dialog.querySelector('[data-install-ios]');
    const android = dialog.querySelector('[data-install-android]');
    const generic = dialog.querySelector('[data-install-generic]');
    if (ios) ios.hidden = !isIOS;
    if (android) android.hidden = !isAndroid;
    if (generic) generic.hidden = isIOS || isAndroid;
    if (typeof dialog.showModal === 'function') dialog.showModal();
    else dialog.setAttribute('open', '');
  }

  document.addEventListener('click', async event => {
    const install = event.target.closest('[data-pwa-install]');
    if (install) {
      if (standalone()) return;
      if (deferredInstallPrompt) {
        deferredInstallPrompt.prompt();
        try { await deferredInstallPrompt.userChoice; } catch (_) {}
        deferredInstallPrompt = null;
        setInstallVisibility();
      } else {
        showInstallGuide();
      }
      return;
    }

    if (event.target.closest('[data-pwa-dialog-close]')) {
      const dialog = installDialog();
      if (dialog?.open && typeof dialog.close === 'function') dialog.close();
      else dialog?.removeAttribute('open');
    }
  });

  document.addEventListener('DOMContentLoaded', setInstallVisibility);
})();
