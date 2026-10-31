(function () {
  'use strict';
  document.querySelectorAll('[data-collection-selection], [data-collection-builder]').forEach(function (root) {
    var list = root.querySelector('[data-collection-order]');
    var choices = Array.from(root.querySelectorAll('[data-solution-choice]'));
    var select = root.querySelector('[data-collection-add]');
    var addButton = root.querySelector('[data-collection-add-button]');
    var feedback = root.querySelector('[data-collection-feedback], [data-selection-count]');
    var max = Number(root.dataset.maxSolutions || 20);
    var inputName = root.dataset.collectionInput || 'solution';
    function items() { return Array.from(list.querySelectorAll('[data-collection-item]')); }
    function ids() { return items().map(function (item) { return item.dataset.collectionItem; }); }
    function announce(message) { if (feedback) feedback.textContent = message; }
    function refresh(sync) {
      var ordered = ids();
      items().forEach(function (item, index) {
        item.querySelector('[data-collection-move="up"]').disabled = index === 0;
        item.querySelector('[data-collection-move="down"]').disabled = index === ordered.length - 1;
        var label = item.querySelector('[data-collection-label]').textContent;
        item.querySelector('[data-collection-remove]').setAttribute('aria-label', 'Remove ' + label);
        item.querySelectorAll('[data-collection-move]').forEach(function (button) {
          button.setAttribute('aria-label', 'Move ' + label + ' ' + button.dataset.collectionMove);
        });
      });
      choices.forEach(function (choice) {
        var index = ordered.indexOf(choice.value);
        choice.checked = index !== -1;
        var badge = choice.closest('tr').querySelector('[data-selection-number]');
        badge.hidden = index === -1;
        badge.textContent = index + 1;
      });
      if (select) {
        Array.from(select.options).forEach(function (option) { option.disabled = ordered.includes(option.value); });
        addButton.disabled = ordered.length >= max || !select.value || ordered.includes(select.value);
      }
      var tray = root.querySelector('[data-selection-tray]');
      if (tray) tray.hidden = !ordered.length;
      var submit = root.querySelector('[data-collection-submit]');
      if (submit) submit.disabled = !ordered.length;
      announce(ordered.length ? ordered.length + ' selected. Reading order is shown above.' :
        (select ? 'Add a solution to start your collection.' : 'Select solutions in reading order.'));
      if (sync !== false) root.dispatchEvent(new CustomEvent('collectionchange', {detail: ordered}));
    }
    function append(id, label) {
      if (ids().includes(id)) return;
      if (ids().length >= max) { announce('You can select up to ' + max + ' solutions.'); return; }
      var item = document.createElement('li');
      item.className = 'list-group-item d-flex align-items-center gap-2';
      item.dataset.collectionItem = id;
      item.innerHTML = '<input type="hidden" name="solution"><span class="flex-grow-1 text-break" data-collection-label></span>' +
        '<div class="d-flex gap-1 flex-shrink-0">' +
        '<button type="button" class="btn btn-outline-secondary btn-sm" data-collection-move="up"><i class="ti ti-arrow-up" aria-hidden="true"></i></button>' +
        '<button type="button" class="btn btn-outline-secondary btn-sm" data-collection-move="down"><i class="ti ti-arrow-down" aria-hidden="true"></i></button>' +
        '<button type="button" class="btn btn-outline-danger btn-sm" data-collection-remove><i class="ti ti-x" aria-hidden="true"></i></button></div>';
      item.querySelector('input').value = id;
      item.querySelector('input').name = inputName;
      item.querySelector('[data-collection-label]').textContent = label;
      list.appendChild(item);
    }
    choices.forEach(function (choice) {
      // Submit only the tray's ordered inputs, rather than table DOM order.
      choice.removeAttribute('name');
      if (choice.checked) append(choice.value, choice.dataset.solutionLabel);
      choice.addEventListener('change', function () {
        var atLimit = ids().length >= max;
        var adding = choice.checked;
        if (adding && inputName === 'share' && ids().some(function (id) {
          return id !== choice.value && id.split(':')[0] === choice.value.split(':')[0];
        })) {
          refresh();
          announce('Remove the unavailable entry before selecting its new shared version.');
          return;
        }
        if (choice.checked) append(choice.value, choice.dataset.solutionLabel);
        else items().filter(function (item) { return item.dataset.collectionItem === choice.value; }).forEach(function (item) { item.remove(); });
        refresh();
        if (adding && atLimit && !choice.checked) announce('You can select up to ' + max + ' solutions.');
      });
    });
    list.addEventListener('click', function (event) {
      var button = event.target.closest('[data-collection-move], [data-collection-remove]');
      if (!button) return;
      var item = button.closest('[data-collection-item]');
      var label = item.querySelector('[data-collection-label]').textContent;
      if (button.hasAttribute('data-collection-remove')) {
        var next = item.nextElementSibling || item.previousElementSibling;
        item.remove();
        refresh();
        if (next) next.querySelector('[data-collection-remove]').focus();
        else if (select) select.focus();
        else if (choices.length) choices[0].focus();
        announce(label + ' removed. ' + ids().length + ' selected.');
        return;
      }
      if (button.dataset.collectionMove === 'up' && item.previousElementSibling) list.insertBefore(item, item.previousElementSibling);
      else if (button.dataset.collectionMove === 'down' && item.nextElementSibling) list.insertBefore(item.nextElementSibling, item);
      refresh();
      item.tabIndex = -1;
      item.focus();
      announce(label + ' moved to position ' + (items().indexOf(item) + 1) + '.');
    });
    var clear = root.querySelector('[data-collection-clear]');
    if (clear) clear.addEventListener('click', function () {
      items().forEach(function (item) { item.remove(); });
      refresh();
    });
    root.addEventListener('collectionrestore', function (event) {
      items().forEach(function (item) { item.remove(); });
      event.detail.forEach(function (row) {
        append(row.ref, row.label + (row.author ? ' · ' + row.author : '') +
          (row.available ? '' : ' · Unavailable — remove or replace'));
      });
      refresh();
    });
    if (select) {
      select.addEventListener('change', refresh);
      addButton.addEventListener('click', function () {
        if (!select.value) return;
        append(select.value, select.options[select.selectedIndex].textContent);
        select.value = '';
        refresh();
      });
    }
    var filter = root.querySelector('[data-collection-filter]');
    if (filter) filter.addEventListener('input', function () {
      var query = filter.value.trim().toLocaleLowerCase();
      root.querySelectorAll('[data-solution-row]').forEach(function (row) {
        row.hidden = !row.querySelector('[data-solution-choice]').dataset.solutionLabel.toLocaleLowerCase().includes(query);
      });
    });
    var existingForm = document.querySelector('[data-existing-collection]');
    if (existingForm) existingForm.addEventListener('submit', function () {
      existingForm.querySelectorAll('input[name="' + inputName + '"]').forEach(function (input) { input.remove(); });
      ids().forEach(function (id) {
        var input = document.createElement('input');
        input.type = 'hidden'; input.name = inputName; input.value = id;
        existingForm.appendChild(input);
      });
    });
    refresh();
    // Browser back/forward restoration may restore checkbox state after startup.
    window.addEventListener('pageshow', function () { refresh(false); });
  });
})();
