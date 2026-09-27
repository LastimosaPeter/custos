(() => {
  'use strict';

  function enhanceTables() {
    document.querySelectorAll('.table-wrap table').forEach(table => {
      const headers = Array.from(table.querySelectorAll('thead th')).map(th => th.textContent.trim());
      table.querySelectorAll('tbody tr').forEach(row => {
        const cells = Array.from(row.children).filter(el => el.tagName === 'TD');
        cells.forEach((cell, index) => {
          if (!cell.hasAttribute('data-label') && !cell.hasAttribute('colspan')) {
            cell.setAttribute('data-label', headers[index] || '');
          }
        });
      });
    });
  }

  function setupMobileNav() {
    const toggle = document.querySelector('.mobile-nav-toggle');
    const header = document.querySelector('.site-header');
    if (!toggle || !header) return;

    const nav = header.querySelector('.admin-nav, .site-nav');
    if (!nav) {
      toggle.hidden = true;
      return;
    }

    const close = () => {
      document.body.classList.remove('mobile-nav-open');
      toggle.setAttribute('aria-expanded', 'false');
      toggle.setAttribute('aria-label', 'Open navigation');
      toggle.querySelector('span').textContent = '☰';
    };
    const open = () => {
      document.body.classList.add('mobile-nav-open');
      toggle.setAttribute('aria-expanded', 'true');
      toggle.setAttribute('aria-label', 'Close navigation');
      toggle.querySelector('span').textContent = '×';
    };

    toggle.addEventListener('click', event => {
      event.stopPropagation();
      document.body.classList.contains('mobile-nav-open') ? close() : open();
    });
    nav.addEventListener('click', event => {
      if (event.target.closest('a')) close();
    });
    document.addEventListener('click', event => {
      if (document.body.classList.contains('mobile-nav-open') && !header.contains(event.target)) close();
    });
    document.addEventListener('keydown', event => {
      if (event.key === 'Escape') close();
    });
    window.addEventListener('resize', () => {
      if (window.innerWidth > 1050) close();
    });
  }


  document.addEventListener('DOMContentLoaded', () => {
    enhanceTables();
    setupMobileNav();
  });
})();
