(() => {
  const runtime = document.getElementById('labPythonRuntime');
  if (!runtime) return;

  const startBtn = document.getElementById('labPythonStart');
  const resetBtn = document.getElementById('labPythonReset');
  const statusEl = document.getElementById('labPythonStatus');
  const dotEl = document.getElementById('labPythonDot');
  const progressEl = document.getElementById('labPythonProgress');
  const cells = [...document.querySelectorAll('.lab-python-cell')];
  const setupCells = cells.filter((cell) => cell.dataset.setup === '1');
  const indexURL = runtime.dataset.pyodideIndex || 'https://cdn.jsdelivr.net/pyodide/v314.0.7/full/';
  const pyodideScript = `${indexURL}pyodide.js`;
  const csrf = document.querySelector('meta[name="csrf-token"]')?.content || '';
  const manifestEl = document.getElementById('labAssetManifest');
  let assets = [];
  try { assets = JSON.parse(manifestEl?.textContent || '[]'); } catch (_) { assets = []; }

  let pyodide = null;
  let execProxy = null;
  let resetProxy = null;
  let runtimePromise = null;
  let workbenchSaveTimer = null;
  let workbenchLoaded = false;
  let workbenchLoadPromise = null;
  const cmByCell = new Map();

  const PYTHON_WORDS = [
    'and','as','assert','async','await','break','class','continue','def','del','elif','else','except','False',
    'finally','for','from','global','if','import','in','is','lambda','None','nonlocal','not','or','pass','raise',
    'return','True','try','while','with','yield','print','len','range','enumerate','zip','min','max','sum','round',
    'list','dict','set','tuple','int','float','str','bool','np','pd','plt','Image','cv2','skimage','scipy'
  ];

  function allCompletionWords() {
    const words = new Set(PYTHON_WORDS);
    cells.forEach((cell) => {
      const text = editorValue(cell);
      (text.match(/[A-Za-z_][A-Za-z0-9_]*/g) || []).forEach((word) => words.add(word));
    });
    return [...words].sort();
  }

  function pythonHint(cm) {
    const cur = cm.getCursor();
    const token = cm.getTokenAt(cur);
    const raw = token.string || '';
    const match = raw.match(/[A-Za-z_][A-Za-z0-9_]*$/);
    const prefix = match ? match[0] : '';
    const from = window.CodeMirror.Pos(cur.line, cur.ch - prefix.length);
    const list = allCompletionWords().filter((word) => !prefix || word.toLowerCase().startsWith(prefix.toLowerCase()));
    return {list: list.slice(0, 80), from, to: cur};
  }

  function initCodeEditors() {
    if (!window.CodeMirror) return;
    cells.forEach((cell) => {
      const textarea = cell.querySelector('.lab-python-editor');
      if (!textarea || cmByCell.has(cell)) return;
      const cm = window.CodeMirror.fromTextArea(textarea, {
        mode: {name: 'python', version: 3},
        lineNumbers: true,
        indentUnit: 4,
        tabSize: 4,
        indentWithTabs: false,
        lineWrapping: false,
        viewportMargin: 20,
        extraKeys: {
          'Ctrl-Space': (editor) => window.CodeMirror.showHint(editor, pythonHint, {completeSingle: false}),
          'Cmd-Space': (editor) => window.CodeMirror.showHint(editor, pythonHint, {completeSingle: false}),
          'Tab': (editor) => editor.execCommand('indentMore'),
          'Shift-Tab': (editor) => editor.execCommand('indentLess'),
        },
      });
      cm.setSize('100%', 'auto');
      cm.on('change', (_editor, change) => {
        scheduleWorkbenchSave();
        if (change.origin === '+input') {
          const cur = cm.getCursor();
          const tok = cm.getTokenAt(cur).string || '';
          if (/[A-Za-z_][A-Za-z0-9_]{1,}$/.test(tok)) {
            clearTimeout(cm._custosHintTimer);
            cm._custosHintTimer = setTimeout(() => {
              if (!cm.state.completionActive) window.CodeMirror.showHint(cm, pythonHint, {completeSingle: false});
            }, 180);
          }
        }
      });
      cm.on('blur', () => saveWorkbenchState());
      cmByCell.set(cell, cm);
    });
  }

  function editorValue(cell) {
    const cm = cmByCell.get(cell);
    if (cm) return cm.getValue();
    return cell.querySelector('.lab-python-editor')?.value || '';
  }

  function setEditorValue(cell, value) {
    const cm = cmByCell.get(cell);
    if (cm) cm.setValue(String(value ?? ''));
    else {
      const textarea = cell.querySelector('.lab-python-editor');
      if (textarea) textarea.value = String(value ?? '');
    }
  }

  const collectCellState = () => {
    const out = {};
    cells.forEach((cell) => {
      const id = cell.dataset.pythonCell;
      if (id) out[id] = editorValue(cell);
    });
    return out;
  };

  async function saveWorkbenchState({keepalive = false} = {}) {
    if (!workbenchLoaded) return;
    try {
      await fetch('/api/lab-workbench', {
        method: 'POST', credentials: 'same-origin', keepalive,
        headers: {'Content-Type': 'application/json', 'X-CSRFToken': csrf},
        body: JSON.stringify({cells: collectCellState()}),
      });
    } catch (_) { /* Saved again on the next edit. */ }
  }

  function scheduleWorkbenchSave() {
    clearTimeout(workbenchSaveTimer);
    workbenchSaveTimer = setTimeout(() => saveWorkbenchState(), 700);
  }

  async function loadWorkbenchState() {
    try {
      const response = await fetch('/api/lab-workbench', {credentials: 'same-origin', cache: 'no-store'});
      const data = await response.json();
      if (response.ok && data.ok && data.cells && typeof data.cells === 'object') {
        cells.forEach((cell) => {
          const id = cell.dataset.pythonCell;
          if (id && Object.prototype.hasOwnProperty.call(data.cells, id)) setEditorValue(cell, data.cells[id]);
        });
      }
    } catch (_) { /* Editing still works if state retrieval fails. */ }
    workbenchLoaded = true;
  }

  const setState = (state, text) => {
    runtime.dataset.runtimeState = state;
    if (statusEl) statusEl.textContent = text;
    if (dotEl) dotEl.dataset.state = state;
    if (progressEl) progressEl.classList.toggle('hidden', state !== 'loading');
  };

  function loadScriptOnce(src) {
    if (window.loadPyodide) return Promise.resolve();
    const existing = document.querySelector(`script[data-pyodide-loader="${src}"]`);
    if (existing) return new Promise((resolve, reject) => {
      existing.addEventListener('load', resolve, {once: true});
      existing.addEventListener('error', () => reject(new Error('Could not load the Pyodide runtime.')), {once: true});
    });
    return new Promise((resolve, reject) => {
      const script = document.createElement('script');
      script.src = src; script.async = true; script.dataset.pyodideLoader = src;
      script.addEventListener('load', resolve, {once: true});
      script.addEventListener('error', () => reject(new Error('Could not load the Pyodide runtime. Check your internet connection.')), {once: true});
      document.head.appendChild(script);
    });
  }

  async function hydrateAssets() {
    if (!assets.length) return;
    setState('loading', `Loading ${assets.length} notebook file${assets.length === 1 ? '' : 's'} into the browser workspace…`);
    await Promise.all(assets.map(async (asset) => {
      const path = String(asset.path || '').replace(/^\/+/, '');
      if (!path || path.split('/').includes('..')) return;
      const response = await fetch(asset.url, {credentials: 'same-origin'});
      if (!response.ok) throw new Error(`Could not load ${path}.`);
      const bytes = new Uint8Array(await response.arrayBuffer());
      const slash = path.lastIndexOf('/');
      if (slash > 0) pyodide.FS.mkdirTree(path.slice(0, slash));
      pyodide.FS.writeFile(path, bytes);
    }));
  }

  async function installRunner() {
    await pyodide.runPythonAsync(`
import os as _custos_os
_custos_os.environ["MPLBACKEND"] = "Agg"
import io as _custos_io
import json as _custos_json
import base64 as _custos_base64
import traceback as _custos_traceback
import contextlib as _custos_contextlib
from pyodide.code import eval_code_async as _custos_eval_code_async
_CUSTOS_NS = {"__builtins__": __builtins__, "__name__": "__main__"}
def _custos_display(value):
    if hasattr(value, "to_string"): print(value.to_string())
    else: print(value)
_CUSTOS_NS["display"] = _custos_display
def _custos_format_result(value):
    if value is None: return ""
    try:
        if hasattr(value, "to_string"): return value.to_string()
    except Exception: pass
    try: return repr(value)
    except Exception: return str(value)
def _custos_collect_plots():
    plots = []
    try:
        import matplotlib.pyplot as _custos_plt
        for number in list(_custos_plt.get_fignums()):
            fig = _custos_plt.figure(number)
            buf = _custos_io.BytesIO()
            fig.savefig(buf, format="png", dpi=110, bbox_inches="tight")
            plots.append(_custos_base64.b64encode(buf.getvalue()).decode("ascii"))
        _custos_plt.close("all")
    except Exception: pass
    return plots
async def _custos_exec(source):
    stdout = _custos_io.StringIO(); stderr = _custos_io.StringIO()
    try:
        with _custos_contextlib.redirect_stdout(stdout), _custos_contextlib.redirect_stderr(stderr):
            result = await _custos_eval_code_async(source, _CUSTOS_NS, _CUSTOS_NS)
        payload = {"ok": True, "stdout": stdout.getvalue(), "stderr": stderr.getvalue(), "result": _custos_format_result(result), "plots": _custos_collect_plots()}
    except Exception:
        payload = {"ok": False, "stdout": stdout.getvalue(), "stderr": stderr.getvalue(), "result": "", "plots": _custos_collect_plots(), "error": _custos_traceback.format_exc()}
    return _custos_json.dumps(payload)
def _custos_reset():
    try:
        import matplotlib.pyplot as _custos_plt
        _custos_plt.close("all")
    except Exception: pass
    _CUSTOS_NS.clear(); _CUSTOS_NS.update({"__builtins__": __builtins__, "__name__": "__main__", "display": _custos_display})
    return True
`);
    execProxy?.destroy?.(); resetProxy?.destroy?.();
    execProxy = pyodide.globals.get('_custos_exec');
    resetProxy = pyodide.globals.get('_custos_reset');
  }

  async function runCell(cell, {quiet = false, skipEnsure = false} = {}) {
    if (!cell) return null;
    await saveWorkbenchState();
    if (!skipEnsure) await ensureRuntime();
    const runBtn = cell.querySelector('[data-python-run]');
    const wrap = cell.querySelector('[data-python-output-wrap]');
    const output = cell.querySelector('[data-python-output]');
    const plots = cell.querySelector('[data-python-plots]');
    if (!execProxy) return null;
    const oldLabel = runBtn?.textContent;
    if (runBtn) { runBtn.disabled = true; runBtn.textContent = 'Running…'; }
    cell.classList.add('running');
    try {
      const resultJson = await execProxy(editorValue(cell));
      const result = JSON.parse(String(resultJson));
      wrap?.classList.remove('hidden');
      if (output) {
        const pieces = [];
        if (result.stdout?.trim()) pieces.push(result.stdout.trimEnd());
        if (result.stderr?.trim()) pieces.push(result.stderr.trimEnd());
        if (result.result?.trim()) pieces.push(result.result.trimEnd());
        if (!result.ok && result.error) pieces.push(result.error.trimEnd());
        output.textContent = pieces.join('\n\n') || (result.ok ? 'Cell completed with no text output.' : 'Cell failed.');
        output.classList.toggle('error', !result.ok);
      }
      if (plots) {
        plots.replaceChildren();
        (result.plots || []).forEach((encoded, index) => {
          const figure = document.createElement('figure');
          const img = document.createElement('img');
          img.src = `data:image/png;base64,${encoded}`; img.alt = `Python output figure ${index + 1}`;
          figure.appendChild(img); plots.appendChild(figure);
        });
      }
      cell.classList.toggle('cell-error', !result.ok); cell.classList.toggle('cell-success', result.ok);
      if (!quiet) setState('ready', result.ok ? 'Python ready · cell executed.' : 'Python ready · cell returned an error.');
      return result;
    } finally {
      cell.classList.remove('running');
      if (runBtn) { runBtn.disabled = false; runBtn.textContent = oldLabel || 'Run Cell'; }
    }
  }

  async function initializeRuntime() {
    if (workbenchLoadPromise) await workbenchLoadPromise;
    startBtn.disabled = true;
    setState('loading', 'Loading Python WebAssembly runtime…');
    await loadScriptOnce(pyodideScript);
    setState('loading', 'Starting Python in your browser…');
    pyodide = await window.loadPyodide({indexURL});

    const importSource = cells.map(editorValue).join('\n\n');
    setState('loading', 'Loading packages used by this notebook…');
    if (typeof pyodide.loadPackagesFromImports === 'function' && importSource.trim()) {
      await pyodide.loadPackagesFromImports(importSource);
    }
    await hydrateAssets();
    setState('loading', 'Preparing the workbench…');
    await installRunner();
    for (const setupCell of setupCells) {
      const result = await runCell(setupCell, {quiet: true, skipEnsure: true});
      if (result && !result.ok) throw new Error('A notebook setup cell could not initialize. Open its output for details.');
    }
    resetBtn.disabled = false; startBtn.textContent = 'Python Ready';
    setState('ready', 'Python ready · notebook state and supporting files are available in this tab.');
    return pyodide;
  }

  function ensureRuntime() {
    if (pyodide && execProxy) return Promise.resolve(pyodide);
    if (!runtimePromise) {
      runtimePromise = initializeRuntime().catch((error) => {
        console.error('Custos Pyodide runtime failed', error);
        setState('error', `Python failed to load: ${error.message || error}`);
        startBtn.disabled = false; startBtn.textContent = 'Retry Python'; runtimePromise = null;
        throw error;
      });
    }
    return runtimePromise;
  }

  async function resetRuntime() {
    if (!pyodide || !resetProxy) return;
    resetBtn.disabled = true; setState('loading', 'Resetting notebook variables…');
    try {
      resetProxy();
      cells.forEach((cell) => {
        cell.classList.remove('cell-success', 'cell-error');
        cell.querySelector('[data-python-output-wrap]')?.classList.add('hidden');
        const output = cell.querySelector('[data-python-output]'); if (output) output.textContent = '';
        cell.querySelector('[data-python-plots]')?.replaceChildren();
      });
      for (const setupCell of setupCells) {
        const result = await runCell(setupCell, {quiet: true, skipEnsure: true});
        if (result && !result.ok) throw new Error('A setup cell failed after reset.');
      }
      setState('ready', 'Python reset · setup cells ran again.');
    } catch (error) { setState('error', `Reset failed: ${error.message || error}`); }
    finally { resetBtn.disabled = false; }
  }

  initCodeEditors();
  workbenchLoadPromise = loadWorkbenchState();
  startBtn?.addEventListener('click', () => ensureRuntime().catch(() => {}));
  resetBtn?.addEventListener('click', () => resetRuntime());

  cells.forEach((cell) => {
    const textarea = cell.querySelector('.lab-python-editor');
    if (!cmByCell.has(cell)) {
      textarea?.addEventListener('input', scheduleWorkbenchSave);
      textarea?.addEventListener('change', () => saveWorkbenchState());
    }
    cell.querySelector('[data-python-run]')?.addEventListener('click', () => runCell(cell).catch((error) => setState('error', `Python error: ${error.message || error}`)));
    cell.querySelector('[data-python-restore]')?.addEventListener('click', () => {
      if (textarea) setEditorValue(cell, textarea.defaultValue);
      cell.classList.remove('cell-success', 'cell-error'); scheduleWorkbenchSave();
    });
    cell.querySelector('[data-python-clear]')?.addEventListener('click', () => {
      const output = cell.querySelector('[data-python-output]'); if (output) output.textContent = '';
      cell.querySelector('[data-python-plots]')?.replaceChildren();
      cell.querySelector('[data-python-output-wrap]')?.classList.add('hidden');
    });
  });

  window.addEventListener('beforeunload', () => {
    saveWorkbenchState({keepalive: true}); execProxy?.destroy?.(); resetProxy?.destroy?.();
  });
})();
