(() => {
  'use strict';
  const boot = window.CAUDEX_BOOT;
  const app = document.getElementById('workspaceApp');
  if (!boot || !app) return;

  const ROOT = '__ROOT__';
  const editor = document.getElementById('codeEditor');
  const lineNumbers = document.getElementById('lineNumbers');
  const editorShell = document.getElementById('editorShell');
  const caretLayer = document.getElementById('remoteCaretLayer');
  const pointerLayer = document.getElementById('remotePointerLayer');
  const connectionBadge = document.getElementById('connectionBadge');
  const saveState = document.getElementById('saveState');
  const participantList = document.getElementById('participantList');
  const peopleCount = document.getElementById('peopleCount');
  const mobilePeopleCount = document.getElementById('mobilePeopleCount');
  const runButton = document.getElementById('runButton');
  const mobileRunButton = document.getElementById('mobileRunButton');
  const runStatus = document.getElementById('runStatus');
  const consoleOutput = document.getElementById('consoleOutput');
  const stdinInput = document.getElementById('stdinInput');
  const importFile = document.getElementById('importFile');
  const exportButton = document.getElementById('exportButton');
  const copyCodeButton = document.getElementById('copyCodeButton');
  const mobileImportButton = document.getElementById('mobileImportButton');
  const mobileExportButton = document.getElementById('mobileExportButton');
  const chatMessages = document.getElementById('chatMessages');
  const chatForm = document.getElementById('chatForm');
  const chatInput = document.getElementById('chatInput');
  const mobileChatDot = document.getElementById('mobileChatDot');
  const toastStack = document.getElementById('toastStack');
  const jamCanvas = document.getElementById('jamCanvas');
  const boardColor = document.getElementById('boardColor');
  const boardWidth = document.getElementById('boardWidth');
  const clearBoardButton = document.getElementById('clearBoardButton');
  const focusButton = document.getElementById('focusButton');
  const focusModal = document.getElementById('focusModal');
  const enterFullscreenButton = document.getElementById('enterFullscreenButton');

  const state = {
    ws: null,
    connected: false,
    helloReceived: false,
    reconnectTimer: null,
    reconnectDelay: 700,
    crdt: {nodes: {}},
    visibleIds: [],
    idToIndex: new Map(),
    renderedText: '',
    participants: new Map(),
    securityCounts: new Map(),
    remoteCarets: new Map(),
    pointerTimers: new Map(),
    pendingOps: [],
    whiteboard: [],
    whiteboardIds: new Set(),
    opCounter: 0,
    composing: false,
    mode: 'code',
    focusEngaged: false,
    lastPointerSent: 0,
  };

  const pendingKey = `caudex-room-${boot.roomCode}-pending-v1`;
  const draftKey = `caudex-room-${boot.roomCode}-draft-v1`;

  function toast(message, kind = '') {
    if (!toastStack) return;
    const el = document.createElement('div');
    el.className = `toast ${kind}`.trim();
    el.textContent = message;
    toastStack.appendChild(el);
    setTimeout(() => el.remove(), 3200);
  }

  function setConnection(status, label) {
    connectionBadge.classList.remove('online', 'offline', 'connecting');
    connectionBadge.classList.add(status);
    const text = connectionBadge.querySelector('span');
    if (text) text.textContent = label;
  }

  function loadPending() {
    try {
      const parsed = JSON.parse(localStorage.getItem(pendingKey) || '[]');
      if (Array.isArray(parsed)) state.pendingOps = parsed.filter(op => op && op.op_id);
    } catch (_) {
      state.pendingOps = [];
    }
  }

  function savePending() {
    try {
      localStorage.setItem(pendingKey, JSON.stringify(state.pendingOps.slice(-500)));
    } catch (_) {}
    saveState.textContent = state.pendingOps.length ? (state.connected ? 'Syncing…' : 'Saved offline') : (state.connected ? 'Synced' : 'Saved offline');
  }

  function saveDraft() {
    try {
      localStorage.setItem(draftKey, JSON.stringify({source: editor.value, updatedAt: Date.now()}));
    } catch (_) {}
  }

  // ---------- CRDT ----------
  function normalizeCrdt(raw) {
    const out = {nodes: {}};
    if (!raw || typeof raw !== 'object' || !raw.nodes || typeof raw.nodes !== 'object') return out;
    Object.entries(raw.nodes).forEach(([id, node]) => {
      if (!node || typeof node !== 'object') return;
      if (typeof id !== 'string' || typeof node.after !== 'string' || typeof node.ch !== 'string' || node.ch.length !== 1) return;
      out.nodes[id] = {id, after: node.after, ch: node.ch, deleted: !!node.deleted};
    });
    return out;
  }

  function crdtOrder() {
    const nodes = state.crdt.nodes || {};
    const children = new Map();
    const pushChild = (parent, id) => {
      if (!children.has(parent)) children.set(parent, []);
      children.get(parent).push(id);
    };
    Object.entries(nodes).forEach(([id, node]) => {
      let parent = node.after;
      if (parent !== ROOT && !nodes[parent]) parent = ROOT;
      pushChild(parent, id);
    });
    children.forEach(list => list.sort());
    const order = [];
    const stack = [...(children.get(ROOT) || [])].reverse();
    const visited = new Set();
    while (stack.length) {
      const id = stack.pop();
      if (visited.has(id)) continue;
      visited.add(id);
      order.push(id);
      const kids = children.get(id) || [];
      for (let i = kids.length - 1; i >= 0; i--) stack.push(kids[i]);
    }
    Object.keys(nodes).sort().forEach(id => {
      if (!visited.has(id)) order.push(id);
    });
    return order;
  }

  function renderCrdt() {
    const chars = [];
    const visible = [];
    const idToIndex = new Map();
    for (const id of crdtOrder()) {
      const node = state.crdt.nodes[id];
      if (!node || node.deleted) continue;
      idToIndex.set(id, visible.length);
      visible.push(id);
      chars.push(node.ch);
    }
    state.visibleIds = visible;
    state.idToIndex = idToIndex;
    state.renderedText = chars.join('');
    return state.renderedText;
  }

  function applyCrdtOp(op) {
    if (!op) return;
    const nodes = state.crdt.nodes;
    for (const item of op.inserts || []) {
      if (!item || typeof item.id !== 'string' || nodes[item.id]) continue;
      if (typeof item.after !== 'string' || typeof item.ch !== 'string' || item.ch.length !== 1) continue;
      nodes[item.id] = {id: item.id, after: item.after, ch: item.ch, deleted: false};
    }
    for (const id of op.deletes || []) {
      if (nodes[id]) nodes[id].deleted = true;
    }
  }

  function selectionAnchors() {
    const make = index => {
      if (index <= 0) return {before: ROOT, fallback: 0};
      const id = state.visibleIds[Math.min(index - 1, state.visibleIds.length - 1)];
      return {before: id || ROOT, fallback: index};
    };
    return {start: make(editor.selectionStart), end: make(editor.selectionEnd)};
  }

  function indexAfterAnchor(anchor) {
    if (!anchor || anchor.before === ROOT) return 0;
    const idx = state.idToIndex.get(anchor.before);
    if (typeof idx === 'number') return idx + 1;
    return Math.min(anchor.fallback || 0, state.visibleIds.length);
  }

  function syncEditorFromCrdt(preserve = true) {
    const anchors = preserve ? selectionAnchors() : null;
    const text = renderCrdt();
    if (editor.value !== text) editor.value = text;
    if (anchors && document.activeElement === editor) {
      const start = indexAfterAnchor(anchors.start);
      const end = indexAfterAnchor(anchors.end);
      editor.setSelectionRange(start, end);
    }
    updateLineNumbers();
    if (window.CaudexSyntax) window.CaudexSyntax.sync(editor);
    renderRemoteCarets();
    saveDraft();
  }

  function nextNodeId() {
    state.opCounter += 1;
    return `${boot.participantId}:${Date.now().toString(36)}:${String(state.opCounter).padStart(6, '0')}`;
  }

  function diffSingleSplice(oldText, newText) {
    let prefix = 0;
    const minLen = Math.min(oldText.length, newText.length);
    while (prefix < minLen && oldText[prefix] === newText[prefix]) prefix++;
    let oldSuffix = oldText.length;
    let newSuffix = newText.length;
    while (oldSuffix > prefix && newSuffix > prefix && oldText[oldSuffix - 1] === newText[newSuffix - 1]) {
      oldSuffix--;
      newSuffix--;
    }
    return {start: prefix, oldEnd: oldSuffix, inserted: newText.slice(prefix, newSuffix)};
  }

  function createLocalOpFromEditor() {
    if (!boot.capabilities.edit) return null;
    const oldText = state.renderedText;
    const newText = editor.value;
    if (oldText === newText) return null;
    const splice = diffSingleSplice(oldText, newText);
    const deletes = state.visibleIds.slice(splice.start, splice.oldEnd);
    let after = splice.start === 0 ? ROOT : state.visibleIds[splice.start - 1];
    const inserts = [];
    for (const ch of splice.inserted) {
      const id = nextNodeId();
      inserts.push({id, after, ch});
      after = id;
    }
    const op = {
      type: 'crdt_op',
      op_id: `${boot.participantId}:${Date.now().toString(36)}:op:${state.opCounter}`,
      inserts,
      deletes,
    };
    applyCrdtOp(op);
    syncEditorFromCrdt(false);
    state.pendingOps.push(op);
    savePending();
    sendOp(op);
    return op;
  }

  function sendOp(op) {
    if (!state.connected || !state.helloReceived || !state.ws || state.ws.readyState !== WebSocket.OPEN) return;
    try { state.ws.send(JSON.stringify(op)); } catch (_) {}
  }

  function resendPending() {
    state.pendingOps.forEach(op => sendOp(op));
  }

  function acknowledge(opId) {
    if (!opId) return;
    const before = state.pendingOps.length;
    state.pendingOps = state.pendingOps.filter(op => op.op_id !== opId);
    if (state.pendingOps.length !== before) savePending();
  }

  // ---------- Editor ----------
  function updateLineNumbers() {
    const count = Math.max(1, editor.value.split('\n').length);
    lineNumbers.textContent = Array.from({length: count}, (_, i) => i + 1).join('\n');
    lineNumbers.scrollTop = editor.scrollTop;
  }

  function insertAtCaret(text, cursorBack = 0) {
    if (!boot.capabilities.edit) {
      toast('This room link is read-only.', 'error');
      return;
    }
    text = String(text || '').replace(/\\n/g, '\n');
    const start = editor.selectionStart;
    const end = editor.selectionEnd;
    editor.setRangeText(text, start, end, 'end');
    const next = Math.max(start, editor.selectionStart - Number(cursorBack || 0));
    editor.setSelectionRange(next, next);
    editor.dispatchEvent(new Event('input', {bubbles: true}));
    editor.focus();
  }

  editor.addEventListener('compositionstart', () => { state.composing = true; });
  editor.addEventListener('compositionend', () => {
    state.composing = false;
    createLocalOpFromEditor();
    sendCursor();
  });
  editor.addEventListener('input', () => {
    if (!state.composing) createLocalOpFromEditor();
    updateLineNumbers();
    sendCursor();
  });
  editor.addEventListener('scroll', () => {
    lineNumbers.scrollTop = editor.scrollTop;
    renderRemoteCarets();
  });
  editor.addEventListener('keydown', event => {
    if (event.key === 'Tab' && boot.capabilities.edit) {
      event.preventDefault();
      insertAtCaret('    ', 0);
    }
    if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === 's') {
      event.preventDefault();
      saveDraft();
      toast(state.connected ? 'Shared source is synchronized.' : 'Draft saved locally until reconnect.');
    }
  });
  ['keyup', 'click', 'select'].forEach(type => editor.addEventListener(type, sendCursor));
  document.querySelectorAll('#codeAccessory [data-insert]').forEach(button => {
    button.addEventListener('click', () => insertAtCaret(button.dataset.insert || '', button.dataset.cursorBack || 0));
  });

  // ---------- Cursors ----------
  function caretLocation() {
    const index = editor.selectionStart || 0;
    const before = editor.value.slice(0, index);
    const lastNl = before.lastIndexOf('\n');
    const line = before.split('\n').length - 1;
    const raw = before.slice(lastNl + 1);
    let visual = 0;
    for (const ch of raw) {
      if (ch === '\t') visual += 4 - (visual % 4);
      else visual += 1;
    }
    return {line, visual_col: visual, selection: editor.selectionStart !== editor.selectionEnd};
  }

  let cursorTimer = 0;
  function sendCursor() {
    if (!state.connected || !state.helloReceived) return;
    clearTimeout(cursorTimer);
    cursorTimer = setTimeout(() => {
      const loc = caretLocation();
      send({type: 'cursor', ...loc});
    }, 25);
  }

  function editorMetrics() {
    const style = getComputedStyle(editor);
    const canvas = document.createElement('canvas');
    const ctx = canvas.getContext('2d');
    ctx.font = `${style.fontWeight} ${style.fontSize} ${style.fontFamily}`;
    const charWidth = ctx.measureText('M').width || 7.8;
    const fontSize = parseFloat(style.fontSize) || 13;
    const lineHeight = style.lineHeight === 'normal' ? fontSize * 1.62 : (parseFloat(style.lineHeight) || fontSize * 1.62);
    return {
      charWidth,
      lineHeight,
      padLeft: parseFloat(style.paddingLeft) || 0,
      padTop: parseFloat(style.paddingTop) || 0,
    };
  }

  function renderRemoteCarets() {
    caretLayer.innerHTML = '';
    const metrics = editorMetrics();
    for (const [pid, caret] of state.remoteCarets.entries()) {
      if (pid === boot.participantId) continue;
      const participant = state.participants.get(pid);
      if (!participant) continue;
      const x = metrics.padLeft + caret.visual_col * metrics.charWidth - editor.scrollLeft;
      const y = metrics.padTop + caret.line * metrics.lineHeight - editor.scrollTop;
      if (x < -4 || y < -metrics.lineHeight || x > editor.clientWidth || y > editor.clientHeight) continue;
      const el = document.createElement('div');
      el.className = 'remote-caret';
      el.style.setProperty('--caret-color', participant.color);
      el.style.left = `${x}px`;
      el.style.top = `${y}px`;
      el.style.height = `${metrics.lineHeight}px`;
      const label = document.createElement('span');
      label.className = 'remote-caret-label';
      label.textContent = participant.name;
      el.appendChild(label);
      caretLayer.appendChild(el);
    }
  }

  // ---------- Presence & pointers ----------
  function initials(name) {
    return String(name || '?').split(/\s+/).filter(Boolean).slice(0, 2).map(x => x[0]).join('').toUpperCase();
  }

  function renderParticipants() {
    const list = [...state.participants.values()];
    participantList.innerHTML = '';
    if (!list.length) {
      participantList.innerHTML = '<div class="participant-skeleton">Waiting for presence…</div>';
    } else {
      list.forEach(p => {
        const row = document.createElement('div');
        row.className = 'participant-row';
        row.style.setProperty('--participant', p.color);
        const avatar = document.createElement('span');
        avatar.className = 'participant-avatar';
        avatar.textContent = initials(p.name);
        const copy = document.createElement('div');
        copy.className = 'participant-copy';
        const name = document.createElement('strong');
        name.textContent = p.name + (p.id === boot.participantId ? ' (you)' : '');
        const meta = document.createElement('small');
        meta.textContent = `${p.role}${p.is_host ? ' · host' : ''}`;
        copy.append(name, meta);
        const count = state.securityCounts.get(p.id) || 0;
        const security = document.createElement('span');
        security.className = 'participant-security';
        security.textContent = count ? `⚑ ${count}` : '';
        row.append(avatar, copy, security);
        participantList.appendChild(row);
      });
    }
    peopleCount.textContent = list.length;
    mobilePeopleCount.textContent = list.length;
    renderRemoteCarets();
  }

  app.addEventListener('pointermove', event => {
    const now = performance.now();
    if (now - state.lastPointerSent < 60 || !state.connected) return;
    state.lastPointerSent = now;
    const x = Math.max(0, Math.min(1, event.clientX / Math.max(1, window.innerWidth)));
    const y = Math.max(0, Math.min(1, event.clientY / Math.max(1, window.innerHeight)));
    send({type: 'pointer', x, y});
  }, {passive: true});

  function showRemotePointer(pid, x, y) {
    const participant = state.participants.get(pid);
    if (!participant) return;
    let el = pointerLayer.querySelector(`[data-pointer-id="${CSS.escape(pid)}"]`);
    if (!el) {
      el = document.createElement('div');
      el.className = 'remote-pointer';
      el.dataset.pointerId = pid;
      el.style.setProperty('--pointer-color', participant.color);
      const label = document.createElement('span');
      label.textContent = participant.name;
      el.appendChild(label);
      pointerLayer.appendChild(el);
    }
    el.style.left = `${x * window.innerWidth}px`;
    el.style.top = `${y * window.innerHeight}px`;
    el.style.opacity = '1';
    clearTimeout(state.pointerTimers.get(pid));
    state.pointerTimers.set(pid, setTimeout(() => { if (el) el.style.opacity = '0'; }, 1800));
  }

  // ---------- Chat ----------
  function renderChatMessage(message) {
    if (!message || typeof message.body !== 'string') return;
    if (chatMessages.querySelector(`[data-chat-id="${message.id}"]`)) return;
    const wrap = document.createElement('div');
    wrap.className = 'chat-message';
    wrap.dataset.chatId = message.id || `temp-${Math.random()}`;
    wrap.style.setProperty('--chat-color', message.color || '#5FBB7A');
    const avatar = document.createElement('span');
    avatar.className = 'chat-avatar';
    avatar.textContent = initials(message.name);
    const bubble = document.createElement('div');
    bubble.className = 'chat-bubble';
    const meta = document.createElement('div');
    meta.className = 'chat-meta';
    const name = document.createElement('strong');
    name.textContent = message.name || 'Coder';
    const time = document.createElement('time');
    try {
      const dt = message.created_at ? new Date(message.created_at) : new Date();
      time.textContent = dt.toLocaleTimeString([], {hour: '2-digit', minute: '2-digit'});
    } catch (_) { time.textContent = ''; }
    const body = document.createElement('p');
    body.textContent = message.body;
    meta.append(name, time);
    bubble.append(meta, body);
    wrap.append(avatar, bubble);
    const empty = chatMessages.querySelector('.chat-empty');
    if (empty) empty.remove();
    chatMessages.appendChild(wrap);
    chatMessages.scrollTop = chatMessages.scrollHeight;
  }

  function showEmptyChat() {
    if (!chatMessages.children.length) {
      const empty = document.createElement('div');
      empty.className = 'chat-empty';
      empty.textContent = 'No messages yet. Use chat for quick coordination while you code.';
      chatMessages.appendChild(empty);
    }
  }

  chatForm.addEventListener('submit', event => {
    event.preventDefault();
    if (!boot.capabilities.comment) return;
    const body = chatInput.value.trim();
    if (!body) return;
    send({type: 'chat', body});
    chatInput.value = '';
    chatInput.focus();
  });
  chatInput.addEventListener('keydown', event => {
    if (event.key === 'Enter' && !event.shiftKey) {
      event.preventDefault();
      chatForm.requestSubmit();
    }
  });

  // ---------- Shared compiler ----------
  function renderRunResult(result) {
    if (!result || typeof result !== 'object' || !Object.keys(result).length) return;
    runStatus.textContent = result.by ? `${result.status || 'done'} · ${result.by}` : (result.status || 'Done');
    const chunks = [];
    if (result.stdout) chunks.push(result.stdout);
    if (result.stderr) chunks.push(result.stderr);
    if (!chunks.length) chunks.push(result.ok ? '[program finished with no output]' : '[no output]');
    consoleOutput.textContent = chunks.join(result.stdout && result.stderr ? '\n' : '');
    consoleOutput.classList.toggle('error', !result.ok);
  }

  async function runCode() {
    if (!boot.capabilities.run) {
      toast('This access link cannot run code.', 'error');
      return;
    }
    runButton.disabled = true;
    if (mobileRunButton) mobileRunButton.disabled = true;
    runStatus.textContent = 'Compiling…';
    consoleOutput.classList.remove('error');
    consoleOutput.textContent = 'Compiling C++17…';
    try {
      const response = await fetch(`/api/rooms/${encodeURIComponent(boot.roomCode)}/run`, {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({stdin: stdinInput.value, source: boot.capabilities.edit ? editor.value : undefined}),
      });
      const result = await response.json();
      if (!response.ok && !result.status) throw new Error(result.message || 'Run failed');
      renderRunResult({...result, by: boot.participantName});
    } catch (error) {
      runStatus.textContent = 'Unavailable';
      consoleOutput.classList.add('error');
      consoleOutput.textContent = state.connected
        ? `Could not run the program: ${error.message || error}`
        : 'Caudex is offline. Your source will continue syncing when the room reconnects, but compilation requires the server.';
    } finally {
      runButton.disabled = !boot.capabilities.run;
      if (mobileRunButton) mobileRunButton.disabled = !boot.capabilities.run;
    }
  }
  runButton.addEventListener('click', runCode);
  if (mobileRunButton) mobileRunButton.addEventListener('click', runCode);

  // ---------- Import / export ----------
  async function importCpp(file) {
    if (!file) return;
    if (!boot.capabilities.edit) {
      toast('Only an Edit link can replace the shared source.', 'error');
      return;
    }
    if (file.size > 100000) {
      toast('Choose a source file under 100 KB for this prototype.', 'error');
      return;
    }
    editor.value = await file.text();
    editor.dispatchEvent(new Event('input', {bubbles: true}));
    toast(`${file.name} imported into the shared editor.`);
  }
  importFile.addEventListener('change', async () => {
    await importCpp(importFile.files && importFile.files[0]);
    importFile.value = '';
  });
  if (mobileImportButton) mobileImportButton.addEventListener('click', () => importFile.click());

  function exportCpp() {
    const blob = new Blob([editor.value], {type: 'text/x-c++src;charset=utf-8'});
    const a = document.createElement('a');
    a.href = URL.createObjectURL(blob);
    a.download = `caudex-${boot.roomCode.toLowerCase()}-main.cpp`;
    a.click();
    setTimeout(() => URL.revokeObjectURL(a.href), 500);
  }
  exportButton.addEventListener('click', exportCpp);
  if (mobileExportButton) mobileExportButton.addEventListener('click', exportCpp);
  copyCodeButton.addEventListener('click', async () => {
    try {
      await navigator.clipboard.writeText(editor.value);
      toast('Source copied to clipboard.');
    } catch (_) {
      editor.select();
      document.execCommand('copy');
      toast('Source copied to clipboard.');
    }
  });

  // ---------- Whiteboard ----------
  const board = {
    ctx: jamCanvas.getContext('2d'),
    tool: 'pen',
    drawing: false,
    current: null,
    dpr: 1,
  };

  function canvasCssSize() {
    const rect = jamCanvas.getBoundingClientRect();
    return {w: Math.max(1, rect.width), h: Math.max(1, rect.height)};
  }

  function resizeCanvas() {
    const {w, h} = canvasCssSize();
    const dpr = Math.min(2, window.devicePixelRatio || 1);
    board.dpr = dpr;
    const width = Math.round(w * dpr);
    const height = Math.round(h * dpr);
    if (jamCanvas.width !== width || jamCanvas.height !== height) {
      jamCanvas.width = width;
      jamCanvas.height = height;
      board.ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
      drawBoard();
    }
  }

  function strokeStyle(stroke) {
    if (stroke.tool === 'eraser') return {color: '#000000', alpha: 1, composite: 'destination-out', width: Math.max(8, stroke.width * 2)};
    if (stroke.tool === 'highlighter') return {color: stroke.color, alpha: .28, composite: 'source-over', width: Math.max(6, stroke.width * 2.4)};
    return {color: stroke.color, alpha: 1, composite: 'source-over', width: stroke.width};
  }

  function drawStroke(stroke) {
    if (!stroke || !Array.isArray(stroke.points) || !stroke.points.length) return;
    const {w, h} = canvasCssSize();
    const style = strokeStyle(stroke);
    const ctx = board.ctx;
    ctx.save();
    ctx.globalCompositeOperation = style.composite;
    ctx.globalAlpha = style.alpha;
    ctx.strokeStyle = style.color;
    ctx.fillStyle = style.color;
    ctx.lineWidth = style.width;
    ctx.lineCap = 'round';
    ctx.lineJoin = 'round';
    const pts = stroke.points;
    if (pts.length === 1) {
      ctx.beginPath();
      ctx.arc(pts[0][0] * w, pts[0][1] * h, style.width / 2, 0, Math.PI * 2);
      ctx.fill();
    } else {
      ctx.beginPath();
      ctx.moveTo(pts[0][0] * w, pts[0][1] * h);
      for (let i = 1; i < pts.length; i++) ctx.lineTo(pts[i][0] * w, pts[i][1] * h);
      ctx.stroke();
    }
    ctx.restore();
  }

  function drawBoard() {
    const {w, h} = canvasCssSize();
    board.ctx.clearRect(0, 0, w, h);
    state.whiteboard.forEach(drawStroke);
  }

  function addStroke(stroke) {
    if (!stroke || !stroke.id || state.whiteboardIds.has(stroke.id)) return;
    state.whiteboardIds.add(stroke.id);
    state.whiteboard.push(stroke);
    drawStroke(stroke);
  }

  function pointFromEvent(event) {
    const rect = jamCanvas.getBoundingClientRect();
    return [
      Math.max(0, Math.min(1, (event.clientX - rect.left) / Math.max(1, rect.width))),
      Math.max(0, Math.min(1, (event.clientY - rect.top) / Math.max(1, rect.height))),
    ];
  }

  jamCanvas.addEventListener('pointerdown', event => {
    if (!boot.capabilities.edit) return;
    event.preventDefault();
    jamCanvas.setPointerCapture(event.pointerId);
    board.drawing = true;
    board.current = {
      id: `${boot.participantId}:stroke:${Date.now().toString(36)}:${Math.random().toString(36).slice(2, 7)}`,
      participant_id: boot.participantId,
      color: boardColor.value,
      width: Number(boardWidth.value || 3),
      tool: board.tool,
      points: [pointFromEvent(event)],
    };
    drawStroke(board.current);
  });
  jamCanvas.addEventListener('pointermove', event => {
    if (!board.drawing || !board.current) return;
    event.preventDefault();
    const point = pointFromEvent(event);
    const last = board.current.points[board.current.points.length - 1];
    const dx = point[0] - last[0], dy = point[1] - last[1];
    if (dx * dx + dy * dy < 0.000006) return;
    board.current.points.push(point);
    drawBoard();
    drawStroke(board.current);
  });
  function finishStroke(event) {
    if (!board.drawing || !board.current) return;
    event && event.preventDefault();
    const stroke = board.current;
    board.drawing = false;
    board.current = null;
    addStroke(stroke);
    send({type: 'whiteboard_stroke', stroke});
  }
  jamCanvas.addEventListener('pointerup', finishStroke);
  jamCanvas.addEventListener('pointercancel', finishStroke);

  document.querySelectorAll('[data-board-tool]').forEach(button => {
    button.addEventListener('click', () => {
      document.querySelectorAll('[data-board-tool]').forEach(b => b.classList.remove('active'));
      button.classList.add('active');
      board.tool = button.dataset.boardTool;
    });
  });
  clearBoardButton.addEventListener('click', () => {
    if (!boot.capabilities.edit) return;
    if (!confirm('Clear the shared jam board for everyone?')) return;
    state.whiteboard = [];
    state.whiteboardIds.clear();
    drawBoard();
    send({type: 'whiteboard_clear'});
  });
  const resizeObserver = new ResizeObserver(() => resizeCanvas());
  resizeObserver.observe(jamCanvas.parentElement);
  window.addEventListener('caudex-theme-changed', drawBoard);

  // ---------- Modes, drawers, share ----------
  function setMode(mode) {
    if (!['code', 'board'].includes(mode)) return;
    state.mode = mode;
    document.querySelectorAll('[data-mode]').forEach(panel => panel.classList.toggle('active', panel.dataset.mode === mode));
    document.querySelectorAll('[data-mode-target]').forEach(button => button.classList.toggle('active', button.dataset.modeTarget === mode));
    if (mode === 'board') setTimeout(resizeCanvas, 20);
  }
  document.querySelectorAll('[data-mode-target]').forEach(button => button.addEventListener('click', () => setMode(button.dataset.modeTarget)));

  function closeDrawers() {
    document.querySelectorAll('[data-drawer]').forEach(el => el.classList.remove('drawer-open'));
  }
  document.querySelectorAll('[data-open-drawer]').forEach(button => button.addEventListener('click', () => {
    const target = document.querySelector(`[data-drawer="${button.dataset.openDrawer}"]`);
    if (!target) return;
    const opening = !target.classList.contains('drawer-open');
    closeDrawers();
    if (opening) target.classList.add('drawer-open');
    if (button.dataset.openDrawer === 'chat' && mobileChatDot) mobileChatDot.classList.remove('active');
  }));
  document.querySelectorAll('[data-close-drawer]').forEach(button => button.addEventListener('click', closeDrawers));

  const shareModal = document.getElementById('shareModal');
  const shareButton = document.getElementById('shareButton');
  if (shareButton && shareModal) shareButton.addEventListener('click', () => {
    shareModal.classList.add('open'); shareModal.setAttribute('aria-hidden', 'false');
  });
  document.querySelectorAll('[data-close-modal]').forEach(el => el.addEventListener('click', () => {
    if (shareModal) { shareModal.classList.remove('open'); shareModal.setAttribute('aria-hidden', 'true'); }
  }));
  document.querySelectorAll('[data-copy-link]').forEach(button => button.addEventListener('click', async () => {
    const link = button.dataset.copyLink;
    try { await navigator.clipboard.writeText(link); button.textContent = 'Copied'; setTimeout(() => button.textContent = 'Copy', 1000); }
    catch (_) { toast('Copy failed. Select the link manually.', 'error'); }
  }));

  // ---------- Focus mode ----------
  function openFocusModal() {
    if (!focusModal) return;
    focusModal.classList.add('open'); focusModal.setAttribute('aria-hidden', 'false');
  }
  function closeFocusModal() {
    if (!focusModal) return;
    focusModal.classList.remove('open'); focusModal.setAttribute('aria-hidden', 'true');
  }
  if (focusButton) focusButton.addEventListener('click', openFocusModal);
  document.querySelectorAll('[data-close-focus]').forEach(el => el.addEventListener('click', closeFocusModal));
  if (enterFullscreenButton) enterFullscreenButton.addEventListener('click', async () => {
    state.focusEngaged = true;
    const standalone = window.matchMedia('(display-mode: standalone)').matches || window.navigator.standalone === true;
    if (standalone) {
      closeFocusModal();
      toast('Focus mode active in the installed app.');
      return;
    }
    if (document.documentElement.requestFullscreen) {
      try {
        await document.documentElement.requestFullscreen();
        closeFocusModal();
        toast('Fullscreen focus mode active.');
      } catch (_) {
        toast('Fullscreen was not allowed by this browser.', 'error');
      }
    } else {
      toast('On iPhone/iPad, add Caudex to the Home Screen for a standalone coding view.');
      closeFocusModal();
    }
  });
  if (boot.focusMode) {
    document.addEventListener('visibilitychange', () => {
      if (document.visibilityState === 'hidden') send({type: 'security_event', event_type: 'page_hidden', details: 'Caudex was no longer the visible page/app.'});
    });
    document.addEventListener('fullscreenchange', () => {
      if (state.focusEngaged && !document.fullscreenElement) send({type: 'security_event', event_type: 'fullscreen_exit', details: 'Fullscreen focus mode was exited.'});
    });
    if (!sessionStorage.getItem(`caudex-focus-seen-${boot.roomCode}`)) {
      sessionStorage.setItem(`caudex-focus-seen-${boot.roomCode}`, '1');
      setTimeout(openFocusModal, 450);
    }
  }

  // ---------- WebSocket ----------
  function send(payload) {
    if (!state.ws || state.ws.readyState !== WebSocket.OPEN || !state.helloReceived) return false;
    try { state.ws.send(JSON.stringify(payload)); return true; } catch (_) { return false; }
  }

  function connect() {
    clearTimeout(state.reconnectTimer);
    setConnection('connecting', 'Connecting');
    const scheme = location.protocol === 'https:' ? 'wss' : 'ws';
    const ws = new WebSocket(`${scheme}://${location.host}/ws/${encodeURIComponent(boot.roomCode)}`);
    state.ws = ws;
    state.helloReceived = false;

    ws.addEventListener('open', () => {
      state.connected = true;
      state.reconnectDelay = 700;
      setConnection('connecting', 'Syncing');
    });

    ws.addEventListener('message', event => {
      let message;
      try { message = JSON.parse(event.data); } catch (_) { return; }
      handleMessage(message);
    });

    ws.addEventListener('close', () => {
      state.connected = false;
      state.helloReceived = false;
      setConnection('offline', 'Offline');
      savePending();
      if (document.visibilityState !== 'hidden') {
        state.reconnectTimer = setTimeout(connect, state.reconnectDelay);
        state.reconnectDelay = Math.min(8000, state.reconnectDelay * 1.6);
      }
    });

    ws.addEventListener('error', () => {
      setConnection('offline', 'Offline');
    });
  }

  function handleMessage(message) {
    if (!message || typeof message.type !== 'string') return;
    if (message.type === 'fatal') {
      toast(message.message || 'Room connection failed.', 'error');
      setConnection('offline', 'Unavailable');
      if (state.ws) state.ws.close();
      return;
    }
    if (message.type === 'hello') {
      state.helloReceived = true;
      state.connected = true;
      state.crdt = normalizeCrdt(message.crdt);
      state.securityCounts = new Map(Object.entries(message.security_counts || {}).map(([k, v]) => [k, Number(v || 0)]));
      // Reapply any local operations that were queued while disconnected. CRDT IDs make this merge-safe.
      for (const op of state.pendingOps) applyCrdtOp(op);
      syncEditorFromCrdt(false);
      state.whiteboard = Array.isArray(message.whiteboard) ? message.whiteboard : [];
      state.whiteboardIds = new Set(state.whiteboard.map(s => s.id).filter(Boolean));
      drawBoard();
      chatMessages.innerHTML = '';
      (message.chat || []).forEach(renderChatMessage);
      showEmptyChat();
      if (message.last_run && Object.keys(message.last_run).length) renderRunResult(message.last_run);
      setConnection('online', 'Live');
      savePending();
      resendPending();
      sendCursor();
      return;
    }
    if (message.type === 'presence') {
      state.participants.clear();
      (message.participants || []).forEach(p => state.participants.set(p.id, p));
      renderParticipants();
      return;
    }
    if (message.type === 'crdt_op') {
      const anchors = selectionAnchors();
      applyCrdtOp(message);
      renderCrdt();
      if (editor.value !== state.renderedText) editor.value = state.renderedText;
      if (document.activeElement === editor) {
        const start = indexAfterAnchor(anchors.start), end = indexAfterAnchor(anchors.end);
        editor.setSelectionRange(start, end);
      }
      updateLineNumbers();
      if (window.CaudexSyntax) window.CaudexSyntax.sync(editor);
      saveDraft();
      if (message.participant_id === boot.participantId) acknowledge(message.op_id);
      renderRemoteCarets();
      return;
    }
    if (message.type === 'source_resync') {
      state.crdt = normalizeCrdt(message.crdt);
      for (const op of state.pendingOps) applyCrdtOp(op);
      syncEditorFromCrdt(true);
      resendPending();
      return;
    }
    if (message.type === 'cursor') {
      state.remoteCarets.set(message.participant_id, {line: Number(message.line || 0), visual_col: Number(message.visual_col || 0)});
      renderRemoteCarets();
      return;
    }
    if (message.type === 'pointer') {
      showRemotePointer(message.participant_id, Number(message.x || 0), Number(message.y || 0));
      return;
    }
    if (message.type === 'chat') {
      renderChatMessage(message.message);
      const chatDrawerOpen = document.querySelector('[data-drawer="chat"]')?.classList.contains('drawer-open');
      if (!chatDrawerOpen && message.message?.participant_id !== boot.participantId && mobileChatDot) mobileChatDot.classList.add('active');
      return;
    }
    if (message.type === 'run_result') {
      renderRunResult(message.result);
      return;
    }
    if (message.type === 'whiteboard_stroke') {
      addStroke(message.stroke);
      return;
    }
    if (message.type === 'whiteboard_clear') {
      state.whiteboard = [];
      state.whiteboardIds.clear();
      drawBoard();
      if (message.participant_id !== boot.participantId) toast('The shared jam board was cleared.');
      return;
    }
    if (message.type === 'security_count') {
      state.securityCounts.set(message.participant_id, Number(message.count || 0));
      renderParticipants();
    }
  }

  // ---------- Lifecycle ----------
  window.addEventListener('online', () => {
    if (!state.connected) connect();
  });
  window.addEventListener('offline', () => {
    state.connected = false;
    setConnection('offline', 'Offline');
    savePending();
  });
  document.addEventListener('visibilitychange', () => {
    if (document.visibilityState === 'visible' && (!state.ws || state.ws.readyState === WebSocket.CLOSED)) connect();
  });
  window.addEventListener('resize', renderRemoteCarets);
  setInterval(() => { if (state.connected) send({type: 'ping'}); }, 25000);

  loadPending();
  updateLineNumbers();
  showEmptyChat();
  connect();
})();
