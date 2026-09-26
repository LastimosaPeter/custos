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
