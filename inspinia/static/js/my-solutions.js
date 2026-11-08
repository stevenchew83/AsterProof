(function () {
  'use strict';

  const root = document.querySelector('[data-my-solutions]');
  const controls = root?.querySelector('[data-solutions-controls]');
  if (!controls) return;

  const search = controls.querySelector('[data-solutions-search]');
  const status = controls.querySelector('[data-solutions-status-select]');
  const review = controls.querySelector('[data-solutions-review-select]');
  const clear = controls.querySelector('[data-solutions-clear]');
  const weekLabel = controls.querySelector('[data-solutions-week-label]');
  const resultCount = root.querySelector('[data-solutions-count]');
  const empty = root.querySelector('[data-solutions-empty]');
  const statusButtons = Array.from(root.querySelectorAll('[data-solutions-status]'));
  const weekButtons = Array.from(root.querySelectorAll('[data-solutions-week]'));
  const rows = Array.from(root.querySelectorAll('[data-solution-row]')).map((element) => ({
    element,
    label: element.querySelector('[data-solution-choice]').dataset.solutionLabel.toLocaleLowerCase(),
    status: element.dataset.solutionStatus,
    week: element.dataset.solutionWeek,
    review: element.dataset.solutionReview,
  }));
  let selectedWeek = null;

  // The page renders only the review statuses the author is allowed to see.
  Array.from(new Set(rows.map((row) => row.review))).sort().forEach((label) => {
    review.add(new Option(label, label));
  });

  function applyFilters() {
    const query = search.value.trim().toLocaleLowerCase();
    const week = selectedWeek?.dataset.solutionsWeek;
    let count = 0;
    rows.forEach((row) => {
      const matches = row.label.includes(query)
        && (!status.value || row.status === status.value)
        && (!review.value || row.review === review.value)
        && (week === undefined || row.week === week);
      row.element.hidden = !matches;
      if (matches) count += 1;
    });
    statusButtons.forEach((button) => {
      button.setAttribute('aria-pressed', String(button.dataset.solutionsStatus === status.value));
    });
    weekButtons.forEach((button) => {
      button.setAttribute('aria-pressed', String(button === selectedWeek));
    });
    weekLabel.hidden = !selectedWeek;
    weekLabel.textContent = selectedWeek ? 'Week of ' + selectedWeek.dataset.weekLabel : '';
    clear.hidden = !(search.value || status.value || review.value || selectedWeek);
    empty.hidden = count !== 0;
    resultCount.textContent = count === rows.length
      ? count + (count === 1 ? ' solution' : ' solutions')
      : count + ' of ' + rows.length + ' solutions';
  }

  statusButtons.forEach((button) => {
    button.disabled = false;
    button.addEventListener('click', () => {
      const key = button.dataset.solutionsStatus;
      status.value = status.value === key ? '' : key;
      applyFilters();
    });
  });
  weekButtons.forEach((button) => {
    button.disabled = false;
    button.addEventListener('click', () => {
      selectedWeek = selectedWeek === button ? null : button;
      applyFilters();
    });
  });
  search.addEventListener('input', applyFilters);
  search.addEventListener('keydown', (event) => {
    if (event.key === 'Enter' && !event.isComposing) event.preventDefault();
  });
  status.addEventListener('change', applyFilters);
  review.addEventListener('change', applyFilters);
  clear.addEventListener('click', () => {
    search.value = '';
    status.value = '';
    review.value = '';
    selectedWeek = null;
    applyFilters();
    search.focus();
  });
  window.addEventListener('pageshow', applyFilters);
  controls.hidden = false;
  applyFilters();
})();
