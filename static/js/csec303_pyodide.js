(() => {
  const runtime = document.getElementById('labPythonRuntime');
  if (!runtime) return;

  const startBtn = document.getElementById('labPythonStart');
  const resetBtn = document.getElementById('labPythonReset');
  const statusEl = document.getElementById('labPythonStatus');
  const dotEl = document.getElementById('labPythonDot');
  const progressEl = document.getElementById('labPythonProgress');
  const cells = [...document.querySelectorAll('.lab-python-cell')];
  const setupCell = cells.find(cell => cell.dataset.setup === '1');
  const indexURL = runtime.dataset.pyodideIndex || 'https://cdn.jsdelivr.net/pyodide/v314.0.7/full/';
  const caseBase = runtime.dataset.caseBase || '/static/labs/csec303_midterm/';
  const pyodideScript = `${indexURL}pyodide.js`;

  const evidenceFiles = [
    'case00_evidence_original.png', 'case00_evidence.tiff', 'case00_evidence.webp',
    'case00_evidence_q25.jpg', 'case00_evidence_q45.jpg', 'case00_evidence_q65.jpg', 'case00_evidence_q85.jpg',
    'case01_medical_reference.png', 'case01_medical_lowcontrast.png',
    'case02_fingerprint_clean.png', 'case02_fingerprint_saltpepper.png', 'case02_fingerprint_gaussian.png',
    'case03_phantom_reference.png', 'case03_phantom_degraded.png',
    'case04_frequency_clean.png', 'case04_frequency_noisy.png', 'case04_frequency_spectrum.png'
  ];

  let pyodide = null;
  let execProxy = null;
  let resetProxy = null;
  let runtimePromise = null;
  const csrf = document.querySelector('meta[name="csrf-token"]')?.content || '';
  let workbenchSaveTimer = null;
  let workbenchLoaded = false;
  let workbenchLoadPromise = null;

  const collectCellState = () => {
    const out = {};
    cells.forEach((cell) => {
      const id = cell.dataset.pythonCell;
      const editor = cell.querySelector('.lab-python-editor');
      if (id && editor) out[id] = editor.value;
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
    } catch (_) { /* Answer state remains authoritative; retry on the next edit. */ }
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
          const editor = cell.querySelector('.lab-python-editor');
          if (id && editor && Object.prototype.hasOwnProperty.call(data.cells, id)) editor.value = String(data.cells[id]);
        });
      }
    } catch (_) { /* Offline/local browser state can still be edited. */ }
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
    if (existing) {
      return new Promise((resolve, reject) => {
        existing.addEventListener('load', resolve, {once: true});
        existing.addEventListener('error', () => reject(new Error('Could not load the Pyodide runtime.')), {once: true});
      });
    }
    return new Promise((resolve, reject) => {
      const script = document.createElement('script');
      script.src = src;
      script.async = true;
      script.dataset.pyodideLoader = src;
      script.addEventListener('load', resolve, {once: true});
      script.addEventListener('error', () => reject(new Error('Could not load the Pyodide runtime. Check your internet connection.')), {once: true});
      document.head.appendChild(script);
    });
  }

  async function hydrateEvidenceFiles() {
    setState('loading', 'Loading PHANTOM-303 evidence into the browser workspace…');
    await Promise.all(evidenceFiles.map(async (filename) => {
      const response = await fetch(`${caseBase}${filename}`, {credentials: 'same-origin'});
      if (!response.ok) throw new Error(`Could not load ${filename}.`);
      const bytes = new Uint8Array(await response.arrayBuffer());
      pyodide.FS.writeFile(filename, bytes);
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
    if hasattr(value, "to_string"):
        print(value.to_string())
    else:
        print(value)

_CUSTOS_NS["display"] = _custos_display

def _custos_format_result(value):
    if value is None:
        return ""
    try:
        if hasattr(value, "to_string"):
            return value.to_string()
    except Exception:
        pass
    try:
        return repr(value)
    except Exception:
        return str(value)

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
    except Exception:
        pass
    return plots

async def _custos_exec(source):
    stdout = _custos_io.StringIO()
    stderr = _custos_io.StringIO()
    try:
        with _custos_contextlib.redirect_stdout(stdout), _custos_contextlib.redirect_stderr(stderr):
            result = await _custos_eval_code_async(source, _CUSTOS_NS, _CUSTOS_NS)
        payload = {
            "ok": True,
            "stdout": stdout.getvalue(),
            "stderr": stderr.getvalue(),
            "result": _custos_format_result(result),
            "plots": _custos_collect_plots(),
        }
    except Exception:
        payload = {
            "ok": False,
            "stdout": stdout.getvalue(),
            "stderr": stderr.getvalue(),
            "result": "",
            "plots": _custos_collect_plots(),
            "error": _custos_traceback.format_exc(),
        }
    return _custos_json.dumps(payload)

def _custos_reset():
    try:
        import matplotlib.pyplot as _custos_plt
        _custos_plt.close("all")
    except Exception:
        pass
    _CUSTOS_NS.clear()
    _CUSTOS_NS.update({"__builtins__": __builtins__, "__name__": "__main__", "display": _custos_display})
    return True
`);
    execProxy?.destroy?.();
    resetProxy?.destroy?.();
    execProxy = pyodide.globals.get('_custos_exec');
    resetProxy = pyodide.globals.get('_custos_reset');
  }

  async function runCell(cell, {quiet = false, skipEnsure = false} = {}) {
    if (!cell) return null;
    await saveWorkbenchState();
    if (!skipEnsure) await ensureRuntime();
    const editor = cell.querySelector('.lab-python-editor');
    const runBtn = cell.querySelector('[data-python-run]');
    const wrap = cell.querySelector('[data-python-output-wrap]');
    const output = cell.querySelector('[data-python-output]');
    const plots = cell.querySelector('[data-python-plots]');
    if (!editor || !execProxy) return null;

    const oldLabel = runBtn?.textContent;
    if (runBtn) {
      runBtn.disabled = true;
      runBtn.textContent = 'Running…';
    }
    cell.classList.add('running');
    try {
      const resultJson = await execProxy(editor.value);
      const result = JSON.parse(String(resultJson));
      if (wrap) wrap.classList.remove('hidden');
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
          img.src = `data:image/png;base64,${encoded}`;
          img.alt = `Python output figure ${index + 1}`;
          figure.appendChild(img);
          plots.appendChild(figure);
        });
      }
      cell.classList.toggle('cell-error', !result.ok);
      cell.classList.toggle('cell-success', result.ok);
      if (!quiet) {
        setState(result.ok ? 'ready' : 'ready', result.ok ? 'Python ready · cell executed.' : 'Python ready · cell returned an error.');
      }
      return result;
    } finally {
      cell.classList.remove('running');
      if (runBtn) {
        runBtn.disabled = false;
        runBtn.textContent = oldLabel || 'Run Cell';
      }
    }
  }

  async function initializeRuntime() {
    if (workbenchLoadPromise) await workbenchLoadPromise;
    startBtn.disabled = true;
    setState('loading', 'Loading Python 3.14 WebAssembly runtime…');
    await loadScriptOnce(pyodideScript);

    setState('loading', 'Starting Python in your browser…');
    pyodide = await window.loadPyodide({indexURL});

    const setupCode = setupCell?.querySelector('.lab-python-editor')?.value || '';
    setState('loading', 'Loading scientific Python packages… this first load can take a while.');
    if (typeof pyodide.loadPackagesFromImports === 'function' && setupCode) {
      await pyodide.loadPackagesFromImports(setupCode);
    } else {
      await pyodide.loadPackage(['numpy', 'pandas', 'matplotlib', 'Pillow', 'scipy', 'scikit-image']);
    }

    await hydrateEvidenceFiles();
    setState('loading', 'Preparing the notebook workspace…');
    await installRunner();

    if (setupCell) {
      const result = await runCell(setupCell, {quiet: true, skipEnsure: true});
      if (result && !result.ok) throw new Error('The PHANTOM-303 setup cell could not initialize. See its output for details.');
    }

    resetBtn.disabled = false;
    startBtn.textContent = 'Python Ready';
    setState('ready', 'Python ready · scientific packages and case evidence loaded locally in this tab.');
    return pyodide;
  }

  function ensureRuntime() {
    if (pyodide && execProxy) return Promise.resolve(pyodide);
    if (!runtimePromise) {
      runtimePromise = initializeRuntime().catch((error) => {
        console.error('CSEC303 Pyodide runtime failed', error);
        setState('error', `Python failed to load: ${error.message || error}`);
        startBtn.disabled = false;
        startBtn.textContent = 'Retry Python';
        runtimePromise = null;
        throw error;
      });
    }
    return runtimePromise;
  }

  async function resetRuntime() {
    if (!pyodide || !resetProxy) return;
    resetBtn.disabled = true;
    setState('loading', 'Resetting notebook variables…');
    try {
      resetProxy();
      cells.forEach(cell => {
        cell.classList.remove('cell-success', 'cell-error');
        const wrap = cell.querySelector('[data-python-output-wrap]');
        const output = cell.querySelector('[data-python-output]');
        const plots = cell.querySelector('[data-python-plots]');
        wrap?.classList.add('hidden');
        if (output) output.textContent = '';
        plots?.replaceChildren();
      });
      if (setupCell) {
        const result = await runCell(setupCell, {quiet: true, skipEnsure: true});
        if (result && !result.ok) throw new Error('Setup cell failed after reset.');
      }
      setState('ready', 'Python reset · case evidence remains loaded and the setup cell ran again.');
    } catch (error) {
      setState('error', `Reset failed: ${error.message || error}`);
    } finally {
      resetBtn.disabled = false;
    }
  }

  startBtn?.addEventListener('click', () => ensureRuntime().catch(() => {}));
  resetBtn?.addEventListener('click', () => resetRuntime());

  cells.forEach(cell => {
    const editor = cell.querySelector('.lab-python-editor');
    editor?.addEventListener('input', scheduleWorkbenchSave);
    editor?.addEventListener('change', () => saveWorkbenchState());
    cell.querySelector('[data-python-run]')?.addEventListener('click', () => runCell(cell).catch(error => {
      setState('error', `Python error: ${error.message || error}`);
    }));
    cell.querySelector('[data-python-restore]')?.addEventListener('click', () => {
      if (editor) editor.value = editor.defaultValue;
      cell.classList.remove('cell-success', 'cell-error');
      scheduleWorkbenchSave();
    });
    cell.querySelector('[data-python-clear]')?.addEventListener('click', () => {
      const wrap = cell.querySelector('[data-python-output-wrap]');
      const output = cell.querySelector('[data-python-output]');
      const plots = cell.querySelector('[data-python-plots]');
      if (output) output.textContent = '';
      plots?.replaceChildren();
      wrap?.classList.add('hidden');
    });
  });

  workbenchLoadPromise = loadWorkbenchState();

  window.addEventListener('beforeunload', () => {
    saveWorkbenchState({keepalive: true});
    execProxy?.destroy?.();
    resetProxy?.destroy?.();
  });
})();
