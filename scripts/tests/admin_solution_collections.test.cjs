const assert = require('node:assert/strict');
const {test} = require('node:test');
const {readFileSync} = require('node:fs');
const vm = require('node:vm');
const {validRefs, basketURL, loadBasket, seedDraft} = require('../../inspinia/static/js/admin-solution-collections.js');
const first = '1:11111111-1111-4111-8111-111111111111';
const second = '2:22222222-2222-4222-8222-222222222222';

test('selection URLs preserve order, filters and paging without accumulating refs', () => {
  const href = basketURL('https://example.test/solutions/admin/shared/?q=geometry&page=2&share=' + first, [second, first], 'flow');
  const url = new URL(href);
  assert.deepEqual(url.searchParams.getAll('share'), [second, first]);
  assert.equal(url.searchParams.get('q'), 'geometry');
  assert.equal(url.searchParams.get('page'), '2');
  assert.deepEqual(new URL(basketURL(href, [], 'flow')).searchParams.getAll('share'), []);
});
test('latest tab basket overrides a historical URL, and explicit clear stays empty', () => {
  const values = new Map();
  const storage = {getItem: key => values.has(key) ? values.get(key) : null};
  assert.deepEqual(loadBasket(storage, 'admin1:flow1', [first]), [first]);
  values.set('admin1:flow1', JSON.stringify([first, second]));
  assert.deepEqual(loadBasket(storage, 'admin1:flow1', [first]), [first, second]);
  assert.deepEqual(loadBasket(storage, 'admin2:flow1', []), []);
  assert.deepEqual(loadBasket(storage, 'admin1:flow2', []), []);
  values.set('admin1:flow1', '[]');
  assert.deepEqual(loadBasket(storage, 'admin1:flow1', [first, second]), []);
});
test('malformed, duplicate, and over-limit stored references cannot hydrate a basket', () => {
  assert.equal(validRefs([first, second]), true);
  for (const value of [[first, first], ['1:invalid'], ['9999999999999999999:' + first.split(':')[1]], [1], {}, Array(21).fill(first)]) {
    assert.equal(validRefs(value), false);
    assert.throws(() => loadBasket({getItem: () => JSON.stringify(value)}, 'key', []));
  }
  assert.throws(() => loadBasket({getItem: () => '{broken'}, 'key', []));
  assert.throws(() => loadBasket({getItem: () => { throw new Error('Storage denied'); }}, 'key', [first]));
});

function pickerDocument(values, initialHref, initialRefs = []) {
  let currentRefs = initialRefs;
  let replaced;
  const handlers = {};
  const notice = {};
  const root = {
    dataset: {curatedUser: '7', curatedFlow: 'same-flow'},
    querySelector: () => notice,
    querySelectorAll: selector => selector === '[data-collection-item]' ?
      currentRefs.map(collectionItem => ({dataset: {collectionItem}})) : [],
    addEventListener: (name, handler) => { handlers[name] = handler; },
  };
  const window = {
    location: {href: initialHref, replace: href => { replaced = href; }},
    history: {replaceState: (_state, _title, href) => { window.location.href = href; }},
    sessionStorage: {getItem: key => values.has(key) ? values.get(key) : null, setItem: (key, value) => values.set(key, value)},
    addEventListener: (name, handler) => { handlers[name] = handler; },
  };
  const document = {querySelectorAll: selector => selector === '[data-curated-selection]' ? [root] : []};
  vm.runInNewContext(readFileSync(require.resolve('../../inspinia/static/js/admin-solution-collections.js'), 'utf8'), {document, window, URL, Set, BigInt});
  return {window, handlers, notice, replaced: () => replaced, change: refs => { currentRefs = refs; handlers.collectionchange(); }};
}

test('an empty first page gets a flow URL before navigation and Back reload hydrates the latest basket', () => {
  const storage = new Map();
  const page1 = pickerDocument(storage, 'https://example.test/solutions/admin/shared/');
  const historicalURL = page1.window.location.href;
  assert.equal(new URL(historicalURL).searchParams.get('flow'), 'same-flow');
  const page2 = pickerDocument(storage, historicalURL + '&page=2');
  page2.change([second]);
  const back = pickerDocument(storage, historicalURL);
  assert.deepEqual(new URL(back.replaced()).searchParams.getAll('share'), [second]);
});

test('clearing the basket prevents browser history from restoring old references', () => {
  const storage = new Map();
  const picker = pickerDocument(storage, 'https://example.test/solutions/admin/shared/', [first, second]);
  picker.change([]);
  const restored = pickerDocument(storage, 'https://example.test/solutions/admin/shared/', [first, second]);
  assert.deepEqual(new URL(restored.replaced()).searchParams.getAll('share'), []);
});

test('a fresh builder handoff replaces an old draft order while Back and reload retain it', () => {
  const values = new Map([['draft', JSON.stringify([second, first])]]);
  const storage = {getItem: key => values.get(key) ?? null, setItem: (key, value) => values.set(key, value)};
  seedDraft(storage, 'draft', [first], 'back_forward');
  assert.deepEqual(loadBasket(storage, 'draft', []), [second, first]);
  seedDraft(storage, 'draft', [first], 'reload');
  assert.deepEqual(loadBasket(storage, 'draft', []), [second, first]);
  seedDraft(storage, 'draft', [first], 'navigate');
  assert.deepEqual(loadBasket(storage, 'draft', []), [first]);
});

function restoringBuilder() {
  let order = [first, second];
  let resolveFetch;
  const handlers = {};
  const review = {disabled: false};
  const feedback = {};
  const values = new Map([['asterproof.curated-draft-order:7:flow:new:', JSON.stringify([second, first])]]);
  const form = {
    dataset: {curatedUser: '7', curatedFlow: 'flow', curatedCollection: 'new', curatedRevision: '', selectionUrl: '/solutions/admin/collections/selection/'},
    querySelectorAll: () => order.map(collectionItem => ({dataset: {collectionItem}})),
    querySelector: selector => selector.includes('button') ? review : feedback,
    addEventListener: (name, handler) => { handlers[name] = handler; },
    dispatchEvent: event => { order = event.detail.map(row => row.ref); handlers.collectionchange(); },
  };
  const window = {
    sessionStorage: {getItem: key => values.get(key) ?? null, setItem: (key, value) => values.set(key, value)},
    performance: {getEntriesByType: () => [{type: 'back_forward'}]},
    location: {href: 'https://example.test/solutions/admin/collections/new/?flow=flow'},
    history: {replaceState() {}},
    addEventListener: (name, handler) => { handlers[name] = handler; },
  };
  const appendForm = {addEventListener: (_name, handler) => { handlers.appendSubmit = handler; }};
  const document = {querySelector: () => appendForm, querySelectorAll: selector => selector === '[data-curated-builder]' ? [form] : []};
  class CustomEvent { constructor(type, options) { this.type = type; this.detail = options.detail; } }
  vm.runInNewContext(readFileSync(require.resolve('../../inspinia/static/js/admin-solution-collections.js'), 'utf8'), {
    document, window, URL, Set, BigInt, CustomEvent, AbortController, setTimeout, clearTimeout,
    fetch: () => new Promise(resolve => { resolveFetch = resolve; }),
  });
  return {handlers, review, feedback, order: () => order, resolve: response => resolveFetch(response)};
}

test('pending or failed history hydration blocks Search and paging from submitting stale references', async () => {
  const builder = restoringBuilder();
  const restore = builder.handlers.pageshow();
  let blocked = 0;
  builder.handlers.submit({preventDefault: () => { blocked += 1; }});
  assert.equal(blocked, 1);
  builder.handlers.appendSubmit({preventDefault: () => { blocked += 1; }});
  assert.equal(blocked, 2);
  assert.equal(builder.review.disabled, true);
  builder.resolve({ok: false});
  await restore;
  builder.handlers.submit({preventDefault: () => { blocked += 1; }});
  builder.handlers.appendSubmit({preventDefault: () => { blocked += 1; }});
  assert.equal(blocked, 4);
  assert.equal(builder.review.disabled, true);
  assert.match(builder.feedback.textContent, /Reload/);
});

test('successful metadata hydration restores order and allows a separate user submission', async () => {
  const builder = restoringBuilder();
  const restore = builder.handlers.pageshow();
  builder.resolve({ok: true, json: async () => ({shares: [{ref: second}, {ref: first}]})});
  await restore;
  assert.deepEqual(Array.from(builder.order()), [second, first]);
  assert.equal(builder.review.disabled, false);
  let blocked = false;
  builder.handlers.submit({preventDefault: () => { blocked = true; }});
  assert.equal(blocked, false);
});
