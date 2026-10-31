const assert = require('node:assert/strict');
const {readFileSync} = require('node:fs');
const {test} = require('node:test');
const vm = require('node:vm');

function element(extra = {}) {
  const handlers = {};
  return Object.assign({
    dataset: {}, textContent: '', value: '', hidden: false,
    classList: {contains: () => false, add() {}, remove() {}},
    addEventListener(name, handler) { handlers[name] = handler; },
    fire(name, event) { handlers[name]?.(event); },
    querySelectorAll() { return []; },
    closest() { return null; },
    setAttribute() {},
    dispatchEvent() {},
  }, extra);
}

function editor({format = 'latex', csrf = 'form-csrf', uploadError = false} = {}) {
  const ids = {};
  const get = id => ids[id] ||= element();
  const buttons = [element(), element()];
  const form = get('solution-editor-form');
  form.querySelector = selector => selector.includes('csrfmiddlewaretoken') ? {value: csrf} : null;
  const document = element({
    getElementById: get,
    querySelectorAll: selector => selector.startsWith('button[type="submit"]') ? buttons : [],
  });
  let finish;
  const calls = [];
  const fetch = (url, options) => {
    calls.push({url, options});
    return new Promise(resolve => { finish = () => resolve({
      ok: !uploadError, status: uploadError ? 403 : 200,
      headers: {get: () => 'application/json'},
      json: async () => uploadError ? {error: 'Upload rejected.'} : {
        path: 'solution_body_images/' + 'a'.repeat(32) + '.png',
      },
    }); });
  };
  const window = element({
    ASTERPROOF_SOLUTION_MEDIA: {uploadUrl: '/body-images/'},
    matchMedia: () => element({matches: true}),
    clearTimeout() {}, setTimeout() {},
  });
  class FormData {
    constructor() { this.values = []; }
    append(...args) { this.values.push(args); }
    entries() { return this.values.values(); }
  }
  const context = vm.createContext({window, document, FormData, fetch, URL,
    Event: class {}, CustomEvent: class {}});
  vm.runInContext(readFileSync(require.resolve('../../inspinia/static/js/solution-latex-hybrid.js'), 'utf8'), context);
  // Startup rendering is independent of clipboard handling; leave MathJax loading.
  window.AsterProofSolutionLatex.mathJaxReady = () => new Promise(() => {});
  vm.runInContext(readFileSync(require.resolve('../../inspinia/static/js/solution-editor.js'), 'utf8'), context);
  const textarea = element({
    tagName: 'TEXTAREA', name: 'blocks-1-body_source', value: 'BeforeAfter',
    selectionStart: 6, selectionEnd: 6,
    closest: () => ({querySelector: () => ({value: format})}),
  });
  function paste(clipboardData) {
    const event = {target: textarea, clipboardData, prevented: false,
      preventDefault() { this.prevented = true; }};
    form.fire('paste', event);
    return event;
  }
  async function complete() {
    finish();
    await new Promise(setImmediate);
  }
  return {paste, complete, calls, textarea, buttons, document, form, get};
}

const image = {type: 'image/png', name: 'clipboard.png'};
const clipboard = {items: [{type: 'image/png', getAsFile: () => image}]};

test('image paste uploads with form CSRF, inserts LaTeX at the caret, and blocks saving until done', async () => {
  const app = editor();
  assert.ok(app.paste(clipboard).prevented);
  assert.equal(app.calls.length, 1);
  const {url, options} = app.calls[0];
  assert.equal(url, '/body-images/');
  assert.equal(options.headers['X-CSRFToken'], 'form-csrf');
  assert.equal(options.credentials, 'same-origin');
  assert.equal(options.body.values[0][1], image);
  assert.ok(app.buttons.every(button => button.disabled));
  const submit = {preventDefault() { this.prevented = true; }};
  app.form.fire('submit', submit);
  assert.ok(submit.prevented);
  await app.complete();
  assert.equal(app.textarea.value, 'Before\\includegraphics[width=0.9\\linewidth]{solution_body_images/' + 'a'.repeat(32) + '.png}After');
  assert.ok(app.buttons.every(button => !button.disabled));
});

test('plain text and non-LaTeX blocks retain native paste', () => {
  const app = editor();
  assert.equal(app.paste({items: [{type: 'text/plain'}]}).prevented, false);
  assert.equal(app.calls.length, 0);
  const plain = editor({format: 'plain_text'});
  assert.equal(plain.paste(clipboard).prevented, false);
  assert.equal(plain.calls.length, 0);
});

test('clipboard file fallback works and upload errors keep the source and re-enable saving', async () => {
  const app = editor({uploadError: true});
  assert.ok(app.paste({files: [image]}).prevented);
  await app.complete();
  assert.equal(app.textarea.value, 'BeforeAfter');
  assert.equal(app.get('solution-upload-feedback').hidden, false);
  assert.equal(app.get('solution-upload-feedback').textContent, 'Upload rejected.');
  assert.ok(app.buttons.every(button => !button.disabled));
});

test('Ctrl+S does not submit a collapsed problem-page editor', () => {
  const app = editor();
  app.form.closest = () => ({});
  let prevented = false;
  app.document.fire('keydown', {ctrlKey: true, key: 's', preventDefault() { prevented = true; }});
  assert.equal(prevented, false);
});
