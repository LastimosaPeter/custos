(() => {
  const sectionMap = {
    ZT: ["11", "12", "13"],
    ZS: ["11"],
  };

  document.querySelectorAll("[data-student-identity-form]").forEach((form) => {
    const program = form.querySelector("[data-program-select]");
    const section = form.querySelector("[data-section-select]");
    if (!program || !section) return;

    const refreshSections = () => {
      const previous = section.value || section.dataset.selectedSection || "11";
      const allowed = sectionMap[program.value] || ["11"];
      section.replaceChildren();
      allowed.forEach((value) => {
        const option = document.createElement("option");
        option.value = value;
        option.textContent = value;
        section.appendChild(option);
      });
      section.value = allowed.includes(previous) ? previous : allowed[0];
      section.dataset.selectedSection = section.value;
    };

    program.addEventListener("change", refreshSections);
    section.addEventListener("change", () => {
      section.dataset.selectedSection = section.value;
    });
    refreshSections();
  });
})();


(() => {
  document.querySelectorAll('.student-key-entry-form').forEach((form) => {
    const subject = form.querySelector('[data-session-subject]');
    const program = form.querySelector('[data-session-program]');
    const section = form.querySelector('[data-session-section]');
    if (!subject || !program || !section) return;

    const applyCourseDefaults = () => {
      const csec = subject.value === 'CSEC303';
      if (csec) {
        program.value = 'ZC';
        section.value = '32';
        program.readOnly = true;
        section.readOnly = true;
        program.setAttribute('aria-description', 'CSEC303 uses section ZC32');
        section.setAttribute('aria-description', 'CSEC303 uses section ZC32');
      } else {
        if (program.value === 'ZC') program.value = '';
        if (section.value === '32') section.value = '';
        program.readOnly = false;
        section.readOnly = false;
        program.placeholder = 'ZT or ZS';
        section.placeholder = '11, 12, 13…';
      }
    };

    subject.addEventListener('change', applyCourseDefaults);
    applyCourseDefaults();
  });
})();
