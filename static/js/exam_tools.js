(() => {
  'use strict';
  const app = document.getElementById('examApp');
  const panel = document.getElementById('examToolsPanel');
  if (!app || !panel || app.dataset.subject !== 'CSDC101') return;

  const csrf = document.querySelector('meta[name="csrf-token"]')?.content || '';
  const toggle = document.getElementById('examToolsToggle');
  const closeBtn = document.getElementById('examToolsClose');
  const backdrop = document.getElementById('examToolsBackdrop');
  const note = document.getElementById('scratchNote');
  const saveBtn = document.getElementById('scratchSave');
  const scratchStatus = document.getElementById('scratchStatus');
  const display = document.getElementById('calculatorDisplay');
  const calcStatus = document.getElementById('calculatorStatus');
  const canvas = document.getElementById('jamCanvas');
  const ctx = canvas?.getContext('2d');
  const jamClear = document.getElementById('jamClear');
  const jamUndo = document.getElementById('jamUndo');
  const jamModeButtons = [...document.querySelectorAll('[data-jam-mode]')];

  let strokes = [];
  let drawing = false;
  let activeStroke = null;
  let mode = 'pen';
  let saveTimer = null;
  let loaded = false;

  const post = async (payload) => {
    const res = await fetch('/api/exam-tools', {
      method: 'POST',
      credentials: 'same-origin',
      headers: {'Content-Type': 'application/json', 'X-CSRFToken': csrf},
      body: JSON.stringify(payload),
    });
    if (!res.ok) throw new Error('save failed');
    return res.json();
  };

  function setOpen(open) {
    panel.classList.toggle('active', open);
    panel.setAttribute('aria-hidden', open ? 'false' : 'true');
    backdrop?.classList.toggle('active', open);
    toggle?.setAttribute('aria-expanded', open ? 'true' : 'false');
    if (open && !loaded) loadTools();
  }
  toggle?.addEventListener('click', () => setOpen(true));
  closeBtn?.addEventListener('click', () => setOpen(false));

  // ---------------- Calculator ----------------
  function tokenize(source) {
    const text = source.replace(/×/g, '*').replace(/÷/g, '/').replace(/−/g, '-').replace(/\s+/g, '');
    if (!/^[0-9+\-*/().]*$/.test(text) || text.length > 80) throw new Error('Invalid expression');
    const tokens = [];
    let i = 0;
    while (i < text.length) {
      const ch = text[i];
      if ('+-*/()'.includes(ch)) { tokens.push(ch); i += 1; continue; }
      let j = i;
      while (j < text.length && /[0-9.]/.test(text[j])) j += 1;
      const raw = text.slice(i, j);
      if (!raw || (raw.match(/\./g) || []).length > 1) throw new Error('Invalid number');
      const value = Number(raw);
      if (!Number.isFinite(value)) throw new Error('Invalid number');
      tokens.push(value); i = j;
    }
    return tokens;
  }

  function evaluateExpression(source) {
    const tokens = tokenize(source);
    let pos = 0;
    function primary() {
      if (tokens[pos] === '+') { pos += 1; return primary(); }
      if (tokens[pos] === '-') { pos += 1; return -primary(); }
      if (tokens[pos] === '(') {
        pos += 1; const v = expression();
        if (tokens[pos] !== ')') throw new Error('Missing )');
        pos += 1; return v;
      }
      const value = tokens[pos];
      if (typeof value !== 'number') throw new Error('Expected number');
      pos += 1; return value;
    }
    function term() {
      let value = primary();
      while (tokens[pos] === '*' || tokens[pos] === '/') {
        const op = tokens[pos++]; const rhs = primary();
        if (op === '/' && rhs === 0) throw new Error('Division by zero');
        value = op === '*' ? value * rhs : value / rhs;
      }
      return value;
    }
    function expression() {
      let value = term();
      while (tokens[pos] === '+' || tokens[pos] === '-') {
        const op = tokens[pos++]; const rhs = term();
        value = op === '+' ? value + rhs : value - rhs;
      }
      return value;
    }
    const result = expression();
    if (pos !== tokens.length || !Number.isFinite(result)) throw new Error('Invalid expression');
    return Number(result.toPrecision(12)).toString();
  }

  document.querySelectorAll('[data-calc]').forEach((btn) => {
    btn.addEventListener('click', () => {
      const key = btn.dataset.calc;
      calcStatus.textContent = '';
      if (key === 'clear') { display.value = ''; return; }
      if (key === 'back') { display.value = display.value.slice(0, -1); return; }
      if (key === '=') {
        try { display.value = evaluateExpression(display.value || '0'); }
        catch (err) { calcStatus.textContent = err.message || 'Invalid expression'; }
        return;
      }
      if (display.value.length < 80) display.value += key;
      display.focus();
    });
  });
  display?.addEventListener('input', () => {
    display.value = display.value.replace(/[^0-9+\-*/().]/g, '').slice(0, 80);
  });
  display?.addEventListener('keydown', (e) => {
    if (e.key === 'Enter') {
      e.preventDefault();
      try { display.value = evaluateExpression(display.value || '0'); calcStatus.textContent = ''; }
      catch (err) { calcStatus.textContent = err.message || 'Invalid expression'; }
    }
  });

  // ---------------- Persistent notes + board ----------------
  async function loadTools() {
    loaded = true;
    try {
      const res = await fetch('/api/exam-tools', {credentials: 'same-origin', cache: 'no-store'});
      if (!res.ok) throw new Error('load failed');
      const data = await res.json();
      note.value = data.note || '';
      strokes = Array.isArray(data.board) ? data.board : [];
      redraw();
      scratchStatus.textContent = 'Saved with this attempt';
    } catch (_) {
      scratchStatus.textContent = 'Could not load saved working paper';
    }
  }

  async function saveTools(message = 'Saved') {
    if (!note) return;
    scratchStatus.textContent = 'Saving…';
    try {
      await post({note: note.value, board: strokes});
      scratchStatus.textContent = message;
    } catch (_) {
      scratchStatus.textContent = 'Save failed — try again';
    }
  }
  function scheduleSave() {
    clearTimeout(saveTimer);
    saveTimer = setTimeout(() => saveTools(), 900);
  }
  note?.addEventListener('input', scheduleSave);
  saveBtn?.addEventListener('click', () => saveTools('Notes saved'));

  function pointFromEvent(e) {
    const rect = canvas.getBoundingClientRect();
    return [
      Math.max(0, Math.min(1, (e.clientX - rect.left) / rect.width)),
      Math.max(0, Math.min(1, (e.clientY - rect.top) / rect.height)),
    ];
  }
  function drawStroke(stroke) {
    if (!ctx || !stroke?.points?.length) return;
    ctx.save();
    ctx.lineCap = 'round';
    ctx.lineJoin = 'round';
    ctx.lineWidth = stroke.mode === 'eraser' ? 22 : 3;
    ctx.globalCompositeOperation = stroke.mode === 'eraser' ? 'destination-out' : 'source-over';
    ctx.strokeStyle = '#17202a';
    ctx.beginPath();
    stroke.points.forEach((p, idx) => {
      const x = p[0] * canvas.width, y = p[1] * canvas.height;
      if (idx === 0) ctx.moveTo(x, y); else ctx.lineTo(x, y);
    });
    if (stroke.points.length === 1) {
      const [x, y] = stroke.points[0];
      ctx.lineTo(x * canvas.width + .01, y * canvas.height + .01);
    }
    ctx.stroke();
    ctx.restore();
  }
  function redraw() {
    if (!ctx) return;
    ctx.clearRect(0, 0, canvas.width, canvas.height);
    strokes.forEach(drawStroke);
  }
  function beginDraw(e) {
    if (!canvas) return;
    drawing = true;
    canvas.setPointerCapture?.(e.pointerId);
    activeStroke = {mode, points: [pointFromEvent(e)]};
    strokes.push(activeStroke);
    drawStroke(activeStroke);
  }
  function moveDraw(e) {
    if (!drawing || !activeStroke) return;
    activeStroke.points.push(pointFromEvent(e));
    redraw();
  }
  function endDraw(e) {
    if (!drawing) return;
    drawing = false;
    activeStroke = null;
    canvas.releasePointerCapture?.(e.pointerId);
    scheduleSave();
  }
  canvas?.addEventListener('pointerdown', beginDraw);
  canvas?.addEventListener('pointermove', moveDraw);
  canvas?.addEventListener('pointerup', endDraw);
  canvas?.addEventListener('pointercancel', endDraw);
  canvas?.addEventListener('contextmenu', (e) => e.preventDefault());

  jamModeButtons.forEach((btn) => btn.addEventListener('click', () => {
    mode = btn.dataset.jamMode;
    jamModeButtons.forEach((b) => b.classList.toggle('active', b === btn));
  }));
  jamUndo?.addEventListener('click', () => { strokes.pop(); redraw(); scheduleSave(); });
  jamClear?.addEventListener('click', () => {
    strokes = []; redraw(); scheduleSave();
  });

  window.addEventListener('beforeunload', () => {
    if (!loaded) return;
    const payload = JSON.stringify({note: note.value, board: strokes});
    // fetch keepalive is more broadly useful here than sendBeacon because the
    // endpoint requires the normal CSRF header.
    fetch('/api/exam-tools', {
      method: 'POST', credentials: 'same-origin', keepalive: true,
      headers: {'Content-Type': 'application/json', 'X-CSRFToken': csrf},
      body: payload,
    }).catch(() => {});
  });
})();
