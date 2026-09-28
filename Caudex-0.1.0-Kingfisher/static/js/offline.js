(() => {
  'use strict';
  const editor = document.getElementById('offlineCode');
  if (!editor) return;

  const lineNumbers = document.getElementById('offlineLineNumbers');
  const saveState = document.getElementById('offlineSaveState');
  const importInput = document.getElementById('offlineImport');
  const exportButton = document.getElementById('offlineExport');
  const runButton = document.getElementById('offlineRun');
  const runStatus = document.getElementById('offlineRunStatus');
  const output = document.getElementById('offlineOutput');
  const stdin = document.getElementById('offlineStdin');
  const netBadge = document.getElementById('offlineNetBadge');
  const storageKey = 'caudex-offline-cpp';

  const starter = `#include <iostream>\nusing namespace std;\n\nint main() {\n    cout << "Hello, Caudex!" << endl;\n    return 0;\n}\n`;
  editor.value = localStorage.getItem(storageKey) || starter;

  function updateLines() {
    const count = Math.max(1, editor.value.split('\n').length);
    lineNumbers.textContent = Array.from({length: count}, (_, i) => i + 1).join('\n');
    lineNumbers.scrollTop = editor.scrollTop;
  }

  let saveTimer;
  editor.addEventListener('input', () => {
    updateLines();
    saveState.textContent = 'Saving…';
    clearTimeout(saveTimer);
    saveTimer = setTimeout(() => {
      localStorage.setItem(storageKey, editor.value);
      saveState.textContent = 'Saved locally';
    }, 120);
  });
  editor.addEventListener('scroll', updateLines);
  editor.addEventListener('keydown', event => {
    if (event.key === 'Tab') {
      event.preventDefault();
      insertAtCaret('    ', 0);
    }
  });

  function insertAtCaret(text, cursorBack = 0) {
    text = text.replace(/\\n/g, '\n');
    const start = editor.selectionStart;
    const end = editor.selectionEnd;
    editor.setRangeText(text, start, end, 'end');
    const next = Math.max(start, editor.selectionStart - Number(cursorBack || 0));
    editor.setSelectionRange(next, next);
    editor.dispatchEvent(new Event('input', {bubbles: true}));
    editor.focus();
  }

  document.querySelectorAll('#offlineAccessory [data-insert]').forEach(button => {
    button.addEventListener('click', () => insertAtCaret(button.dataset.insert || '', button.dataset.cursorBack || 0));
  });

  importInput.addEventListener('change', async () => {
    const file = importInput.files && importInput.files[0];
    if (!file) return;
    if (file.size > 100000) {
      alert('Please choose a source file under 100 KB for this prototype.');
      importInput.value = '';
      return;
    }
    editor.value = await file.text();
    editor.dispatchEvent(new Event('input', {bubbles: true}));
    importInput.value = '';
  });

  exportButton.addEventListener('click', () => {
    const blob = new Blob([editor.value], {type: 'text/x-c++src;charset=utf-8'});
    const a = document.createElement('a');
    a.href = URL.createObjectURL(blob);
    a.download = 'caudex-offline.cpp';
    a.click();
    setTimeout(() => URL.revokeObjectURL(a.href), 500);
  });

  async function runCode() {
    runButton.disabled = true;
    runStatus.textContent = 'Running…';
    output.classList.remove('error');
    output.textContent = 'Compiling…';
    try {
      const response = await fetch('/api/solo/run', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({source: editor.value, stdin: stdin.value})
      });
      const data = await response.json();
      runStatus.textContent = data.status || 'Done';
      const chunks = [];
      if (data.stdout) chunks.push(data.stdout);
      if (data.stderr) chunks.push(data.stderr);
      if (!chunks.length) chunks.push(data.ok ? '[program finished with no output]' : '[no output]');
      output.textContent = chunks.join(data.stdout && data.stderr ? '\n' : '');
      output.classList.toggle('error', !data.ok);
    } catch (error) {
      runStatus.textContent = 'Server unavailable';
      output.classList.add('error');
      output.textContent = 'The Caudex server is unreachable. Your code is still saved locally; export the .cpp file or run it after reconnecting.';
    } finally {
      runButton.disabled = false;
    }
  }
  runButton.addEventListener('click', runCode);

  function updateNetwork() {
    const online = navigator.onLine;
    netBadge.classList.toggle('online', online);
    netBadge.classList.toggle('offline', !online);
    netBadge.querySelector('span').textContent = online ? 'Server may be reachable' : 'Offline';
  }
  window.addEventListener('online', updateNetwork);
  window.addEventListener('offline', updateNetwork);
  updateNetwork();
  updateLines();
})();
