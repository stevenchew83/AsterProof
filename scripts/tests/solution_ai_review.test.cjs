const assert = require('node:assert/strict');
const {readFileSync} = require('node:fs');
const {test} = require('node:test');
const vm = require('node:vm');

let nextKey = 0;
const code = readFileSync(require.resolve('../../inspinia/static/js/solution-ai-review.js'), 'utf8');
const tick = () => new Promise(setImmediate);

class Element {
  constructor(tag = 'div') {
    this.tagName = tag.toUpperCase(); this.dataset = {}; this.children = []; this.events = {};
    this.value = ''; this._text = ''; this.hidden = false; this.disabled = false; this.checked = false;
    this.classes = new Set(); this.classList = {toggle: (name, enabled) => enabled ? this.classes.add(name) : this.classes.delete(name)};
  }
  get textContent() { return this._text + this.children.map(child => child.textContent).join(''); }
  set textContent(value) { this._text = String(value); this.children = []; }
  addEventListener(name, fn) { (this.events[name] ||= []).push(fn); }
  fire(name, event = {}) { return Promise.all((this.events[name] || []).map(fn => fn({target: this, ...event}))); }
  dispatchEvent(event) { this.fire(event.type, event); return true; }
  appendChild(child) { child.parentElement = this; this.children.push(child); return child; }
  replaceChildren(...children) { this.children = []; this._text = ''; children.forEach(child => this.appendChild(child)); }
  scrollIntoView() { this.scrolled = true; }
  all() { return this.children.flatMap(child => [child, ...child.all()]); }
}

function harness({enabled = true, acknowledged = false, checked = true, sourceText = 'First proof', dirty = true,
                  revisionId = 'revision-1', latestStatusUrl = '', storage = new Map(), withEditor = true} = {}) {
  const controls = {};
  for (const key of ['start', 'status', 'report', 'source', 'source-details', 'acknowledgement', 'statement', 'statement-confirmed']) {
    controls[key] = new Element(key === 'start' ? 'button' : 'div');
  }
  controls.acknowledgement.checked = checked;
  const explanation = new Element('details');
  controls.acknowledgement.closest = () => explanation;
  const coach = new Element();
  coach.querySelector = selector => {
    if (selector === '[data-review-statement-confirmed]:checked') return controls['statement-confirmed'].checked ? controls['statement-confirmed'] : null;
    const key = /^\[data-review-(.+)\]$/.exec(selector)?.[1];
    return controls[key] || null;
  };
  const form = new Element('form'), source = new Element('textarea'), csrf = new Element('input');
  source.value = sourceText; source.name = 'solution-body_source'; csrf.value = 'form-csrf'; csrf.name = 'csrfmiddlewaretoken';
  const version = new Element('input'), editorContext = new Element('input'), title = new Element('input');
  version.value = '1'; version.name = 'solution-base_version'; editorContext.value = 'signed-old'; editorContext.name = 'solution-editor_context';
  title.name = 'solution-title'; title.value = 'My proof';
  form.elements = [source, csrf, version, editorContext, title];
  form.action = '/solutions/problems/problem/draft/';
  form.querySelector = selector => {
    if (selector === '[data-solution-source]') return source;
    if (selector.includes('csrfmiddlewaretoken')) return csrf;
    if (selector.includes('base_version')) return version;
    if (selector.includes('editor_context')) return editorContext;
    return null;
  };
  const scope = new Element(); scope.dataset.owner = 'owner-1'; form.closest = () => scope;
  const calls = [], timers = new Map(), focused = [], panes = [], savedEvents = [];
  let uploads = 0, timerId = 0, activeEditor;
  const snapshot = () => ({body_source: source.value, fields: {title: title.value}});
  let baseline = dirty ? {body_source: 'Older proof', fields: {title: title.value}} : snapshot();
  const api = {
    source: () => source.value, snapshot,
    dirty: () => JSON.stringify(snapshot()) !== JSON.stringify(baseline),
    pendingUploads: () => uploads, focusRange: (...args) => focused.push(args), setPane: pane => panes.push(pane),
  };
  activeEditor = withEditor ? api : null;
  form.addEventListener('asterproof:solution-saved', event => {
    savedEvents.push(event.detail);
    if (activeEditor) baseline = event.detail.savedSnapshot;
  });
  const config = new Element('script');
  config.textContent = JSON.stringify({enabled, acknowledged, createUrl: '/solutions/problems/problem/reviews/',
    revisionId, editVersion: 1, latestStatusUrl});
  const document = new Element(); document.readyState = 'complete'; document.hidden = false;
  document.getElementById = id => id === 'solution-review-config' ? config : id === 'solution-editor-form' ? form : null;
  document.querySelector = selector => selector === '[data-ai-coach]' ? coach : null;
  document.createElement = tag => new Element(tag);
  document.createTextNode = text => { const node = new Element('#text'); node.textContent = text; return node; };
  const window = new Element(); window.location = {origin: 'https://asterproof.test', href: 'https://asterproof.test/solutions/problems/problem/draft/'};
  window.AsterProofDocumentEditors = {get: () => activeEditor};
  class FormData {
    constructor(value) { this.values = new Map((value?.elements || []).map(input => [input.name, input.value])); }
    set(name, value) { this.values.set(name, value); }
    get(name) { return this.values.get(name); }
  }
  class CustomEvent { constructor(type, options) { this.type = type; Object.assign(this, options); } }
  const fetch = (url, options = {}) => new Promise((resolve, reject) => calls.push({url, options, resolve, reject}));
  vm.runInNewContext(code, {window, document, URL, FormData, fetch, CustomEvent,
    crypto: {randomUUID: () => '00000000-0000-4000-8000-' + String(++nextKey).padStart(12, '0')},
    sessionStorage: {getItem: key => storage.get(key) || null, setItem: (key, value) => storage.set(key, value)},
    setTimeout: (fn, delay) => { const id = ++timerId; timers.set(id, {fn, delay}); return id; }, clearTimeout: id => timers.delete(id),
  });
  async function respond(index, data, {status = 200, redirected = false} = {}) {
    assert.ok(calls[index], 'fetch call ' + index + ' exists');
    calls[index].resolve({ok: status >= 200 && status < 300, status, redirected, json: async () => data});
    await tick();
  }
  return {controls, coach, form, source, csrf, version, editorContext, title, explanation, calls, timers, focused, panes,
    savedEvents, storage, api, config, respond, click: () => controls.start.fire('click'),
    fail: async index => { calls[index].reject(new Error('Connection interrupted')); await tick(); },
    editorReady: async () => { activeEditor = api; await window.fire('asterproof:editor-ready'); },
    setUploads: async count => { uploads = count; await form.fire('asterproof:editor-state'); },
    input: async text => { source.value = text; await form.fire('input'); },
    button: text => controls.report.all().find(node => node.tagName === 'BUTTON' && node.textContent === text),
  };
}

const saved = (revision = 'revision-1') => ({saved: true, revision_id: revision, edit_version: 2, editor_context: 'signed-new'});
const created = (id = 'review-1') => ({id, revision_id: 'revision-1', status: 'queued', status_url: '/solutions/problems/problem/reviews/' + id + '/'});
function completed({source = 'First proof', revision = 'revision-1', stale = false, hintLevel = 0, hintCount = 2} = {}) {
  const finding = {id: 'finding-1', reveal_url: created().status_url + 'findings/finding-1/reveal/',
    released_level: hintLevel, quote: source, explanation: '<script>must stay literal</script>',
    anchor: {line: 1, end_line: 1}, hint_count: hintCount};
  if (hintLevel) finding.hints = ['First hidden hint', 'Second hidden hint'].slice(0, hintLevel);
  return {id: 'review-1', status: 'completed', revision_id: revision, stale, reviewed_source: source,
    feedback: {assessment: 'gap_found', summary: 'A justification is missing.', strengths: [], findings: [finding], next_step: 'Explain the step.', limitations: []}};
}

test('first-use acknowledgement happens before saving or sending any request', async () => {
  const app = harness({checked: false});
  await app.click();
  assert.equal(app.calls.length, 0);
  assert.equal(app.explanation.open, true);
  assert.match(app.controls.status.textContent, /acknowledge/);
  assert.equal(app.source.value, 'First proof');
});

test('previous acknowledgement is honored and pending image uploads block review', async () => {
  const app = harness({checked: false, acknowledged: true});
  await app.setUploads(1);
  assert.equal(app.controls.start.disabled, true);
  await app.click();
  assert.equal(app.calls.length, 0);
  assert.match(app.controls.status.textContent, /upload/);
  await app.setUploads(0);
  assert.equal(app.controls.start.disabled, false, 'upload completion re-enables review without another keystroke');
});

test('Save and review keeps the dispatched snapshot dirty when writing changes during save', async () => {
  const app = harness();
  const click = app.click();
  assert.equal(app.calls[0].options.body.get('solution-body_source'), 'First proof');
  await app.input('Later unsaved proof');
  await app.respond(0, saved());
  assert.equal(app.version.value, 2);
  assert.equal(app.editorContext.value, 'signed-new');
  assert.equal(app.savedEvents[0].savedSnapshot.body_source, 'First proof');
  assert.equal(app.api.dirty(), true);
  const request = JSON.parse(app.calls[1].options.body);
  assert.equal(request.revision_id, 'revision-1');
  assert.equal(request.acknowledged, true);
  assert.equal(app.calls[1].options.headers['X-CSRFToken'], 'form-csrf');
  await app.respond(1, created());
  await app.respond(2, completed());
  await click;
  assert.equal(app.source.value, 'Later unsaved proof');
  assert.match(app.controls.status.textContent, /earlier version/);
});

test('authentication failure during save preserves the buffer and never enqueues review', async () => {
  const app = harness();
  const click = app.click();
  await app.respond(0, {}, {status: 401});
  await click;
  assert.equal(app.calls.length, 1);
  assert.equal(app.source.value, 'First proof');
  assert.match(app.controls.status.textContent, /Sign in again/);
  assert.equal(app.controls.start.disabled, false);
});

test('hints are fetched progressively and rendered as literal text', async () => {
  const app = harness({latestStatusUrl: created().status_url, dirty: false});
  assert.equal(app.calls[0].url, created().status_url);
  await app.respond(0, completed());
  assert.doesNotMatch(app.controls.report.textContent, /hidden hint/);
  assert.match(app.controls.report.textContent, /<script>must stay literal<\/script>/);
  assert.equal(app.controls.report.all().some(node => node.tagName === 'SCRIPT'), false);
  app.button('Reveal hint 1').fire('click');
  assert.match(app.calls[1].url, /findings\/finding-1\/reveal\/$/);
  assert.equal(app.calls[1].options.method, 'POST');
  assert.equal(JSON.parse(app.calls[1].options.body).level, 1);
  assert.ok(app.calls[1].options.headers['X-CSRFToken']);
  await app.respond(1, completed({hintLevel: 1}));
  assert.match(app.controls.report.textContent, /First hidden hint/);
  assert.doesNotMatch(app.controls.report.textContent, /Second hidden hint/);
  app.button('Reveal hint 2').fire('click');
  assert.equal(JSON.parse(app.calls[2].options.body).level, 2);
  await app.respond(2, completed({hintLevel: 2}));
  assert.match(app.controls.report.textContent, /Second hidden hint/);
  assert.equal(app.button('Reveal hint 2'), undefined);
});

test('reports with no hints do not offer an empty reveal action', async () => {
  const app = harness({latestStatusUrl: created().status_url});
  await app.respond(0, completed({hintCount: 0}));
  assert.equal(app.button('Reveal hint 1'), undefined);
});

test('passage links select the current source only when the reviewed version matches', async () => {
  const app = harness({latestStatusUrl: created().status_url, sourceText: '😀\nQuoted passage', dirty: false});
  const data = completed({source: app.source.value});
  data.feedback.findings[0].anchor = {line: 2, end_line: 2};
  await app.respond(0, data);
  await app.button('Show this passage').fire('click');
  assert.deepEqual(app.focused, [[3, app.source.value.length]]);
  assert.deepEqual(app.panes, ['write']);
  await app.input('A different proof');
  await app.button('Show this passage').fire('click');
  assert.equal(app.controls['source-details'].open, true);
  assert.equal(app.controls.source.all().find(node => node.tagName === 'MARK').textContent, 'Quoted passage');
  assert.equal(app.focused.length, 1);
});

test('an old hint response cannot replace the status or source of a newly requested revision', async () => {
  const app = harness({latestStatusUrl: created().status_url, dirty: false});
  await app.respond(0, completed());
  app.button('Reveal hint 1').fire('click');
  await app.input('New proof');
  const click = app.click();
  await app.respond(2, saved('revision-2'));
  await app.respond(3, created('review-2'));
  await app.respond(4, {status: 'queued', revision_id: 'revision-2', reviewed_source: 'New proof'});
  await click;
  assert.match(app.controls.status.textContent, /queued/);
  assert.equal(app.controls['source-details'].hidden, true);
  await app.respond(1, completed({hintLevel: 1}));
  assert.match(app.controls.status.textContent, /queued/);
  assert.equal(app.controls.source.textContent, 'New proof');
  assert.doesNotMatch(app.controls.report.textContent, /First hidden hint/);
});

test('a lost create response retains the same idempotency key across reload', async () => {
  const storage = new Map();
  const first = harness({storage});
  const click = first.click();
  await first.respond(0, saved());
  const originalKey = JSON.parse(first.calls[1].options.body).idempotency_key;
  await first.fail(1);
  await click;
  const reloaded = harness({storage, revisionId: 'revision-1', dirty: false});
  assert.equal(reloaded.calls.length, 0, 'recovery never automatically sends a paid request');
  const retry = reloaded.click();
  await reloaded.respond(0, saved());
  assert.equal(JSON.parse(reloaded.calls[1].options.body).idempotency_key, originalKey);
  await reloaded.respond(1, created());
  await reloaded.respond(2, completed());
  await retry;
});

test('saved feedback remains readable after review activation is turned off', async () => {
  const app = harness({enabled: false, latestStatusUrl: created().status_url, dirty: false});
  assert.equal(app.calls.length, 1);
  await app.respond(0, completed());
  assert.match(app.controls.report.textContent, /justification/);
  assert.equal(app.controls.start.disabled, true);
  await app.click();
  assert.equal(app.calls.length, 1);
});

test('server latest status takes precedence over an older device receipt', async () => {
  const storage = new Map([['asterproof.solution-review:owner-1:/solutions/problems/problem/reviews/', created('old-review').status_url]]);
  const app = harness({storage, latestStatusUrl: created('new-review').status_url});
  assert.match(app.calls[0].url, /new-review/);
  await app.respond(0, completed());
});

test('fallback textarea saves capture a baseline before an asynchronously loaded editor', async () => {
  const app = harness({withEditor: false});
  const click = app.click();
  await app.input('Changed while saving');
  await app.editorReady();
  await app.respond(0, saved());
  assert.equal(app.savedEvents[0].savedSnapshot.body_source, 'First proof');
  assert.equal(app.api.dirty(), true);
  await app.respond(1, created());
  await app.respond(2, completed());
  await click;
});

test('a failed stale hint request cannot overwrite a newer review status', async () => {
  const app = harness({latestStatusUrl: created().status_url, dirty: false});
  await app.respond(0, completed());
  app.button('Reveal hint 1').fire('click');
  await app.input('New proof');
  const click = app.click();
  await app.respond(2, saved('revision-2'));
  await app.respond(3, created('review-2'));
  await app.respond(4, {status: 'queued', revision_id: 'revision-2', reviewed_source: 'New proof'});
  await click;
  await app.fail(1);
  assert.match(app.controls.status.textContent, /queued/);
  assert.equal(app.controls.source.textContent, 'New proof');
});

test('revealing a hint on one finding does not advance another finding', async () => {
  const app = harness({latestStatusUrl: created().status_url, dirty: false});
  const data = completed();
  data.feedback.findings.push({...data.feedback.findings[0], id: 'finding-2',
    reveal_url: created().status_url + 'findings/finding-2/reveal/'});
  await app.respond(0, data);
  app.button('Reveal hint 1').fire('click');
  const released = structuredClone(data);
  released.feedback.findings[0].released_level = 1;
  released.feedback.findings[0].hints = ['First hidden hint'];
  await app.respond(1, released);
  app.button('Reveal hint 1').fire('click');
  assert.match(app.calls[2].url, /finding-2\/reveal\/$/);
  assert.equal(JSON.parse(app.calls[2].options.body).level, 1);
});
