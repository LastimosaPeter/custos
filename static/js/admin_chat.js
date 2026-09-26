(() => {
  'use strict';
  const root = document.querySelector('[data-admin-chat]');
  const list = document.getElementById('adminChatMessages');
  if (!root || !list) return;
  const url = root.dataset.chatUrl;
  let lastSignature = '';

  function render(messages) {
    const signature = JSON.stringify(messages.map(m => [m.id, m.sender, m.message, m.created_at]));
    if (signature === lastSignature) return;
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
    list.scrollTop = list.scrollHeight;
  }

  async function refresh() {
    try {
      const res = await fetch(url, {credentials: 'same-origin', cache: 'no-store'});
      if (!res.ok) return;
      const data = await res.json();
      if (data.ok) render(data.messages || []);
    } catch (_) {}
  }

  refresh();
  setInterval(refresh, 3000);
})();
