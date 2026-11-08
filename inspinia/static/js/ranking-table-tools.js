(function () {
  'use strict';

  var collator = new Intl.Collator(undefined, { numeric: true, sensitivity: 'base' });

  function normalize(value) {
    return String(value).normalize('NFKC').toLocaleLowerCase().replace(/\s+/g, ' ').trim();
  }

  function compare(left, right, direction) {
    if (left === null || right === null) return left === right ? 0 : left === null ? 1 : -1;
    if (typeof left !== typeof right) return typeof left === 'number' ? -1 : 1;
    var result = typeof left === 'number' ? left - right : collator.compare(left, right);
    return direction === 'desc' ? -result : result;
  }

  function orderRows(rows, column, direction) {
    return rows.slice().sort(function (left, right) {
      return compare(left.keys[column], right.keys[column], direction) || left.index - right.index;
    });
  }

  function matches(search, query) {
    return normalize(query).split(' ').filter(Boolean).every(function (word) { return search.includes(word); });
  }

  function spreadsheetCell(value) {
    var text = String(value).replace(/[\t\r\n]+/g, ' ').trim();
    return /^[=+@-]/.test(text) && !/^-?\d+(\.\d+)?$/.test(text) ? "'" + text : text;
  }

  function toTSV(headers, rows) {
    return [headers].concat(rows).map(function (cells) {
      return cells.map(spreadsheetCell).join('\t');
    }).join('\n');
  }

  function cellText(cell) {
    var clone = cell.cloneNode(true);
    clone.querySelectorAll('details').forEach(function (details) { details.remove(); });
    return clone.textContent.replace(/\s+/g, ' ').trim();
  }

  async function copyText(text) {
    if (navigator.clipboard && navigator.clipboard.writeText) {
      try { await navigator.clipboard.writeText(text); return; } catch (error) { /* Try local selection. */ }
    }
    var focused = document.activeElement;
    var textarea = document.createElement('textarea');
    textarea.value = text;
    textarea.readOnly = true;
    textarea.style.position = 'fixed';
    textarea.style.left = '-10000px';
    document.body.appendChild(textarea);
    try {
      textarea.select();
      if (!document.execCommand('copy')) throw new Error('Copy unavailable');
    } finally {
      textarea.remove();
      if (focused) focused.focus();
    }
  }

  function init(root) {
    if (root.dataset.localReady) return;
    var table = root.querySelector('table');
    var body = table.tBodies[0];
    var headers = Array.from(table.tHead.rows[0].cells);
    var labels = headers.map(function (header) { return header.textContent.trim(); });
    var rows = Array.from(body.querySelectorAll('[data-local-row]')).map(function (row, index) {
      var cells = Array.from(row.cells);
      var values = cells.map(cellText);
      return { node: row, index: index, values: values, search: normalize(row.textContent),
        keys: cells.map(function (cell, column) {
          var value = values[column];
          var raw = cell.getAttribute('data-sort-value');
          if (headers[column].dataset.sortType !== 'text' && raw !== null && raw !== '') return Number(raw);
          return !value || value === '—' ? null : value;
        }) };
    });
    if (!rows.length) return;
    root.dataset.localReady = 'true';
    root.querySelector('[data-local-tools]').hidden = false;
    var input = root.querySelector('[data-local-filter]');
    var copy = root.querySelector('[data-local-copy]');
    var count = root.querySelector('[data-local-count]');
    var feedback = root.querySelector('[data-local-feedback]');
    var visible = rows.slice();
    var copying = false;
    var activeColumn = -1;
    var direction = 'asc';
    var empty = document.createElement('tr');
    var emptyCell = document.createElement('td');
    emptyCell.colSpan = headers.length;
    emptyCell.className = 'text-muted py-4';
    emptyCell.textContent = 'No loaded rows match this filter.';
    empty.appendChild(emptyCell);
    input.placeholder = 'Filter ' + rows.length + ' loaded rows';

    function draw() {
      visible = [];
      rows.forEach(function (row) {
        row.node.hidden = !matches(row.search, input.value);
        if (!row.node.hidden) visible.push(row);
        body.appendChild(row.node);
      });
      empty.hidden = visible.length > 0;
      body.appendChild(empty);
      count.textContent = visible.length + ' of ' + rows.length + ' rows on this page';
      copy.disabled = copying || !visible.length;
    }

    headers.forEach(function (header, column) {
      var button = document.createElement('button');
      button.type = 'button';
      button.className = 'btn btn-link p-0 text-reset text-start text-decoration-none fw-semibold fs-xs';
      button.appendChild(document.createTextNode(labels[column] + ' '));
      var icon = document.createElement('i');
      icon.className = 'ti ti-arrows-sort';
      icon.setAttribute('aria-hidden', 'true');
      button.appendChild(icon);
      header.textContent = '';
      header.appendChild(button);
      header.setAttribute('aria-sort', 'none');
      button.addEventListener('click', function () {
        direction = activeColumn === column ? (direction === 'asc' ? 'desc' : 'asc') : (header.dataset.sortFirst || 'asc');
        activeColumn = column;
        rows = orderRows(rows, column, direction);
        headers.forEach(function (other, index) {
          other.setAttribute('aria-sort', index === column ? (direction === 'asc' ? 'ascending' : 'descending') : 'none');
          other.querySelector('i').className = 'ti ' + (index === column ? (direction === 'asc' ? 'ti-sort-ascending' : 'ti-sort-descending') : 'ti-arrows-sort');
        });
        feedback.textContent = '';
        draw();
      });
    });
    input.addEventListener('input', function () { feedback.textContent = ''; draw(); });
    copy.addEventListener('click', async function () {
      if (copying || !visible.length) return;
      var total = visible.length;
      var text = toTSV(labels, visible.map(function (row) { return row.values; }));
      copying = true;
      copy.disabled = true;
      try {
        await copyText(text);
        feedback.className = 'fs-xs text-success';
        feedback.textContent = 'Copied ' + total + ' row' + (total === 1 ? '' : 's') + ' with headers.';
      } catch (error) {
        feedback.className = 'fs-xs text-danger';
        feedback.textContent = 'Copy unavailable. Select the table and copy it manually.';
      } finally {
        copying = false;
        copy.disabled = !visible.length;
      }
    });
    draw();
  }

  if (typeof module !== 'undefined' && module.exports) {
    module.exports = { compare: compare, orderRows: orderRows, normalize: normalize, matches: matches, toTSV: toTSV };
  }
  if (typeof window !== 'undefined') window.RankingTableTools = { toTSV: toTSV, copyText: copyText };
  if (typeof document !== 'undefined') {
    var start = function () { document.querySelectorAll('[data-local-table]').forEach(init); };
    if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', start, { once: true });
    else start();
  }
})();
