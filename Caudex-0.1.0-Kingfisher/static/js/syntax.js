(() => {
  'use strict';

  const KEYWORDS = new Set([
    'alignas','alignof','and','and_eq','asm','auto','bitand','bitor','break','case','catch','class','compl','concept','const','consteval','constexpr','constinit','const_cast','continue','co_await','co_return','co_yield','decltype','default','delete','do','dynamic_cast','else','enum','explicit','export','extern','for','friend','goto','if','inline','mutable','namespace','new','noexcept','not','not_eq','operator','or','or_eq','private','protected','public','register','reinterpret_cast','requires','return','sizeof','static','static_assert','static_cast','struct','switch','template','this','thread_local','throw','try','typedef','typeid','typename','union','using','virtual','volatile','while','xor','xor_eq'
  ]);
  const TYPES = new Set([
    'bool','char','char8_t','char16_t','char32_t','double','float','int','long','short','signed','unsigned','void','wchar_t','string','vector','array','map','unordered_map','set','unordered_set','pair','size_t','nullptr_t','istream','ostream'
  ]);
  const LITERALS = new Set(['true','false','nullptr','NULL']);

  const esc = value => value.replace(/[&<>]/g, ch => ({'&':'&amp;','<':'&lt;','>':'&gt;'}[ch]));
  const span = (cls, text) => `<span class="${cls}">${esc(text)}</span>`;
  const isIdentStart = ch => /[A-Za-z_]/.test(ch || '');
  const isIdent = ch => /[A-Za-z0-9_]/.test(ch || '');
  const isDigit = ch => /[0-9]/.test(ch || '');

  function highlightCpp(source) {
    let out = '';
    let i = 0;
    let lineStart = true;

    while (i < source.length) {
      const ch = source[i];
      const next = source[i + 1] || '';

      if (ch === '\n') {
        out += '\n';
        i += 1;
        lineStart = true;
        continue;
      }

      if (lineStart && (ch === ' ' || ch === '\t')) {
        out += ch;
        i += 1;
        continue;
      }

      if (lineStart && ch === '#') {
        const end = source.indexOf('\n', i);
        const stop = end === -1 ? source.length : end;
        out += span('syntax-preproc', source.slice(i, stop));
        i = stop;
        lineStart = false;
        continue;
      }
      lineStart = false;

      if (ch === '/' && next === '/') {
        const end = source.indexOf('\n', i);
        const stop = end === -1 ? source.length : end;
        out += span('syntax-comment', source.slice(i, stop));
        i = stop;
        continue;
      }

      if (ch === '/' && next === '*') {
        let j = i + 2;
        while (j < source.length && !(source[j] === '*' && source[j + 1] === '/')) j += 1;
        j = Math.min(source.length, j + 2);
        out += span('syntax-comment', source.slice(i, j));
        i = j;
        continue;
      }

      if (ch === '"' || ch === "'") {
        const quote = ch;
        let j = i + 1;
        while (j < source.length) {
          if (source[j] === '\\') { j += 2; continue; }
          if (source[j] === quote) { j += 1; break; }
          j += 1;
        }
        out += span(quote === '"' ? 'syntax-string' : 'syntax-char', source.slice(i, j));
        i = j;
        continue;
      }

      if (isDigit(ch) || (ch === '.' && isDigit(next))) {
        let j = i + 1;
        while (j < source.length && /[0-9A-Fa-fxXbB._'eEpP+\-uUlLfF]/.test(source[j])) j += 1;
        out += span('syntax-number', source.slice(i, j));
        i = j;
        continue;
      }

      if (isIdentStart(ch)) {
        let j = i + 1;
        while (j < source.length && isIdent(source[j])) j += 1;
        const word = source.slice(i, j);
        let k = j;
        while (k < source.length && /\s/.test(source[k])) k += 1;
        if (KEYWORDS.has(word)) out += span('syntax-keyword', word);
        else if (TYPES.has(word)) out += span('syntax-type', word);
        else if (LITERALS.has(word)) out += span('syntax-literal', word);
        else if (source[k] === '(') out += span('syntax-function', word);
        else if (word === 'std' || word === 'cout' || word === 'cin' || word === 'endl') out += span('syntax-builtin', word);
        else out += esc(word);
        i = j;
        continue;
      }

      if (/[:+\-*\/%=&|!<>~^?]/.test(ch)) {
        let j = i + 1;
        while (j < source.length && /[:+\-*\/%=&|!<>~^?]/.test(source[j]) && j - i < 3) j += 1;
        out += span('syntax-operator', source.slice(i, j));
        i = j;
        continue;
      }

      if (/[{}()[\],;.]/.test(ch)) {
        out += span('syntax-punctuation', ch);
        i += 1;
        continue;
      }

      out += esc(ch);
      i += 1;
    }

    return out + (source.endsWith('\n') ? ' ' : '');
  }

  function sync(editor) {
    if (!editor) return;
    const targetId = editor.dataset.syntaxTarget;
    const target = targetId ? document.getElementById(targetId) : null;
    if (!target) return;
    target.innerHTML = highlightCpp(editor.value || '');
    target.style.transform = `translate(${-editor.scrollLeft}px, ${-editor.scrollTop}px)`;
  }

  function attach(editor) {
    if (!editor || editor.dataset.syntaxAttached === '1') return;
    editor.dataset.syntaxAttached = '1';
    const doSync = () => sync(editor);
    editor.addEventListener('input', doSync);
    editor.addEventListener('scroll', doSync, {passive: true});
    window.addEventListener('resize', doSync, {passive: true});
    doSync();
  }

  function init() {
    document.querySelectorAll('.syntax-source[data-syntax-target]').forEach(attach);
  }

  window.CaudexSyntax = {highlightCpp, sync, attach};
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', init, {once: true});
  else init();
})();
