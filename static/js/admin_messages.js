(() => {
  'use strict';
  const page = document.querySelector('.messages-page');
  if (!page) return;
  const list = document.getElementById('messageThreadList');
  const body = document.getElementById('messageConversationBody');
  const nameEl = document.getElementById('messageStudentName');
  const metaEl = document.getElementById('messageStudentMeta');
  const review = document.getElementById('messageReviewLink');
  const form = document.getElementById('messageReplyForm');
  const input = document.getElementById('messageReplyInput');
  const csrf = document.querySelector('meta[name="csrf-token"]')?.content || '';
  const requestedSid = Number(new URLSearchParams(window.location.search).get('session') || 0);
  let currentSid = requestedSid || Number(list.querySelector('[data-session-id]')?.dataset.sessionId || 0);
  let messageSignature = '';

  const esc = value => String(value ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  const displayName = s => (s.last_name || s.first_name) ? `${s.last_name || ''}${s.last_name && s.first_name ? ', ' : ''}${s.first_name || ''}` : (s.student_name || s.email || 'Student');

  function renderMessages(messages) {
    const signature = JSON.stringify(messages.map(m => [m.id,m.sender,m.message,m.created_at]));
    if (signature === messageSignature) return;
    const keepBottom = body.scrollHeight - body.scrollTop - body.clientHeight < 80;
    messageSignature = signature;
    body.innerHTML = messages.length ? messages.map(m => `<div class="chat-message ${esc(m.sender)}"><div class="chat-message-meta">${m.sender === 'student' ? 'Student' : 'Instructor'} · ${esc(m.created_at)}</div><div>${esc(m.message)}</div></div>`).join('') : '<div class="chat-empty">No messages in this conversation yet.</div>';
    if (keepBottom || messages.length <= 2) body.scrollTop = body.scrollHeight;
  }

  async function loadThread(sid) {
    if (!sid) return;
    currentSid = Number(sid);
    list.querySelectorAll('[data-session-id]').forEach(b => b.classList.toggle('active', Number(b.dataset.sessionId) === currentSid));
    try {
      const res = await fetch(`/admin/messages/${currentSid}`, {credentials:'same-origin', cache:'no-store'});
      const data = await res.json();
      if (!data.ok) return;
      nameEl.textContent = displayName(data.student);
      metaEl.textContent = `${data.student.program || '—'} ${data.student.class_section || ''} · ${data.student.batch_name || ''}`;
      review.href = `/admin/session/${currentSid}`;
      review.classList.remove('hidden');
      form.hidden = false;
      renderMessages(data.messages || []);
      const btn = list.querySelector(`[data-session-id="${currentSid}"]`);
      btn?.querySelector('.message-thread-unread')?.remove();
    } catch (_) {}
  }

  async function refreshThreads() {
    try {
      const res = await fetch(page.dataset.threadsUrl, {credentials:'same-origin', cache:'no-store'});
      const data = await res.json();
      if (!data.ok) return;
      const threads = data.threads || [];
      if (!threads.length) {
        list.innerHTML = '<div class="messages-empty">No student conversations yet.</div>';
        return;
      }
      list.innerHTML = threads.map(t => `<button type="button" class="message-thread ${Number(t.id) === currentSid ? 'active' : ''}" data-session-id="${Number(t.id)}"><span class="message-thread-name">${esc(displayName(t))}</span><span class="message-thread-meta">${esc(t.program || '—')} ${esc(t.class_section || '')} · ${esc(t.batch_name || '')}</span><span class="message-thread-preview">${esc(t.last_message || 'No message yet')}</span>${Number(t.unread_messages || 0) ? `<span class="message-thread-unread">${Number(t.unread_messages)}</span>` : ''}</button>`).join('');
      if (!currentSid) loadThread(threads[0].id);
    } catch (_) {}
  }

  list.addEventListener('click', event => {
    const btn = event.target.closest('[data-session-id]');
    if (btn) loadThread(btn.dataset.sessionId);
  });

  form.addEventListener('submit', async event => {
    event.preventDefault();
    const message = input.value.trim();
    if (!message || !currentSid) return;
    const button = form.querySelector('button[type="submit"]');
    button.disabled = true;
    try {
      const res = await fetch(`/admin/session/${currentSid}/chat`, {
        method:'POST', credentials:'same-origin',
        headers:{'Content-Type':'application/json','Accept':'application/json','X-CSRFToken':csrf},
        body:JSON.stringify({message})
      });
      const data = await res.json();
      if (data.ok) {
        input.value = '';
        messageSignature = '';
        await loadThread(currentSid);
        await refreshThreads();
      }
    } catch (_) {} finally { button.disabled = false; input.focus(); }
  });

  if (currentSid) loadThread(currentSid);
  setInterval(() => { refreshThreads(); if (currentSid) loadThread(currentSid); }, 4000);
})();
