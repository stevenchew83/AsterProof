(function () {
  'use strict';
  var reference = /^[1-9]\d{0,18}:[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/;
  function validRefs(values) {
    return Array.isArray(values) && values.length <= 20 && values.every(function (value) {
      return typeof value === 'string' && reference.test(value) && BigInt(value.split(':')[0]) <= 9223372036854775807n;
    }) && new Set(values.map(function (value) { return value.split(':')[0]; })).size === values.length;
  }
  function basketURL(href, refs, flow) {
    var url = new URL(href);
    url.searchParams.delete('share');
    refs.forEach(function (ref) { url.searchParams.append('share', ref); });
    url.searchParams.set('flow', flow);
    return url.href;
  }
  function loadBasket(storage, key, fallback) {
    var raw = storage.getItem(key);
    if (raw === null) return fallback;
    var refs = JSON.parse(raw);
    if (!validRefs(refs)) throw new Error('Invalid stored selection');
    return refs;
  }
  function seedDraft(storage, key, refs, navigationType) {
    if (!['back_forward', 'reload'].includes(navigationType) || storage.getItem(key) === null) {
      storage.setItem(key, JSON.stringify(refs));
    }
  }
  if (typeof module === 'object' && module.exports) module.exports = {validRefs: validRefs, basketURL: basketURL, loadBasket: loadBasket, seedDraft: seedDraft};
  if (typeof document === 'undefined') return;

  document.querySelectorAll('[data-completed-flow]').forEach(function (root) {
    if (!/^[0-9a-f-]{36}$/.test(root.dataset.completedFlow || '')) return;
    try {
      window.sessionStorage.setItem('asterproof.curated-selection:' + root.dataset.curatedUser + ':' + root.dataset.completedFlow, '[]');
    } catch (error) { /* The successful publication is independent of tab storage. */ }
  });

  document.querySelectorAll('[data-curated-builder]').forEach(function (form) {
    var key = 'asterproof.curated-draft-order:' + form.dataset.curatedUser + ':' + form.dataset.curatedFlow + ':' +
      form.dataset.curatedCollection + ':' + form.dataset.curatedRevision;
    var storage;
    var version = 0;
    var restoring = false;
    var blocked = false;
    function refs() {
      return Array.from(form.querySelectorAll('[data-collection-item]'), function (item) { return item.dataset.collectionItem; });
    }
    try {
      storage = window.sessionStorage;
      var navigation = window.performance.getEntriesByType('navigation')[0];
      seedDraft(storage, key, refs(), navigation && navigation.type);
    } catch (error) { storage = null; }
    var url = new URL(window.location.href);
    url.searchParams.set('flow', form.dataset.curatedFlow);
    window.history.replaceState(null, '', url.href);
    form.addEventListener('collectionchange', function () {
      version += 1;
      blocked = false;
      try { if (storage) storage.setItem(key, JSON.stringify(refs())); } catch (error) { storage = null; }
    });
    function guardSubmission(event) {
      if (!restoring && !blocked) return;
      event.preventDefault();
      form.querySelector('[data-collection-feedback]').textContent = restoring ?
        'Restoring the latest reading order. Please wait.' : 'Reload before reviewing or browsing this draft.';
    }
    form.addEventListener('submit', guardSubmission);
    var appendForm = document.querySelector('[data-existing-collection]');
    if (appendForm) appendForm.addEventListener('submit', guardSubmission);
    window.addEventListener('pageshow', async function () {
      if (!storage || restoring) return;
      var review = form.querySelector('button[value="review"]');
      var wasDisabled = review.disabled;
      var currentVersion = version;
      var restored = false;
      var timer;
      try {
        var saved = loadBasket(storage, key, refs());
        if (JSON.stringify(saved) === JSON.stringify(refs())) return;
        restoring = true;
        review.disabled = true;
        var controller = new AbortController();
        timer = setTimeout(function () { controller.abort(); }, 10000);
        var endpoint = new URL(form.dataset.selectionUrl, window.location.href);
        saved.forEach(function (ref) { endpoint.searchParams.append('share', ref); });
        var response = await fetch(endpoint.href, {credentials: 'same-origin', cache: 'no-store', signal: controller.signal});
        if (!response.ok) throw new Error('Selection unavailable');
        var data = await response.json();
        if (!Array.isArray(data.shares) || data.shares.length !== saved.length ||
          !data.shares.every(function (row, index) { return row.ref === saved[index]; })) throw new Error('Invalid selection');
        // A manual edit during this read takes precedence over its stale result.
        if (version !== currentVersion) { restored = true; return; }
        form.dispatchEvent(new CustomEvent('collectionrestore', {detail: data.shares}));
        restored = true;
      } catch (error) {
        blocked = true;
        form.querySelector('[data-collection-feedback]').textContent = 'Unable to restore the latest reading order. Reload before reviewing.';
      } finally {
        clearTimeout(timer);
        if (restoring) review.disabled = restored ? wasDisabled : true;
        restoring = false;
      }
    });
  });

  document.querySelectorAll('[data-curated-selection]').forEach(function (root) {
    var flow = root.dataset.curatedFlow;
    var key = 'asterproof.curated-selection:' + root.dataset.curatedUser + ':' + flow;
    var notice = root.querySelector('[data-selection-persistence]');
    var storage;
    function refs() {
      return Array.from(root.querySelectorAll('[data-collection-item]'), function (item) { return item.dataset.collectionItem; });
    }
    function unavailable() {
      storage = null;
      if (notice) notice.textContent = 'Tab storage is unavailable. Selection is kept in page links; browser Back may restore an earlier selection.';
    }
    function syncLinks(values) {
      root.querySelectorAll('form[method="get"]').forEach(function (form) {
        if (form.hasAttribute('data-selection-next')) return;
        form.querySelectorAll('[data-basket-field]').forEach(function (input) { input.remove(); });
        [['flow', flow]].concat(values.map(function (value) { return ['share', value]; })).forEach(function (pair) {
          var input = document.createElement('input');
          input.type = 'hidden'; input.name = pair[0]; input.value = pair[1]; input.dataset.basketField = '';
          form.appendChild(input);
        });
      });
      root.querySelectorAll('.app-table-pager a, [data-selection-reset]').forEach(function (link) {
        link.href = basketURL(link.href, values, flow);
      });
    }
    function restore() {
      if (!storage) return;
      try {
        var current = refs();
        var saved = loadBasket(storage, key, current);
        if (JSON.stringify(saved) !== JSON.stringify(current)) {
          // Rehydrate every label and eligibility check on the server. This also
          // handles a restored Back/forward-cache document without trusting its DOM.
          window.location.replace(basketURL(window.location.href, saved, flow));
          return;
        }
        storage.setItem(key, JSON.stringify(current));
      } catch (error) { unavailable(); }
    }
    // Keep even an empty first page in this flow when Back needs a network reload.
    window.history.replaceState(null, '', basketURL(window.location.href, refs(), flow));
    try { storage = window.sessionStorage; restore(); } catch (error) { unavailable(); }
    syncLinks(refs());
    root.addEventListener('collectionchange', function () {
      var current = refs();
      try { if (storage) storage.setItem(key, JSON.stringify(current)); } catch (error) { unavailable(); }
      window.history.replaceState(null, '', basketURL(window.location.href, current, flow));
      syncLinks(current);
    });
    window.addEventListener('pageshow', restore);
    window.addEventListener('popstate', restore);
  });
})();
