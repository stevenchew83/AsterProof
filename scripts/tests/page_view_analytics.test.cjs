const assert = require('node:assert/strict');
const {readFileSync} = require('node:fs');
const {test} = require('node:test');
const vm = require('node:vm');

const template = readFileSync(require.resolve('../../inspinia/templates/pages/page-view-analytics.html'), 'utf8');
const source = [...template.matchAll(/<script>([\s\S]*?)<\/script>/g)].at(-1)[1];
const path = '/dashboard/problem-statements/?q=Geometry&topic=Algebra';

function dashboard({clipboard = true, reject = false, fallback = true} = {}) {
  const timers = [];
  const copied = [];
  let removed = false;
  function element(attrs = {}) {
    const classes = new Set(['text-muted', 'btn-outline-secondary']);
    return {value: '30d', textContent: '', innerHTML: '<i class="ti ti-copy"></i>', handlers: {},
      getAttribute: name => attrs[name], setAttribute: (name, value) => { attrs[name] = value; },
      addEventListener(event, handler) { this.handlers[event] = handler; },
      classList: {add: value => classes.add(value), remove: value => classes.delete(value),
        toggle: (value, enabled) => enabled ? classes.add(value) : classes.delete(value)},
      hasClass: value => classes.has(value),
    };
  }
  const button = element({'data-page-view-path':path, 'aria-label':'Copy path'});
  const range = element();
  const dates = element();
  const start = element();
  const end = element();
  const status = element();
  const elements = {'page-view-range':range, 'page-view-custom-dates':dates, 'page-view-start':start,
    'page-view-end':end, 'page-view-copy-status':status};
  vm.runInNewContext(source, {
    document: {getElementById: id => elements[id], querySelectorAll: () => [button],
      createElement: () => ({style:{}, setAttribute() {}, select() {}}),
      body: {appendChild() {}, removeChild() { removed = true; }}, execCommand: () => fallback},
    window: {setTimeout: fn => timers.push(fn)},
    navigator: clipboard ? {clipboard:{writeText: text => {
      copied.push(text);
      return reject ? Promise.reject(new Error('Denied')) : Promise.resolve();
    }}} : {},
  });
  return {button, range, dates, start, end, status, timers, copied, removed: () => removed};
}

test('custom date controls open and manual date changes select the custom range', () => {
  const app = dashboard();
  app.range.handlers.change();
  assert.notEqual(app.dates.open, true);
  app.range.value = 'custom';
  app.range.handlers.change();
  assert.equal(app.dates.open, true);
  for (const input of [app.start, app.end]) {
    app.range.value = '7d';
    input.handlers.change();
    assert.equal(app.range.value, 'custom');
  }
});

test('copy keeps the exact path and announces success before restoring the action', async () => {
  const app = dashboard();
  await app.button.handlers.click();
  assert.deepEqual(app.copied, [path]);
  assert.equal(app.status.textContent, 'Path copied.');
  assert.equal(app.button.getAttribute('aria-label'), 'Path copied');
  assert.equal(app.button.disabled, false);
  app.timers[0]();
  assert.equal(app.button.getAttribute('aria-label'), 'Copy path');
  assert.ok(app.button.hasClass('btn-outline-secondary'));
});

test('clipboard denial reports failure and leaves the copy action usable', async () => {
  const app = dashboard({reject:true});
  await app.button.handlers.click();
  assert.ok(app.status.textContent.includes('Could not copy'));
  assert.ok(app.status.hasClass('text-danger'));
  assert.equal(app.button.getAttribute('aria-label'), 'Copy path');
  assert.equal(app.button.disabled, false);
  assert.equal(app.timers.length, 0);
});

test('legacy clipboard fallback cleans up and does not report false success', async () => {
  for (const fallback of [true, false]) {
    const app = dashboard({clipboard:false, fallback});
    await app.button.handlers.click();
    assert.equal(app.removed(), true);
    assert.equal(app.status.textContent === 'Path copied.', fallback);
    assert.equal(app.button.disabled, false);
  }
});
