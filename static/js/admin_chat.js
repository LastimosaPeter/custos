(() => {
  'use strict';
  const root = document.querySelector('[data-admin-chat]');
  const list = document.getElementById('adminChatMessages');
  const form = root?.querySelector('.admin-chat-form');
  if (!root || !list) return;
  const url = root.dataset.chatUrl;
  const sendUrl = root.dataset.chatSendUrl || form?.action;
  const csrf = document.querySelector('meta[name="csrf-token"]')?.content || '';
  let lastSignature = '';

  function render(messages, forceBottom = false) {
    const signature = JSON.stringify(messages.map(m => [m.id, m.sender, m.message, m.created_at]));
    if (signature === lastSignature) return;
    const nearBottom = list.scrollHeight - list.scrollTop - list.clientHeight < 60;
    lastSignature = signature;
    list.innerHTML = '';
    if (!messages.length) {
      const empty = document.createElement('div');
      empty.className = 'chat-empty';
      empty.textContent = 'No messages yet.';
      list.appendChild(empty);
      return;
    }
    for (const m of messages) {
      const item = document.createElement('div');
      item.className = `chat-message ${m.sender}`;
      const meta = document.createElement('div');
      meta.className = 'chat-message-meta';
      meta.textContent = `${m.sender === 'student' ? 'Student' : 'Instructor'} · ${m.created_at}`;
      const body = document.createElement('div');
      body.textContent = m.message;
      item.append(meta, body);
      list.appendChild(item);
    }
    if (forceBottom || nearBottom) list.scrollTop = list.scrollHeight;
  }

  async function refresh(forceBottom = false) {
    try {
      const res = await fetch(url, {credentials: 'same-origin', cache: 'no-store'});
      if (!res.ok) return;
      const data = await res.json();
      if (data.ok) render(data.messages || [], forceBottom);
    } catch (_) {}
  }

  if (form && sendUrl) {
    form.addEventListener('submit', async event => {
      event.preventDefault();
      const input = form.querySelector('textarea[name="message"]');
      const button = form.querySelector('button[type="submit"]');
      const message = input?.value.trim() || '';
      if (!message) return;
      button.disabled = true;
      try {
        const res = await fetch(sendUrl, {
          method: 'POST',
          credentials: 'same-origin',
          headers: {'Content-Type':'application/json','Accept':'application/json','X-CSRFToken':csrf},
          body: JSON.stringify({message})
        });
        const data = await res.json();
        if (data.ok) {
          input.value = '';
          lastSignature = '';
          await refresh(true);
          input.focus();
        }
      } catch (_) {} finally { button.disabled = false; }
    });
  }

  refresh(true);
  setInterval(() => refresh(false), 3000);
})();
