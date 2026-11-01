const assert = require('node:assert/strict');
const {test} = require('node:test');
const {createRecovery, recoveryKey, decode, LEGACY_KEY, TTL} = require('../../inspinia/static/js/solution-document-recovery.js');

function controls(current, {storage = new Map(), owner = 'alice', problem = 'p1', types = {}} = {}) {
  const previousWindow = global.window;
  function control() {
    const events = {};
    return {hidden: false, checked: false, textContent: '', addEventListener: (name, fn) => {events[name] = fn;}, fire: name => events[name]?.({})};
  }
  const elements = Object.fromEntries(['enable', 'status', 'offer', 'offer-text', 'clear', 'restore'].map(name => ['[data-draft-' + name + ']', control()]));
  const listeners = {};
  global.window = {localStorage: {getItem: key => storage.get(key) ?? null, setItem: (key, value) => storage.set(key, value), removeItem: key => storage.delete(key)}, addEventListener: (name, fn) => {listeners[name] = fn;}};
  const state = {document: structuredClone(current)};
  const panel = {querySelector: selector => elements[selector]};
  const root = {dataset: {owner, problem}, querySelector: () => panel, ownerDocument: {getElementById: () => ({textContent: JSON.stringify(types)})}};
  const recovery = createRecovery(root, {snapshot: () => state.document, restore: value => {state.document = structuredClone(value);}});
  return {elements, state, recovery, storage, listeners, finish() { global.window = previousWindow; }};
}

const doc = title => ({body_source: 'Proof of $x^2\\geq0$.', fields: {title, pdf_show_author: false}});

test('continuous recovery is opt-in and restores source and metadata only on request', () => {
  const app = controls(doc('Original'));
  try {
    app.recovery.flush(); assert.equal(app.storage.size, 0);
    app.elements['[data-draft-enable]'].checked = true;
    app.elements['[data-draft-enable]'].fire('change');
    assert.deepEqual(decode(app.storage.get(recoveryKey('alice', 'p1'))).document, doc('Original'));
    app.state.document = doc('Unsaved local writing');
    app.listeners.storage({key: recoveryKey('alice', 'p1')});
    assert.equal(app.elements['[data-draft-offer]'].hidden, false);
    assert.equal(app.state.document.fields.title, 'Unsaved local writing');
    app.elements['[data-draft-restore]'].fire('click');
    assert.deepEqual(app.state.document, doc('Original'));
  } finally {app.finish();}
});

test('a stale continuous-editor tab cannot replace a newer recovery copy', () => {
  const app = controls(doc('Old'));
  try {
    app.elements['[data-draft-enable]'].checked = true; app.elements['[data-draft-enable]'].fire('change');
    const savedAt = Date.now();
    const newer = JSON.stringify({version: 2, savedAt, expiresAt: savedAt + TTL, document: doc('New')});
    app.storage.set(recoveryKey('alice', 'p1'), newer);
    app.state.document.fields.title = 'Old tab edits'; app.recovery.flush();
    assert.equal(app.storage.get(recoveryKey('alice', 'p1')), newer);
    assert.equal(app.elements['[data-draft-offer]'].hidden, false);
    assert.equal(app.state.document.fields.title, 'Old tab edits');
  } finally {app.finish();}
});

test('legacy block recovery converts claim semantics before removing the old key', () => {
  const savedAt = Date.now();
  const document = {title: 'Old draft', author_name: '', problem_statement: '', pdf_show_author: true, pdf_show_date: false, pdf_show_footer: true,
    blocks: [{block_type: '7', title: 'Claim statement', body_source: 'A proof.', body_format: 'latex'}]};
  const old = JSON.stringify({version: 1, savedAt, expiresAt: savedAt + TTL, document});
  const storage = new Map([[LEGACY_KEY, old]]);
  const app = controls(doc('Current'), {storage, owner: 'anonymous', problem: '', types: {'7': {slug: 'claim', label: 'Claim'}}});
  try {
    assert.equal(app.state.document.fields.title, 'Current');
    assert.equal(storage.get(LEGACY_KEY), old);
    app.elements['[data-draft-restore]'].fire('click');
    assert.equal(app.state.document.body_source, '\\begin{claim}\nClaim statement\n\\end{claim}\n\n\\begin{proof}\nA proof.\n\\end{proof}');
    assert.equal(storage.has(LEGACY_KEY), false);
    assert.ok(decode(storage.get(recoveryKey('anonymous', ''))));
  } finally {app.finish();}
});

test('storage errors keep the document editable and never clear unrelated drafts', () => {
  const app = controls(doc('Keep me'), {storage: new Map([['unrelated', 'keep']])});
  try {
    global.window.localStorage.setItem = () => {throw new Error('quota');};
    app.elements['[data-draft-enable]'].checked = true; app.elements['[data-draft-enable]'].fire('change');
    assert.equal(app.elements['[data-draft-enable]'].checked, false);
    assert.deepEqual(app.state.document, doc('Keep me'));
    assert.equal(app.storage.get('unrelated'), 'keep');
    assert.match(app.elements['[data-draft-status]'].textContent, /unavailable/);
  } finally {app.finish();}
});
