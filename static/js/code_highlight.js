(() => {
  'use strict';

  const KEYWORDS = new Set([
    'alignas','alignof','and','and_eq','asm','auto','bitand','bitor','bool','break','case','catch','char','char8_t','char16_t','char32_t','class','compl','concept','const','consteval','constexpr','constinit','const_cast','continue','co_await','co_return','co_yield','decltype','default','delete','do','double','dynamic_cast','else','enum','explicit','export','extern','false','float','for','friend','goto','if','inline','int','long','mutable','namespace','new','noexcept','not','not_eq','nullptr','operator','or','or_eq','private','protected','public','register','reinterpret_cast','requires','return','short','signed','sizeof','static','static_assert','static_cast','struct','switch','template','this','thread_local','throw','true','try','typedef','typeid','typename','union','unsigned','using','virtual','void','volatile','wchar_t','while','xor','xor_eq'
  ]);
  const BUILTINS = new Set([
    'std','string','vector','array','map','unordered_map','set','queue','stack','pair','tuple','cin','cout','cerr','clog','endl','getline','size_t','printf','scanf','main'
  ]);

  const esc = (s) => s.replace(/[&<>]/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;'}[c]));

  function span(cls, text) {
    return `<span class="tok-${cls}">${esc(text)}</span>`;
  }

  function highlightLine(line, state) {
    let i = 0;
    let out = '';

    // Treat preprocessor directives as a distinct token while preserving headers/strings.
    const firstNonSpace = line.search(/\S/);
    if (!state.blockComment && firstNonSpace >= 0 && line[firstNonSpace] === '#') {
      const leading = line.slice(0, firstNonSpace);
      const body = line.slice(firstNonSpace);
      const m = body.match(/^(#[A-Za-z_][A-Za-z0-9_]*)/);
      if (m) {
        out += esc(leading) + span('preprocessor', m[1]);
        i = firstNonSpace + m[1].length;
      }
    }

    while (i < line.length) {
      if (state.blockComment) {
        const end = line.indexOf('*/', i);
        if (end === -1) {
          out += span('comment', line.slice(i));
          return out;
        }
        out += span('comment', line.slice(i, end + 2));
        i = end + 2;
        state.blockComment = false;
        continue;
      }

      if (line.startsWith('//', i)) {
        out += span('comment', line.slice(i));
        break;
      }
      if (line.startsWith('/*', i)) {
        const end = line.indexOf('*/', i + 2);
        if (end === -1) {
          out += span('comment', line.slice(i));
          state.blockComment = true;
          break;
        }
        out += span('comment', line.slice(i, end + 2));
        i = end + 2;
        continue;
      }

      const ch = line[i];
      if (ch === '"' || ch === "'") {
        const quote = ch;
        let j = i + 1;
        let escaped = false;
        while (j < line.length) {
          const c = line[j];
          if (!escaped && c === quote) { j += 1; break; }
          if (!escaped && c === '\\') escaped = true;
          else escaped = false;
          j += 1;
        }
        out += span('string', line.slice(i, j));
        i = j;
        continue;
      }

      if (/\d/.test(ch) && (i === 0 || !/[A-Za-z_]/.test(line[i - 1]))) {
        const m = line.slice(i).match(/^(?:0[xX][0-9A-Fa-f]+|0[bB][01]+|(?:\d+\.?\d*|\.\d+)(?:[eE][+-]?\d+)?)[uUlLfF]*/);
        if (m) {
          out += span('number', m[0]);
          i += m[0].length;
          continue;
        }
      }

      if (/[A-Za-z_]/.test(ch)) {
        const m = line.slice(i).match(/^[A-Za-z_][A-Za-z0-9_]*/);
        const word = m[0];
        if (KEYWORDS.has(word)) out += span('keyword', word);
        else if (BUILTINS.has(word)) out += span('builtin', word);
        else out += esc(word);
        i += word.length;
        continue;
      }

      const op = line.slice(i).match(/^(?:<<=|>>=|<=>|::|->\*|->|\+\+|--|&&|\|\||==|!=|<=|>=|<<|>>|\+=|-=|\*=|\/=|%=|&=|\|=|\^=|[+\-*\/%=&|^!~<>?:])/);
      if (op) {
        out += span('operator', op[0]);
        i += op[0].length;
        continue;
      }

      out += esc(ch);
      i += 1;
    }
    return out;
  }

  function highlightBlock(code) {
    if (code.dataset.custosHighlighted === '1') return;
    const source = code.textContent.replace(/\r\n?/g, '\n').replace(/\n$/, '');
    const lines = source.split('\n');
    const state = {blockComment:false};
    code.innerHTML = lines.map((line, idx) => (
      `<span class="code-line"><span class="code-line-number" aria-hidden="true">${idx + 1}</span><span class="code-line-text">${highlightLine(line, state) || '&nbsp;'}</span></span>`
    )).join('');
    code.dataset.custosHighlighted = '1';
    code.closest('.code-block')?.classList.add('has-line-numbers');
  }

  function run() {
    document.querySelectorAll('.code-block code').forEach(highlightBlock);
  }

  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', run);
  else run();
})();
