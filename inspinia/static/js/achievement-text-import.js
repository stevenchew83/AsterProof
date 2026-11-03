// Progressive enhancement: the server also accepts another manual row after each review.
(() => {
  const form = document.querySelector('[data-achievement-review]');
  if (!form) return;
  const total = form.querySelector('[name="rows-TOTAL_FORMS"]');
  const container = form.querySelector('[data-achievement-rows]');
  const template = form.querySelector('[data-empty-row]');
  const add = form.querySelector('[data-add-row]');
  const status = form.querySelector('[data-row-count]');
  const limit = Number(form.dataset.maxRows);
  const update = () => {
    add.hidden = Number(total.value) >= limit;
    status.textContent = `${total.value} of ${limit} available rows. Exclude every row to save only the original context.`;
  };
  add.addEventListener('click', () => {
    const index = Number(total.value);
    if (index >= limit) return;
    const fragment = template.content.cloneNode(true);
    fragment.querySelectorAll('[name], [id], [for]').forEach(element => {
      ['name', 'id', 'for'].forEach(attribute => {
        if (element.hasAttribute(attribute)) {
          element.setAttribute(attribute, element.getAttribute(attribute).replaceAll('__prefix__', String(index)));
        }
      });
    });
    fragment.querySelector('[data-row-number]').textContent = String(index + 1);
    fragment.querySelector('[data-achievement-row]').setAttribute('aria-label', `Achievement suggestion ${index + 1}`);
    container.appendChild(fragment);
    total.value = String(index + 1);
    update();
    container.lastElementChild.querySelector('[name$="-title"]').focus();
  });
  update();
})();
