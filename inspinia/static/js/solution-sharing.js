(function () {
  'use strict';
  document.querySelectorAll('[data-copy-public-link]').forEach(function (button) {
    button.addEventListener('click', async function () {
      var feedback = document.querySelector('[data-copy-feedback]');
      try {
        await navigator.clipboard.writeText(button.dataset.copyPublicLink);
        if (feedback) feedback.textContent = 'Link copied.';
      } catch (error) {
        var input = document.getElementById('public-solution-url');
        if (input) { input.focus(); input.select(); }
        if (feedback) feedback.textContent = input ? 'Select and copy the public link above.' : 'Copy this page’s address to share it.';
      }
    });
  });
  document.querySelectorAll('[data-share-form]').forEach(function (form) {
    form.addEventListener('submit', function (event) {
      if (form.dataset.submitting) { event.preventDefault(); return; }
      form.dataset.submitting = 'true';
      form.setAttribute('aria-busy', 'true');
    });
  });
})();
