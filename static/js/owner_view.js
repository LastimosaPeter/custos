// Owner "Show all" confirmation modal (see templates/_owner_view_toggle.html).
(() => {
  const dialog = document.querySelector("[data-owner-view-all-dialog]");
  const open = document.querySelector("[data-owner-view-all-open]");
  if (!dialog || !open) return;
  open.addEventListener("click", () => dialog.showModal());
  dialog.querySelector("[data-owner-view-all-cancel]").addEventListener("click", () => dialog.close());
  dialog.addEventListener("click", (e) => { if (e.target === dialog) dialog.close(); });  // click outside closes
})();
