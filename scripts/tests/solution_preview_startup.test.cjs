const assert = require('node:assert/strict');
const {readFileSync} = require('node:fs');
const {test} = require('node:test');
const vm = require('node:vm');

const source = readFileSync(require.resolve('../../inspinia/static/js/solution-preview.js'), 'utf8');
async function settle() {
  await new Promise(setImmediate);
  await new Promise(setImmediate);
}

function events(target = {}) {
  const handlers = new Map();
  return Object.assign(target, {
    addEventListener(name, fn) {
      if (!handlers.has(name)) handlers.set(name, []);
      handlers.get(name).push(fn);
    },
    fire(name) { for (const fn of handlers.get(name) || []) fn({}); },
  });
}

function writer(readyState = 'loading') {
  const node = () => events({textContent: '', value: '', children: [], hidden: false,
    appendChild(child) { this.children.push(child); },
    replaceChildren() { this.children = []; },
    querySelectorAll() { return []; },
  });
  const root = node();
  root.dataset = {blockLimit: '32', plainBlockType: '1'};
  const ids = Object.fromEntries(['solution-preview-form', 'preview-block-list', 'id_blocks-TOTAL_FORMS',
    'preview-block-empty-form', 'preview-add-block', 'converter-block-preview', 'converter-statement',
    'converter-preview-status', 'converter-document-title'].map(id => [id, node()]));
  ids['solution-preview-form'].elements = Object.fromEntries(
    ['title', 'author_name', 'problem_statement', 'pdf_show_author', 'pdf_show_date', 'pdf_show_footer']
      .map(name => [name, {value: name === 'title' ? 'My proof' : '', checked: false}]),
  );
  const document = events({readyState, querySelector: () => root, getElementById: id => ids[id], createElement: node});
  const window = events();
  const timers = new Set();
  const calls = [];
  vm.runInNewContext(source, {document, window, setTimeout(fn, delay) {
    if (delay === 0) return setImmediate(fn);
    timers.add(fn); return fn;
  }, clearTimeout(fn) { if (typeof fn === 'function') timers.delete(fn); else clearImmediate(fn); }});
  function mathLoading() {
    let resolve;
    window.AsterProofMathReady = new Promise(done => { resolve = done; });
    window.MathJax = {startup: {promise: Promise.resolve()}, typesetClear() {},
      typesetPromise: async () => { calls.push(ids['converter-document-title'].textContent); }};
    return resolve;
  }
  function ready(resolve) { document.fire('asterproof:math-ready'); resolve(); }
  function input(title) {
    ids['solution-preview-form'].elements.title.value = title;
    ids['solution-preview-form'].fire('input');
    for (const fn of timers) fn();
    timers.clear();
  }
  return {document, window, ids, calls, mathLoading, ready, input};
}

test('one initial typeset when window load precedes MathJax readiness', async () => {
  const app = writer();
  const resolve = app.mathLoading();
  app.window.fire('load');
  app.ready(resolve);
  await settle();
  assert.deepEqual(app.calls, ['My proof']);
});

test('one initial typeset when MathJax readiness precedes window load', async () => {
  const app = writer();
  const resolve = app.mathLoading();
  app.ready(resolve);
  await settle();
  app.window.fire('load');
  await settle();
  assert.deepEqual(app.calls, ['My proof']);
});

test('a deferred homepage preview upgrades from text to math once and remains editable', async () => {
  const app = writer();
  app.window.fire('load');
  await settle();
  assert.equal(app.ids['converter-document-title'].textContent, 'My proof');
  assert.equal(app.calls.length, 0);
  const resolve = app.mathLoading();
  app.ready(resolve);
  await settle();
  assert.deepEqual(app.calls, ['My proof']);
  app.input('Updated proof');
  await settle();
  assert.deepEqual(app.calls, ['My proof', 'Updated proof']);
});

test('failed math loading still initializes and updates the text preview', async () => {
  const app = writer();
  let resolve;
  app.window.AsterProofMathReady = new Promise(done => { resolve = done; });
  app.window.MathJax = null;
  app.window.fire('load');
  resolve();
  await settle();
  assert.equal(app.ids['converter-document-title'].textContent, 'My proof');
  app.input('Offline proof');
  await settle();
  assert.equal(app.ids['converter-document-title'].textContent, 'Offline proof');
  assert.equal(app.ids['converter-preview-status'].textContent, 'Text preview');
});
