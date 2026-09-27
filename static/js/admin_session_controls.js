(() => {
  'use strict';
  const root = document.querySelector('[data-session-control]');
  if (!root) return;
  const sid = Number(root.dataset.sessionId || 0);
  const csrf = document.querySelector('meta[name="csrf-token"]')?.content || '';
  root.addEventListener('click', async event => {
    const btn = event.target.closest('[data-monitor-action]');
    if (!btn || !sid) return;
    const action = btn.dataset.monitorAction;
    const question = action === 'mark_done' ? 'Remove this student from Live Monitor? This will not submit or change the exam.' : action === 'clear_security' ? 'Clear the active security lock? Recorded violations will remain.' : 'Return this attempt to Live Monitor?';
    if (!window.confirm(question)) return;
    btn.disabled = true;
    try {
      const res = await fetch(`/admin/monitor/session/${sid}/action`, {method:'POST',credentials:'same-origin',headers:{'Content-Type':'application/json','X-CSRFToken':csrf},body:JSON.stringify({action})});
      const data = await res.json();
      if (data.ok) window.location.reload();
      else window.alert(data.error || 'Could not update the session.');
    } catch (_) { window.alert('Could not update the session.'); }
    finally { btn.disabled = false; }
  });
})();
