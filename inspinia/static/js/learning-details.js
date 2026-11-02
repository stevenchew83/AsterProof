/* Teaching details edit the same metadata submitted by the shared document editor. */
(() => {
  const form = document.querySelector('[data-learning-editor]');
  if (!form) return;
  const metadata = form.elements.metadata;
  const concepts = form.querySelector('[data-learning-concepts]');
  const primary = form.querySelector('[data-learning-primary]');
  const level = form.querySelector('[data-learning-level]');
  let initial;
  try { initial = JSON.parse(metadata.value || '{}'); } catch { initial = {}; }
  const selected = initial.concepts || [];
  for (const option of concepts.options) option.selected = selected.some(row => row.id === option.value);
  primary.value = selected.find(row => row.role === 'primary')?.id || '';
  level.value = initial.level || '';
  for (const input of [concepts, primary, level]) input.addEventListener('change', () => {
    let value;
    try { value = JSON.parse(metadata.value || '{}'); } catch { return; }
    value.concepts = Array.from(concepts.selectedOptions, option => ({id: option.value, role: option.value === primary.value ? 'primary' : 'supporting'}));
    if (level.value) value.level = level.value; else delete value.level;
    metadata.value = JSON.stringify(value);
    metadata.dispatchEvent(new Event('change', {bubbles: true}));
    form.dispatchEvent(new Event('input', {bubbles: true}));
  });
})();
