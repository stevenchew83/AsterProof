/* The same document options control the live preview and the submitted PDF fields. */
(function () {
  "use strict";
  function init() {
    document.querySelectorAll("[data-pdf-document]").forEach(function (root) {
      const form = root.matches("form") ? root : root.querySelector("form");
      function refresh() {
        const authorInput = form.querySelector("[data-pdf-author-input]");
        const author = authorInput ? authorInput.value.trim() : (root.dataset.pdfAuthor || "");
        const authorPreview = root.querySelector("[data-pdf-preview-author]");
        const datePreview = root.querySelector("[data-pdf-preview-date]");
        const footer = root.querySelector("[data-pdf-preview-footer]");
        authorPreview.textContent = author;
        authorPreview.hidden = !form.querySelector("[data-pdf-show-author]").checked || !author;
        datePreview.textContent = root.dataset.pdfDate || "";
        datePreview.hidden = !form.querySelector("[data-pdf-show-date]").checked;
        footer.hidden = !form.querySelector("[data-pdf-show-footer]").checked;
      }
      form.addEventListener("input", refresh);
      form.addEventListener("change", refresh);
      refresh();
    });
  }
  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", init, {once: true});
  else init();
}());
