(() => {
  'use strict';
  const root = document.documentElement;

  function applyTheme(theme) {
    root.dataset.theme = theme === 'dark' ? 'dark' : 'light';
    document.querySelectorAll('[data-theme-toggle]').forEach(btn => {
      const dark = root.dataset.theme === 'dark';
      btn.setAttribute('aria-label', dark ? 'Switch to light mode' : 'Switch to dark mode');
      btn.setAttribute('title', dark ? 'Switch to light mode' : 'Switch to dark mode');
      const icon = btn.querySelector('[data-theme-icon]');
      if (icon) icon.textContent = dark ? '☀️' : '🌙';
    });
  }

  async function saveTheme(theme) {
    const csrf = document.querySelector('meta[name="csrf-token"]')?.content || '';
    const response = await fetch('/api/preferences/theme', {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        'X-CSRFToken': csrf,
      },
      body: JSON.stringify({ theme }),
      credentials: 'same-origin',
    });
    if (!response.ok) throw new Error(`Theme save failed (${response.status})`);
  }

  applyTheme(root.dataset.theme || 'light');

  document.addEventListener('DOMContentLoaded', () => {
    applyTheme(root.dataset.theme || 'light');
    document.querySelectorAll('[data-theme-toggle]').forEach(btn => {
      btn.addEventListener('click', async () => {
        const next = root.dataset.theme === 'dark' ? 'light' : 'dark';
        applyTheme(next);
        try {
          await saveTheme(next);
        } catch (err) {
          console.error(err);
        }
      });
    });
  });
})();
