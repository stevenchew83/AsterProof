const assert = require("node:assert/strict");
const {readFileSync} = require("node:fs");
const {randomUUID} = require("node:crypto");
const {test} = require("node:test");
const vm = require("node:vm");
const shared = require("../../inspinia/static/js/math-document-editor.js");

const imageID = "f4ea72eb-5e7d-4fb8-82ad-951dcceea85a";

function element(extra = {}) {
  const handlers = new Map();
  const value = Object.assign({dataset: {}, children: [], hidden: false, value: "", textContent: "", isConnected: true,
    append(...children) { children.forEach(child => { child.parent = this; this.children.push(child); }); },
    replaceChildren(...children) { this.children = []; this.append(...children); },
    contains(node) { return this === node || this.children.some(child => child.contains?.(node)); },
    setAttribute(name, data) { this[name] = name === "hidden" ? true : data; },
    addEventListener(name, handler) { const list = handlers.get(name) || []; list.push(handler); handlers.set(name, list); },
    async fire(name, event = {}) { event.target ||= this; for (const callback of handlers.get(name) || []) await callback(event); },
    querySelector() { return null; }, querySelectorAll() { return []; }, remove() {}, before() {},
  }, extra);
  return value;
}

function application({saveError, statusResult, saveURL = "/learning/save/", uploadURL = "/learning/upload/", deferredPreviews = false, uploadNonJSON = false} = {}) {
  const fields = {};
  for (const name of ["body_source", "title", "summary", "metadata", "edit_version", "editor_context", "csrfmiddlewaretoken"])
    fields[name] = element({name, value: ({body_source: "BeforeAfter", title: "Private title", summary: "", metadata: "{}", edit_version: "1", editor_context: "signed-v1", csrfmiddlewaretoken: "same-origin-csrf"})[name]});
  fields.body_source.selectionStart = fields.body_source.selectionEnd = 6;
  const preview = element(), status = element(), feedback = element(), assets = element(), reconcile = element({hidden: true});
  const checkpoint = element({dataset: {learningAction: "checkpoint"}}), submit = element({dataset: {learningAction: "submit"}});
  const form = element({dataset: {learningEditor: "", saveUrl: saveURL, previewUrl: "/learning/preview/", uploadUrl: uploadURL, statusUrl: "/learning/status/"}});
  const root = element();
  form.closest = () => root;
  form.querySelector = selector => /^\[name="([^"]+)"\]$/.test(selector) ? fields[selector.match(/^\[name="([^"]+)"\]$/)[1]] || null : selector.includes('data-learning-action="checkpoint"') ? checkpoint : null;
  root.querySelector = selector => ({"[data-learning-preview]": preview, "[data-learning-status]": status, "[data-learning-feedback]": feedback, "[data-learning-assets]": assets, "[data-learning-reconcile]": reconcile})[selector] || null;
  root.querySelectorAll = selector => selector.includes("data-learning-action") ? [checkpoint, submit] : [];
  let submits = 0;
  form.requestSubmit = action => { submits++; form.fire("submit", {submitter: action, preventDefault() {}}); };
  const document = element({readyState: "loading", activeElement: null, createElement: () => element()});
  const window = element({location: {origin: "https://asterproof.test"}, crypto: {randomUUID}});
  let finishUpload;
  const calls = [];
  const previews = [];
  const fetch = async (url, options = {}) => {
    calls.push({url, options});
    if (url.includes("preview") && deferredPreviews) return new Promise(resolve => previews.push(html => resolve({ok: true, json: async () => ({html})})));
    if (url.includes("preview")) return {ok: true, json: async () => ({html: "<p>Server preview</p>"})};
    if (url.includes("upload") && uploadNonJSON) return {ok: false, status: 500, json: async () => { throw new SyntaxError("Unexpected token '<', <!DOCTYPE"); }};
    if (url.includes("upload")) return new Promise(resolve => { finishUpload = () => resolve({ok: true, json: async () => ({id: imageID, path: "asset:" + imageID})}); });
    if (url.includes("status")) return {ok: true, json: async () => statusResult || {found: false}};
    if (saveError === "network") throw new Error("Disconnected");
    if (saveError === "html") return {ok: false, status: 500, json: async () => { throw new SyntaxError("Unexpected token '<', <!DOCTYPE"); }};
    if (saveError === "conflict") return {ok: false, status: 409, json: async () => ({error: "A newer draft exists."})};
    return {ok: true, json: async () => ({edit_version: 2, editor_context: "signed-v2"})};
  };
  class FormData { constructor() { this.values = []; } append(...values) { this.values.push(values); } }
  const mockView = class { constructor() { throw new Error("Use textarea fallback for this test"); } };
  const noop = () => null;
  const modules = {
    "@codemirror/state": {EditorState: {create: value => value}},
    "@codemirror/view": {EditorView: mockView, keymap: {of: value => value}, lineNumbers: noop},
    "@codemirror/commands": {history: noop, historyKeymap: [], defaultKeymap: []},
    "@codemirror/autocomplete": {autocompletion: noop, completionKeymap: [], closeBrackets: noop, closeBracketsKeymap: [], snippetCompletion: noop},
    "@codemirror/search": {searchKeymap: []}, "./math-document-editor.js": shared,
  };
  const context = vm.createContext({window, document, fetch, URL, FormData, setTimeout: () => 1, clearTimeout() {}, module: {exports: {}}, require: name => modules[name]});
  vm.runInContext(readFileSync(require.resolve("../../inspinia/static/js/learning-editor.js"), "utf8"), context);
  const api = context.module.exports.setup(form);
  return {api, calls, fields, form, root, status, feedback, assets, checkpoint, submit, preview, previews,
    get submits() { return submits; }, async uploadDone() { finishUpload(); await new Promise(setImmediate); }};
}

test("managed references retain descriptions and credits without inventing author permission", () => {
  const source = shared.managedImageSnippet(imageID, "A triangle ] with a marked angle");
  const metadata = shared.collectAssetMetadata(source, [{id: imageID, caption: "A synthetic diagram", credit: "Author retains rights"}]);
  assert.equal(metadata[0].alt, "A triangle ] with a marked angle");
  assert.equal(metadata[0].credit, "Author retains rights");
  const changed = shared.setImageDescription(source, imageID, "Updated description");
  assert.equal(shared.collectAssetMetadata(changed)[0].alt, "Updated description");
  assert.throws(() => shared.managedImageSnippet("../outside"));
  assert.throws(() => shared.safeEndpoint("https://other.test/save/", "https://asterproof.test"));
});

test("paste upload uses form CSRF, maps a moving caret, and requires deliberate image metadata", async () => {
  const app = application();
  const file = {type: "image/png", name: "clipboard.png"};
  const event = {clipboardData: {items: [{type: file.type, getAsFile: () => file}]}, preventDefault() { this.prevented = true; }};
  await app.fields.body_source.fire("paste", event);
  assert.ok(event.prevented);
  assert.equal(app.api.pendingUploads(), 1);
  assert.ok(app.checkpoint.disabled);
  const call = app.calls.find(value => value.url.includes("upload"));
  assert.equal(call.options.headers["X-CSRFToken"], "same-origin-csrf");
  assert.equal(call.options.credentials, "same-origin");
  app.fields.body_source.value = "Intro BeforeAfter";
  await app.fields.body_source.fire("input");
  await app.uploadDone();
  assert.equal(app.api.source(), "Intro Before![](asset:" + imageID + ")After");
  assert.equal(JSON.parse(app.fields.metadata.value).assets[0].alt, "");
  const altInput = app.assets.children[0].children[1].children[0];
  altInput.value = "An original triangle diagram";
  await altInput.fire("input");
  assert.ok(app.api.source().includes("![An original triangle diagram]"));
  assert.equal(JSON.parse(app.fields.metadata.value).assets[0].alt, "An original triangle diagram");
});

test("private autosave sends ownership version and operation identity, then updates signed context", async () => {
  const app = application();
  app.fields.body_source.value = "Changed private proof";
  await app.fields.body_source.fire("input");
  await app.api.save();
  const call = app.calls.find(value => value.url.includes("save"));
  const payload = JSON.parse(call.options.body);
  assert.equal(payload.body_source, "Changed private proof");
  assert.equal(payload.edit_version, 1);
  assert.equal(payload.editor_context, "signed-v1");
  assert.match(payload.operation_id, /^[0-9a-f-]{36}$/);
  assert.equal(app.fields.edit_version.value, 2);
  assert.equal(app.fields.editor_context.value, "signed-v2");
  assert.equal(app.status.textContent, "Saved privately");
});

test("lost save response freezes further POSTs and unrelated later receipt cannot thaw editing", async () => {
  const app = application({saveError: "network", statusResult: {found: true, edit_version: 3, saved_operation_version: 2, title: "Private title", summary: "", body_source: "Changed", metadata: {assets: []}, editor_context: "later"}});
  app.fields.body_source.value = "Changed";
  await app.fields.body_source.fire("input");
  await assert.rejects(app.api.save());
  const before = app.calls.filter(value => value.url.includes("save")).length;
  await app.api.save(); await app.api.reconcile(); await app.api.save();
  assert.equal(app.calls.filter(value => value.url.includes("save")).length, before);
  assert.equal(app.api.source(), "Changed");
  assert.match(app.feedback.textContent, /later or different version/);
});

test("stale editor responses preserve source and never automatically overwrite newer work", async () => {
  const app = application({saveError: "conflict"});
  app.fields.body_source.value = "Keep this unsaved proof";
  await app.fields.body_source.fire("input");
  await assert.rejects(app.api.save(), /newer draft/);
  assert.equal(app.api.source(), "Keep this unsaved proof");
  assert.equal(app.fields.edit_version.value, "1");
  assert.ok(app.submit.disabled);
});

test("an external autosave endpoint never receives the CSRF token or source", async () => {
  const app = application({saveURL: "https://attacker.test/save/"});
  app.fields.body_source.value = "Sensitive draft";
  await app.fields.body_source.fire("input");
  await assert.rejects(app.api.save());
  assert.ok(!app.calls.some(value => value.url.includes("attacker")));
});

test("an external upload endpoint preserves native paste and cannot leave a pending upload", async () => {
  const app = application({uploadURL: "https://attacker.test/upload/"});
  const event = {clipboardData: {items: [{type: "image/png", getAsFile: () => ({type: "image/png"})}]}, preventDefault() { this.prevented = true; }};
  await app.fields.body_source.fire("paste", event);
  assert.ok(!event.prevented);
  assert.equal(app.api.pendingUploads(), 0);
  assert.ok(!app.calls.some(value => value.url.includes("attacker")));
});

test("non-JSON upload failure preserves source and reports a plain recovery message", async () => {
  const app = application({uploadNonJSON: true});
  await app.fields.body_source.fire("paste", {clipboardData: {items: [{type: "image/png", getAsFile: () => ({type: "image/png"})}]}, preventDefault() {}});
  await new Promise(setImmediate);
  assert.equal(app.api.source(), "BeforeAfter");
  assert.equal(app.api.pendingUploads(), 0);
  assert.match(app.feedback.textContent, /Your writing is preserved/);
  assert.doesNotMatch(app.feedback.textContent, /Unexpected token|DOCTYPE/);
});

test("non-JSON autosave response remains uncertain and pauses further writes", async () => {
  const app = application({saveError: "html"});
  app.fields.body_source.value = "Preserve this proof";
  await app.fields.body_source.fire("input");
  await assert.rejects(app.api.save(), /could not be confirmed/);
  await app.api.save();
  assert.equal(app.api.source(), "Preserve this proof");
  assert.equal(app.calls.filter(value => value.url.includes("save")).length, 1);
  assert.doesNotMatch(app.feedback.textContent, /Unexpected token|DOCTYPE/);
  assert.ok(app.submit.disabled);
});

test("reverse-order previews retain the response matching the latest source", async () => {
  const app = application({deferredPreviews: true});
  app.fields.body_source.value = "First edit";
  const older = app.api.render();
  app.fields.body_source.value = "Latest edit";
  const latest = app.api.render();
  app.previews[2]("<p>Latest preview</p>");
  await latest;
  app.previews[1]("<p>Stale preview</p>");
  await older;
  assert.equal(app.preview.innerHTML, "<p>Latest preview</p>");
  app.previews[0]("<p>Initial preview</p>");
  await new Promise(setImmediate);
  assert.equal(app.preview.innerHTML, "<p>Latest preview</p>");
});

test("a confirmed exact receipt thaws saving while preserving newer unsaved local text", async () => {
  const app = application({saveError: "network", statusResult: {found: true, edit_version: 2, saved_operation_version: 2,
    title: "Private title", summary: "", body_source: "Confirmed proof", metadata: {assets: []}, editor_context: "signed-v2"}});
  app.fields.body_source.value = "Confirmed proof";
  await app.fields.body_source.fire("input");
  await assert.rejects(app.api.save());
  app.fields.body_source.value = "Later local proof";
  await app.fields.body_source.fire("input");
  await app.api.reconcile();
  assert.equal(app.api.source(), "Later local proof");
  assert.equal(app.fields.editor_context.value, "signed-v2");
  assert.equal(app.status.textContent, "Unsaved changes");
  assert.ok(!app.submit.disabled);
});

test("checkpoint waits for uploads that start while its autosave is in flight", async () => {
  const app = application();
  app.fields.body_source.value = "Changed before checkpoint";
  await app.fields.body_source.fire("input");
  const submit = app.form.fire("submit", {submitter: app.checkpoint, preventDefault() {}});
  await app.fields.body_source.fire("paste", {clipboardData: {items: [{type: "image/png", getAsFile: () => ({type: "image/png"})}]}, preventDefault() {}});
  await submit;
  assert.equal(app.submits, 0);
  assert.equal(app.api.pendingUploads(), 1);
  assert.ok(app.checkpoint.disabled);
  await app.uploadDone();
  assert.ok(app.api.source().includes("asset:" + imageID));
});

test("simultaneous checkpoint clicks share one preparation and one native submission", async () => {
  const app = application();
  app.fields.body_source.value = "Changed before checkpoint";
  await app.fields.body_source.fire("input");
  const event = {submitter: app.checkpoint, preventDefault() {}};
  await Promise.all([app.form.fire("submit", {...event}), app.form.fire("submit", {...event})]);
  assert.equal(app.submits, 1);
  assert.equal(app.calls.filter(value => value.url.includes("save")).length, 1);
});

test("receipt comparison ignores object key order while preserving nested values and array order", async () => {
  const original = {content_pack: {version: 1, key: "pilot"}, concepts: [{id: "am-gm", role: "primary"}], assets: []};
  const returned = {assets: [], concepts: [{role: "primary", id: "am-gm"}], content_pack: {key: "pilot", version: 1}};
  assert.equal(shared.canonicalJSON(original), shared.canonicalJSON(returned));
  assert.notEqual(shared.canonicalJSON({values: [1, 2]}), shared.canonicalJSON({values: [2, 1]}));
  assert.notEqual(shared.canonicalJSON(original), shared.canonicalJSON({...returned, content_pack: {key: "pilot", version: 2}}));
  const app = application({saveError: "network", statusResult: {found: true, edit_version: 2, saved_operation_version: 2,
    title: "Private title", summary: "", body_source: "Confirmed proof", metadata: returned, editor_context: "signed-v2"}});
  app.fields.metadata.value = JSON.stringify(original);
  app.fields.body_source.value = "Confirmed proof";
  await app.fields.body_source.fire("input");
  await assert.rejects(app.api.save());
  await app.api.reconcile();
  assert.equal(app.fields.editor_context.value, "signed-v2");
  assert.ok(!app.submit.disabled);
});
