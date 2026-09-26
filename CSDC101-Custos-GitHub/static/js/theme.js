(() => {
  'use strict';
  const root = document.documentElement;
  const key = 'custos-theme';

  function resolvedTheme() {
    const saved = localStorage.getItem(key);
    if (saved === 'light' || saved === 'dark') return saved;
    return window.matchMedia && window.matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light';
  }

  function applyTheme(theme, persist = false) {
    root.dataset.theme = theme;
    if (persist) localStorage.setItem(key, theme);
    document.querySelectorAll('[data-theme-toggle]').forEach(btn => {
      const dark = theme === 'dark';
      btn.setAttribute('aria-label', dark ? 'Switch to light mode' : 'Switch to dark mode');
      btn.setAttribute('title', dark ? 'Switch to light mode' : 'Switch to dark mode');
      const icon = btn.querySelector('[data-theme-icon]');
      if (icon) icon.textContent = dark ? '☀' : '☾';
    });
  }

  applyTheme(root.dataset.theme || resolvedTheme());

  document.addEventListener('DOMContentLoaded', () => {
    applyTheme(root.dataset.theme || resolvedTheme());
    document.querySelectorAll('[data-theme-toggle]').forEach(btn => {
      btn.addEventListener('click', () => {
        applyTheme(root.dataset.theme === 'dark' ? 'light' : 'dark', true);
      });
    });
  });
})();
