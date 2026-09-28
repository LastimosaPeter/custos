// Google sign-in (students + instructors) and Google Classroom roster import.
// Loaded only on pages that render these blocks and only when GOOGLE_CLIENT_ID
// is configured. The server verifies every token; nothing here is trusted.
(() => {
  const post = async (url, csrf, body) => {
    const resp = await fetch(url, {
      method: "POST",
      credentials: "same-origin",
      headers: { "Content-Type": "application/json", "X-CSRFToken": csrf },
      body: JSON.stringify(body || {}),
    });
    let data = {};
    try { data = await resp.json(); } catch (e) { /* non-JSON error page */ }
    if (!resp.ok || data.ok === false) throw new Error(data.error || "Something went wrong. Please try again.");
    return data;
  };

  const whenGoogle = (check, cb, tries = 100) => {
    if (check()) return cb();
    if (tries <= 0) return;
    setTimeout(() => whenGoogle(check, cb, tries - 1), 100);
  };
  const hasId = () => window.google && google.accounts && google.accounts.id;
  const hasOAuth = () => window.google && google.accounts && google.accounts.oauth2;

  // ---- Sign in with Google (student exam login, instructor login) ----
  document.querySelectorAll("[data-google-signin]").forEach((block) => {
    const errorBox = block.querySelector("[data-google-error]");
    const showError = (msg) => { if (errorBox) { errorBox.textContent = msg; errorBox.hidden = false; } };
    whenGoogle(hasId, () => {
      google.accounts.id.initialize({
        client_id: block.dataset.clientId,
        ux_mode: "popup",
        auto_select: false,
        callback: async (response) => {
          try {
            const data = await post(block.dataset.endpoint, block.dataset.csrf, { credential: response.credential });
            window.location.assign(data.redirect || window.location.href);
          } catch (err) {
            showError(err.message);
          }
        },
      });
      const target = block.querySelector("[data-google-button]");
      google.accounts.id.renderButton(target, {
        theme: document.documentElement.dataset.theme === "dark" ? "filled_black" : "outline",
        size: "large", text: "signin_with", shape: "pill",
        width: Math.min(320, Math.max(200, target.clientWidth || 320)),
      });
    });
  });

  document.querySelectorAll("[data-google-signout]").forEach((btn) => {
    btn.addEventListener("click", async () => {
      try { await post(btn.dataset.endpoint, btn.dataset.csrf); } finally {
        if (window.google && google.accounts && google.accounts.id) google.accounts.id.disableAutoSelect();
        window.location.reload();
      }
    });
  });

  // ---- Google Classroom roster import (assessment page) ----
  const card = document.querySelector("[data-classroom]");
  if (!card) return;
  const csrf = card.dataset.csrf;
  const status = card.querySelector("[data-classroom-status]");
  const panel = card.querySelector("[data-classroom-import]");
  const courseSel = card.querySelector("[data-course-select]");
  const programSel = card.querySelector("[data-program-select]");
  const sectionSel = card.querySelector("[data-section-select]");
  const sections = JSON.parse(card.dataset.sections || "{}");
  let accessToken = null;
  const say = (msg) => { status.textContent = msg; };
  const option = (sel, value, label) => { const o = document.createElement("option"); o.value = value; o.textContent = label; sel.appendChild(o); };

  Object.keys(sections).forEach((p) => option(programSel, p, p));
  const fillSections = () => {
    sectionSel.replaceChildren();
    (sections[programSel.value] || []).forEach((s) => option(sectionSel, s, s));
  };
  programSel.addEventListener("change", fillSections);
  fillSections();

  // Pre-select Program/Section when the course name says e.g. "ZT11" or "ZT-12".
  const guessSection = () => {
    const label = courseSel.selectedOptions[0] ? courseSel.selectedOptions[0].textContent : "";
    const m = label.match(/\b([A-Za-z]{2})\s*-?\s*(\d{2})\b/g) || [];
    for (const hit of m) {
      const [, prog, sec] = hit.match(/([A-Za-z]{2})\s*-?\s*(\d{2})/);
      const P = prog.toUpperCase();
      if ((sections[P] || []).includes(sec)) {
        programSel.value = P; fillSections(); sectionSel.value = sec; return;
      }
    }
  };
  courseSel.addEventListener("change", guessSection);

  const loadCourses = async () => {
    say("Loading your Google Classroom courses…");
    try {
      const data = await post(card.dataset.coursesUrl, csrf, { access_token: accessToken });
      courseSel.replaceChildren();
      if (!data.courses.length) { say("No active courses where you are a teacher were found."); return; }
      data.courses.forEach((c) => option(courseSel, c.id, c.section ? `${c.name} · ${c.section}` : c.name));
      guessSection();
      panel.hidden = false;
      say("Choose the course and the Custos section its students belong to.");
    } catch (err) { say(err.message); }
  };

  let tokenClient = null;
  card.querySelector("[data-classroom-connect]").addEventListener("click", () => {
    whenGoogle(hasOAuth, () => {
      if (!tokenClient) {
        tokenClient = google.accounts.oauth2.initTokenClient({
          client_id: card.dataset.clientId,
          scope: card.dataset.scopes,
          callback: (resp) => {
            if (resp.error) { say("Google Classroom access was not granted."); return; }
            accessToken = resp.access_token;
            loadCourses();
          },
        });
      }
      tokenClient.requestAccessToken({ prompt: accessToken ? "" : "consent" });
    });
  });

  card.querySelector("[data-classroom-do-import]").addEventListener("click", async (ev) => {
    ev.target.disabled = true;
    say("Importing students…");
    try {
      const data = await post(card.dataset.importUrl, csrf, {
        access_token: accessToken, course_id: courseSel.value,
        program: programSel.value, class_section: sectionSel.value,
      });
      say(`Imported ${data.imported} students${data.skipped ? ` (${data.skipped} skipped: not a school Google account)` : ""}.`);
      setTimeout(() => window.location.reload(), 1200);
    } catch (err) { say(err.message); ev.target.disabled = false; }
  });

  card.querySelectorAll("[data-roster-delete]").forEach((btn) => {
    btn.addEventListener("click", async () => {
      if (!window.confirm("Remove this Google Classroom roster? Students not on another linked roster will no longer be restricted.")) return;
      try { await post(btn.dataset.rosterDelete, csrf); window.location.reload(); } catch (err) { say(err.message); }
    });
  });
})();
