(() => {
  const key = 'caudex-theme';
  const systemDark = window.matchMedia && window.matchMedia('(prefers-color-scheme: dark)').matches;
  const saved = localStorage.getItem(key);
  const initial = saved || (systemDark ? 'dark' : 'light');
  document.documentElement.dataset.theme = initial;

  function updateIcons() {
    document.querySelectorAll('[data-theme-icon]').forEach(el => {
      el.textContent = document.documentElement.dataset.theme === 'dark' ? '☀' : '◐';
    });
  }

  document.addEventListener('DOMContentLoaded', () => {
    updateIcons();
    document.querySelectorAll('[data-theme-toggle]').forEach(button => {
      button.addEventListener('click', () => {
        const next = document.documentElement.dataset.theme === 'dark' ? 'light' : 'dark';
        document.documentElement.dataset.theme = next;
        localStorage.setItem(key, next);
        updateIcons();
        window.dispatchEvent(new CustomEvent('caudex-theme-changed', {detail: {theme: next}}));
      });
    });
  });
})();
