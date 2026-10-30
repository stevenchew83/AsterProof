(function () {
  'use strict';
  var dialog = document.getElementById('solution-share-dialog');
  var trigger = document.getElementById('solution-share-trigger');
  var editor = document.getElementById('solution-editor-form');
  if (!dialog || !trigger || !editor || typeof dialog.showModal !== 'function') return;

  var get = function (name) { return dialog.querySelector('[data-share-' + name + ']'); };
  var feedback = get('feedback');
  var state = null;
  var busy = false;
  var loading = false;
  var generation = 0;
  var opener = trigger;
  var narrow = window.matchMedia('(max-width: 767px)');
  var endpoint = dialog.dataset.shareUrl;
  var buttons = Array.from(dialog.querySelectorAll('[data-share-action], [data-share-copy]'));

  function position() {
    if (!dialog.open || narrow.matches) return;
    var anchor = trigger.getBoundingClientRect();
    var box = dialog.getBoundingClientRect();
    var left = Math.max(12, Math.min(anchor.right - box.width, window.innerWidth - box.width - 12));
    var top = Math.max(12, Math.min(anchor.bottom + 10, window.innerHeight - box.height - 12));
    dialog.style.setProperty('--share-left', left + 'px');
    dialog.style.setProperty('--share-top', top + 'px');
  }

  function setFeedback(message, error) {
    feedback.textContent = message || '';
    feedback.classList.toggle('text-danger', Boolean(error));
    position();
  }

  function syncDirty() {
    var saveStatus = document.getElementById('solution-save-status');
    get('dirty').hidden = !saveStatus || saveStatus.dataset.dirty !== 'true';
    position();
  }

  function setLink(link, href, enabled) {
    if (href) link.href = href;
    else link.removeAttribute('href');
    link.setAttribute('aria-disabled', String(!enabled));
    link.tabIndex = enabled ? 0 : -1;
  }

  function keepFocusInside() {
    if (dialog.open && !dialog.contains(document.activeElement)) get('close').focus({preventScroll: true});
  }

  function render() {
    var ready = Boolean(state) && !loading && !busy;
    get('content').hidden = !state;
    get('footer').hidden = !state;
    buttons.forEach(function (button) { button.disabled = !ready; });
    dialog.setAttribute('aria-busy', String(loading || busy));
    if (!state) { position(); keepFocusInside(); return; }

    var active = state.is_active;
    get('saved-title').textContent = state.saved_title || 'Your solution';
    var credit = [state.saved_author ? 'By ' + state.saved_author : '', state.saved_date].filter(Boolean).join(' · ');
    get('saved-credit').textContent = credit;
    get('saved-credit').hidden = !credit;
    get('access-label').textContent = active ? 'Anyone with the link' : 'Only you';
    get('access-icon').className = active ? 'ti ti-world' : 'ti ti-lock';
    get('access-description').textContent = active ? 'Anyone can read or forward it.' : 'Not shared publicly.';
    get('permission').hidden = !active;
    get('version').textContent = active
      ? (state.has_saved_changes ? 'Saved changes not shared' : 'Shared version up to date')
      : (endpoint ? 'Create a link to the saved version.' : 'Save a draft first to share.');
    get('version').classList.toggle('fw-semibold', Boolean(active && state.has_saved_changes));
    get('link').value = active ? state.share_url : '';
    get('link-group').hidden = !active;
    get('copy').hidden = !active;
    get('whatsapp').hidden = !active;
    setLink(get('whatsapp'), state.whatsapp_url, ready && active);
    get('stop-row').hidden = !active;
    get('update-row').hidden = !active || !state.has_saved_changes || !state.can_share;
    setLink(get('review'), state.review_url, ready && Boolean(endpoint));
    get('review').hidden = !active || !state.has_saved_changes || !state.can_share;
    dialog.querySelector('[data-share-action="create"]').hidden = active || !state.can_share;
    get('preview').hidden = !endpoint;
    get('preview').textContent = active ? 'Preview ↗' : 'Review saved version ↗';
    setLink(get('preview'), state.preview_url, ready && Boolean(endpoint));
    get('footer-note').textContent = active ? 'Anyone with the link can read it.' : 'Your draft stays separate.';
    document.querySelector('[data-share-active-notice]').hidden = !active;
    document.querySelector('[data-share-indicator]').hidden = !active;
    syncDirty();
    position();
    keepFocusInside();
  }

  async function request(method, params) {
    var controller = new AbortController();
    var timeout = window.setTimeout(function () { controller.abort(); }, 15000);
    try {
      var response = await fetch(endpoint, {
        method: method, credentials: 'same-origin', cache: 'no-store', redirect: 'error',
        headers: {Accept: 'application/json'}, body: params,
        signal: controller.signal
      });
      var result = await response.json();
      if (method === 'GET' && (!response.ok || typeof result.is_active !== 'boolean')) throw new Error('Unavailable');
      if (method === 'POST' && typeof result.ok !== 'boolean') throw new Error('Unconfirmed');
      return result;
    } finally {
      window.clearTimeout(timeout);
    }
  }

  async function refresh(message, error) {
    var current = ++generation;
    loading = true;
    get('retry').hidden = true;
    get('recovery').hidden = true;
    render();
    if (!message) setFeedback('Loading sharing settings…');
    try {
      var result = await request('GET');
      if (current !== generation) return;
      state = result;
      setFeedback(message || result.error, error || Boolean(result.error));
    } catch (failure) {
      if (current !== generation) return;
      state = null;
      get('retry').hidden = false;
      get('recovery').hidden = false;
      setFeedback('Sharing settings are unavailable. Your editor is still open. Retry loading, or reopen Share after signing in.', true);
    } finally {
      if (current === generation) { loading = false; render(); }
    }
  }

  async function changeSharing(action) {
    if (busy || loading || !state) return;
    // Send only the reviewed saved-version identifiers, never editor contents.
    var params = new URLSearchParams({
      action: action,
      source_version: state.source_version,
      share_revision: state.share_revision,
      review_digest: state.review_digest,
      csrfmiddlewaretoken: editor.querySelector('[name="csrfmiddlewaretoken"]').value
    });
    busy = true;
    render();
    setFeedback(action === 'stop' ? 'Stopping sharing…' : 'Updating the public copy…');
    var message, error;
    try {
      var result = await request('POST', params);
      message = result.message;
      error = !result.ok;
    } catch (failure) {
      message = 'The change could not be confirmed. Current sharing settings have been rechecked below.';
      error = true;
    } finally {
      busy = false;
      // Reconcile with a read, including after an ambiguous network failure.
      // Never automatically repeat a create, update, or stop request.
      await refresh(message, error);
    }
  }

  function open(event) {
    event.preventDefault();
    opener = event.currentTarget;
    if (!dialog.open) dialog.showModal();
    document.documentElement.classList.add('solution-share-open');
    trigger.setAttribute('aria-expanded', 'true');
    if (endpoint) refresh();
    else {
      state = {is_active: false, can_share: false, saved_title: 'Your solution'};
      render();
      setFeedback('Save your solution before creating a public link.');
    }
    position();
  }

  document.querySelectorAll('[data-share-open]').forEach(function (button) { button.addEventListener('click', open); });
  get('close').addEventListener('click', function () { dialog.close(); });
  dialog.addEventListener('close', function () {
    generation += 1;
    document.documentElement.classList.remove('solution-share-open');
    trigger.setAttribute('aria-expanded', 'false');
    var target = opener.isConnected && opener.getClientRects().length ? opener : trigger;
    target.focus({preventScroll: true});
  });
  document.addEventListener('keydown', function (event) {
    if (!dialog.open || event.key !== 'Tab') return;
    var focusable = Array.from(dialog.querySelectorAll('button, a[href], input, summary, [tabindex]')).filter(function (node) {
      return !node.disabled && node.tabIndex >= 0 && node.getAttribute('aria-disabled') !== 'true' && node.getClientRects().length;
    });
    if (!focusable.length) return;
    var first = focusable[0], last = focusable[focusable.length - 1];
    var outside = !dialog.contains(document.activeElement);
    if (event.shiftKey && (document.activeElement === first || outside)) {
      event.preventDefault(); last.focus();
    } else if (!event.shiftKey && (document.activeElement === last || outside)) {
      event.preventDefault(); first.focus();
    }
  });
  dialog.addEventListener('click', function (event) {
    if (event.target !== dialog) return;
    var box = dialog.getBoundingClientRect();
    if (event.clientX < box.left || event.clientX > box.right || event.clientY < box.top || event.clientY > box.bottom) dialog.close();
  });
  dialog.querySelectorAll('[data-share-action]').forEach(function (button) {
    button.addEventListener('click', function () { changeSharing(button.dataset.shareAction); });
  });
  dialog.querySelectorAll('a').forEach(function (link) {
    link.addEventListener('click', function (event) { if (link.getAttribute('aria-disabled') === 'true') event.preventDefault(); });
  });
  get('retry').addEventListener('click', function () { refresh(); });
  get('copy').addEventListener('click', async function () {
    if (!state || busy || loading || !state.is_active) return;
    try {
      await navigator.clipboard.writeText(state.share_url);
      setFeedback('Link copied.');
    } catch (failure) {
      get('options').open = true;
      get('link-group').open = true;
      get('link').focus();
      get('link').select();
      setFeedback('Select and copy the public link above.');
    }
  });
  editor.addEventListener('asterproof:solution-save-state', syncDirty);
  dialog.querySelectorAll('details').forEach(function (details) {
    details.addEventListener('toggle', position);
  });
  window.addEventListener('resize', position);
  trigger.hidden = false;
  var fallback = document.querySelector('[data-share-fallback]');
  if (fallback) fallback.hidden = true;
})();
