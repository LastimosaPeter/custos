(() => {
  'use strict';

  // CSP-safe replacement for inline onchange handlers. Used by every
  // assessment context picker and other selects that should reload their form.
  document.addEventListener('change', event => {
    const select = event.target.closest('select[data-auto-submit]');
    if (!select || select.disabled || !select.form) return;
    if (select.dataset.submitPending === '1') return;
    select.dataset.submitPending = '1';
    select.setAttribute('aria-busy', 'true');
    if (typeof select.form.requestSubmit === 'function') select.form.requestSubmit();
    else select.form.submit();
  });

  // CSP-safe confirmation for destructive/key-regeneration forms. Inline
  // onsubmit handlers are blocked by Custos' own script-src 'self' policy.
  document.addEventListener('submit', event => {
    const form = event.target.closest('form[data-confirm]');
    if (!form) return;
    const message = (form.dataset.confirm || '').trim();
    if (message && !window.confirm(message)) {
      event.preventDefault();
      const autoSelect = form.querySelector('select[data-auto-submit][data-submit-pending="1"]');
      if (autoSelect) {
        delete autoSelect.dataset.submitPending;
        autoSelect.removeAttribute('aria-busy');
      }
    }
  }, true);
})();
