// Live Monitor add-on: rostered (Google Classroom) students who haven't started.
// Follows the monitor's existing Assessment filter; refreshes every 20 s.
(() => {
  const box = document.querySelector("[data-not-started]");
  if (!box) return;
  const filter = document.getElementById("monitorAssessmentFilter");
  let data = {};
  const el = (tag, text, cls) => { const e = document.createElement(tag); if (cls) e.className = cls; if (text != null) e.textContent = text; return e; };
  const list = (students) => {
    const ul = el("ul");
    students.forEach((s) => { const li = el("li", s.name); li.append(el("span", `${s.section} · ${s.email}`)); ul.append(li); });
    return ul;
  };
  const render = () => {
    box.replaceChildren();
    const chosen = filter && filter.value !== "all" ? filter.value : null;
    const ids = chosen ? [chosen] : Object.keys(data);
    const withRoster = ids.filter((id) => data[id]);
    if (!withRoster.length) { box.hidden = true; return; }
    box.hidden = false;
    withRoster.forEach((id) => {
      const a = data[id];
      if (chosen) {
        box.append(el("h3", `Not started yet · ${a.students.length}`), list(a.students));
      } else {
        const d = el("details"); d.append(el("summary", `${a.title} · ${a.students.length} not started yet`), list(a.students)); box.append(d);
      }
    });
  };
  const refresh = async () => {
    try {
      const r = await fetch(box.dataset.endpoint, { credentials: "same-origin", cache: "no-store" });
      const j = await r.json();
      if (j.ok) { data = j.assessments; render(); }
    } catch (e) { /* keep last list */ }
  };
  if (filter) filter.addEventListener("change", render);
  refresh(); setInterval(() => { if (!document.hidden) refresh(); }, 30000);
})();
