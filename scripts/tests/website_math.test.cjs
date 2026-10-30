const assert = require('node:assert/strict');
const {readFileSync} = require('node:fs');
const {test} = require('node:test');
const vm = require('node:vm');

const source = readFileSync(require.resolve('../../inspinia/static/js/website-math.js'), 'utf8');

function page({lazy = false, editor = true, intersection = true} = {}) {
  const scripts = [], events = [], handlers = new Map(), observers = [];
  const preview = {};
  const root = {
    addEventListener(name, handler) { handlers.set(name, handler); },
    querySelector() { return preview; },
  };
  class Observer {
    constructor(callback) { this.callback = callback; observers.push(this); }
    observe(target) { this.target = target; }
    disconnect() { this.disconnected = true; }
  }
  const window = {IntersectionObserver: intersection ? Observer : undefined};
  const document = {
    currentScript: {hasAttribute: () => lazy, dataset: {
      mathSrc: 'https://cdn.example/tex-mml-chtml.js', previewMathSrc: 'https://cdn.example/startup.js',
    }},
    querySelector: () => editor ? root : null,
    createElement: () => ({}),
    head: {appendChild: script => scripts.push(script)},
    dispatchEvent: event => events.push(event.type),
  };
  vm.runInNewContext(source, {window, document, Event, IntersectionObserver: Observer});
  function startup() {
    let finish;
    window.MathJax.startup.promise = new Promise(resolve => { finish = resolve; });
    return {finish, loaded: scripts[0].onload()};
  }
  return {window, scripts, events, handlers, observers, preview, startup};
}

test('the writer loads eagerly but leaves its initial typeset to the preview controller', async () => {
  const app = page();
  assert.equal(app.scripts.length, 1);
  assert.equal(app.scripts[0].src, 'https://cdn.example/startup.js');
  assert.deepEqual(Array.from(app.window.MathJax.loader.load), ['input/tex', 'input/mml', 'output/chtml', 'ui/menu']);
  assert.equal(app.window.MathJax.startup.typeset, false);
  const startup = app.startup();
  await Promise.resolve();
  assert.deepEqual(app.events, []);
  startup.finish();
  await startup.loaded;
  await app.window.AsterProofMathReady;
  assert.deepEqual(app.events, ['asterproof:math-ready']);
});

test('static mathematics pages retain automatic initial typesetting', () => {
  const app = page({editor: false});
  assert.equal(app.scripts.length, 1);
  assert.equal(app.scripts[0].src, 'https://cdn.example/tex-mml-chtml.js');
  assert.equal(app.window.MathJax.startup.typeset, true);
});

test('the homepage loads math once on use or visibility and leaves preview typesetting to its controller', () => {
  const app = page({lazy: true});
  assert.equal(app.scripts.length, 0);
  assert.equal(app.window.AsterProofMathReady, undefined);
  assert.equal(app.observers[0].target, app.preview);
  app.handlers.get('focusin')();
  app.handlers.get('input')();
  app.observers[0].callback([{isIntersecting: true}]);
  assert.equal(app.scripts.length, 1);
  assert.equal(app.window.MathJax.startup.typeset, false);
  assert.equal(app.observers[0].disconnected, true);
});

test('older browsers still load homepage mathematics without IntersectionObserver', () => {
  const app = page({lazy: true, intersection: false});
  assert.equal(app.scripts.length, 1);
  assert.equal(app.window.MathJax.startup.typeset, false);
});

test('a failed CDN request releases preview initialization into the text fallback', async () => {
  const app = page();
  app.scripts[0].onerror(new Error('offline'));
  await app.window.AsterProofMathReady;
  assert.equal(app.window.MathJax, null);
  assert.deepEqual(app.events, []);
});

test('a failed component releases preview initialization even when startup cannot finish', async () => {
  const app = page();
  const error = new Error('blocked component');
  let failStartup;
  let failDependency;
  app.window.MathJax.startup.promise = new Promise((resolve, reject) => { failStartup = reject; });
  const dependency = new Promise((resolve, reject) => { failDependency = reject; });
  app.window.MathJax.loader.ready = () => Promise.all([dependency]);
  app.window.MathJax.loader.failed(error);
  failStartup(error);
  failDependency(error);
  await app.window.AsterProofMathReady;
  await new Promise(setImmediate);
  assert.equal(app.window.MathJax, null);
  assert.deepEqual(app.events, []);
});
