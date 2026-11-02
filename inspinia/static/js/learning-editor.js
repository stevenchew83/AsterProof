/* Private Markdown/LaTeX authoring; saving never publishes or changes learner progress. */
"use strict";

const {EditorState} = require("@codemirror/state");
const {EditorView, keymap, lineNumbers} = require("@codemirror/view");
const {history, historyKeymap, defaultKeymap} = require("@codemirror/commands");
const {autocompletion, completionKeymap, closeBrackets, closeBracketsKeymap, snippetCompletion} = require("@codemirror/autocomplete");
const {searchKeymap} = require("@codemirror/search");
const shared = require("./math-document-editor.js");
const instances = new WeakMap();

function completion(context) {
  if (context.view?.composing) return null;
  const spec = shared.completionSpec(context.state.doc.toString(), context.pos);
  if (!spec || spec.mode !== "command") return null;
  const options = spec.names.filter(name => name.startsWith(spec.prefix) && !["section", "subsection", "paragraph", "begin", "end"].includes(name)).map(name => shared.snippets[name] ? snippetCompletion(shared.snippets[name], {label: "\\" + name, type: "function"}) : {label: "\\" + name, apply: "\\" + name, type: "keyword"});
  return {from: spec.from, to: spec.to, options, filter: false};
}

function setup(form) {
  if (instances.has(form)) return instances.get(form);
  const textarea = form.querySelector('[name="body_source"]');
  if (!textarea) return null;
  const scope = form.closest("[data-learning-workspace]") || form;
  const preview = scope.querySelector("[data-learning-preview]");
  const status = scope.querySelector("[data-learning-status]");
  const feedback = scope.querySelector("[data-learning-feedback]");
  const assetsHost = scope.querySelector("[data-learning-assets]");
  const metadataField = form.querySelector('[name="metadata"]');
  const csrf = form.querySelector('[name="csrfmiddlewaretoken"]')?.value;
  const versionField = form.querySelector('[name="edit_version"]');
  const contextField = form.querySelector('[name="editor_context"]');
  let view, previous = textarea.value, saveTimer, previewTimer, previewGeneration = 0, saveFlight, frozen = false, submitting = false, submissionFlight = false;
  let pendingSave = null, saved = "";
  const uploads = new Map();
  const endpoint = key => shared.safeEndpoint(form.dataset[key], window.location.origin);
  const show = message => { if (feedback) { feedback.textContent = message || ""; feedback.hidden = !message; } };
  const source = () => view ? view.state.doc.toString() : textarea.value;
  function metadata() { try { const value = JSON.parse(metadataField?.value || "{}"); return value && typeof value === "object" && !Array.isArray(value) ? value : {}; } catch (_) { return {}; } }
  function synchronizeAssets() {
    if (!metadataField) return;
    const value = metadata(); value.assets = shared.collectAssetMetadata(source(), value.assets);
    metadataField.value = JSON.stringify(value);
  }
  function payload() {
    synchronizeAssets();
    return {title: form.querySelector('[name="title"]')?.value || "", summary: form.querySelector('[name="summary"]')?.value || "", body_source: source(), metadata: metadata()};
  }
  function dirty() { return JSON.stringify(payload()) !== saved; }
  function state(label) {
    if (status) status.textContent = label || (uploads.size ? "Uploading image…" : frozen ? "Save paused · your writing is preserved" : dirty() ? "Unsaved changes" : "Saved privately");
    scope.querySelectorAll('[data-learning-action="checkpoint"], [data-learning-action="submit"]').forEach(button => { button.disabled = uploads.size > 0 || frozen || submissionFlight; });
  }
  function assetControls() {
    if (!assetsHost) return;
    synchronizeAssets();
    const values = metadata().assets || [];
    const active = document.activeElement;
    if (active && assetsHost.contains(active)) return;
    assetsHost.replaceChildren();
    for (const asset of values) {
      const row = document.createElement("fieldset"); row.className = "border rounded p-2 mb-2";
      const legend = document.createElement("legend"); legend.className = "fs-sm fw-semibold"; legend.textContent = "Image details"; row.append(legend);
      for (const [key, label, maximum] of [["alt", "Image description (required)", 500], ["caption", "Caption", 1000], ["credit", "Source credit / permission", 500]]) {
        const wrapper = document.createElement("label"); wrapper.className = "form-label d-block"; wrapper.textContent = label;
        const input = document.createElement("input"); input.type = "text"; input.className = "form-control"; input.value = asset[key]; input.maxLength = maximum;
        input.addEventListener("input", () => {
          const current = metadata(); const entry = current.assets.find(value => value.id === asset.id);
          if (entry) {
            entry[key] = input.value; metadataField.value = JSON.stringify(current);
            if (key === "alt") {
              const updated = shared.setImageDescription(source(), asset.id, input.value);
              replaceSource(updated);
            }
            changed();
          }
        });
        wrapper.append(input); row.append(wrapper);
      }
      assetsHost.append(row);
    }
    assetsHost.hidden = !values.length;
  }
  function sync() { if (view) textarea.value = view.state.doc.toString(); }
  function replaceSource(updated) {
    if (view) view.dispatch({changes: {from: 0, to: view.state.doc.length, insert: updated}});
    else {
      const original = textarea.value;
      for (const bookmark of uploads.values()) {
        bookmark.from = shared.mapOffset(bookmark.from, original, updated);
        bookmark.to = shared.mapOffset(bookmark.to, original, updated);
      }
      textarea.value = previous = updated;
    }
  }
  function changed() {
    sync(); state();
    clearTimeout(saveTimer); clearTimeout(previewTimer);
    previewTimer = setTimeout(render, 350);
    if (!frozen) saveTimer = setTimeout(() => save().catch(() => {}), 1100);
  }
  async function request(url, body) {
    const response = await fetch(url, {method: "POST", credentials: "same-origin", headers: {"X-CSRFToken": csrf || "", "Content-Type": "application/json"}, body: JSON.stringify(body)});
    const data = await responseData(response);
    if (!response.ok) { const error = new Error(data.error || data.message || "The request could not be saved. Your writing is preserved."); error.status = response.status; throw error; }
    return data;
  }
  async function responseData(response) {
    try {
      const value = await response.json();
      if (!value || typeof value !== "object" || Array.isArray(value)) throw new Error("Invalid response");
      return value;
    }
    catch (_) {
      const error = new Error("The server response could not be confirmed. Your writing is preserved.");
      error.status = response.status; error.uncertain = true;
      throw error;
    }
  }
  async function render() {
    if (!preview || !form.dataset.previewUrl) return;
    assetControls();
    const generation = ++previewGeneration;
    try {
      const result = await request(endpoint("previewUrl"), payload());
      if (generation !== previewGeneration) return;
      window.MathJax?.typesetClear?.([preview]);
      // Only the same-origin, server-sanitised preview response enters this surface.
      preview.innerHTML = result.html;
      if (window.AsterProofLearningMath) await window.AsterProofLearningMath.typeset(preview);
    } catch (error) { if (generation === previewGeneration) show(error.message || "Preview is unavailable. Your source is preserved."); }
  }
  async function save() {
    clearTimeout(saveTimer);
    if (saveFlight) { await saveFlight; if (dirty() && !frozen) return save(); return; }
    if (frozen || uploads.size || !dirty() || !form.dataset.saveUrl) return;
    const body = payload();
    const operation = shared.operationID(window.crypto);
    pendingSave = {body, operation};
    saveFlight = (async () => {
      try {
        state("Saving privately…");
        const result = await request(endpoint("saveUrl"), {...body, operation_id: operation, edit_version: Number(versionField?.value || 0), editor_context: contextField?.value || ""});
        if (versionField) versionField.value = result.edit_version;
        if (contextField) contextField.value = result.editor_context;
        saved = JSON.stringify(body); pendingSave = null; show("");
      } catch (error) {
        frozen = error.uncertain || !error.status || [401, 403, 409].includes(error.status);
        show(error.status ? error.message : "The save result is unknown. Check the saved version before trying again; your writing is still here.");
        const button = scope.querySelector("[data-learning-reconcile]"); if (button) button.hidden = !frozen;
        throw error;
      } finally { saveFlight = null; state(); }
    })();
    return saveFlight;
  }
  async function reconcile() {
    if (!pendingSave || !form.dataset.statusUrl) return;
    try {
      const url = new URL(endpoint("statusUrl")); url.searchParams.set("operation_id", pendingSave.operation);
      const response = await fetch(url.href, {credentials: "same-origin", cache: "no-store"});
      const result = await response.json();
      if (!response.ok || !result.found) { show("No confirmed result is available. Keep this source and compare the saved draft before another save."); return; }
      const original = pendingSave.body;
      const sameBody = result.body_source === original.body_source && result.title === original.title && result.summary === original.summary && shared.canonicalJSON(result.metadata) === shared.canonicalJSON(original.metadata);
      if (Number(result.edit_version) !== Number(result.saved_operation_version) || !sameBody) {
        show("The saved draft has a later or different version. Keep this source and compare or reload; automatic saving remains paused.");
        return;
      }
      if (versionField) versionField.value = result.edit_version;
      if (contextField) contextField.value = result.editor_context;
      saved = JSON.stringify(pendingSave.body); pendingSave = null; frozen = false;
      show("The prior save was confirmed. Any later local edits remain unsaved."); state();
      scope.querySelector("[data-learning-reconcile]")?.setAttribute("hidden", "");
      if (dirty()) changed();
    } catch (_) { show("The saved result cannot be checked yet. Your writing is preserved."); }
  }
  function paste(event) {
    const clipboard = event.clipboardData;
    const item = clipboard && Array.from(clipboard.items || []).find(value => value.type.startsWith("image/"));
    const file = item?.getAsFile() || clipboard && Array.from(clipboard.files || []).find(value => value.type.startsWith("image/"));
    if (!file || !form.dataset.uploadUrl) return false;
    let uploadURL;
    try { uploadURL = endpoint("uploadUrl"); }
    catch (error) { show(error.message); return false; }
    event.preventDefault();
    const selected = view ? view.state.selection.main : {from: textarea.selectionStart, to: textarea.selectionEnd};
    const bookmark = {from: selected.from, to: selected.to, selected: source().slice(selected.from, selected.to)};
    const identity = Symbol("upload"); uploads.set(identity, bookmark); state(); show("");
    const body = new FormData(); body.append("image", file, file.name || "clipboard.png");
    fetch(uploadURL, {method: "POST", credentials: "same-origin", headers: {"X-CSRFToken": csrf || ""}, body})
      .then(async response => { const value = await responseData(response); if (!response.ok) throw new Error(value.error || "The image could not be uploaded. Your writing is preserved."); return value; })
      .then(value => {
        const insertion = shared.managedImageSnippet(value.id);
        const range = shared.uploadReplacementRange(bookmark, source());
        if (view) view.dispatch({changes: {...range, insert: insertion}, userEvent: "input.paste"});
        else { replaceSource(source().slice(0, range.from) + insertion + source().slice(range.to)); changed(); }
        const current = metadata(); current.assets = [...(current.assets || []).filter(asset => asset.id !== value.id), {id: value.id, alt: "", caption: "", credit: ""}];
        if (metadataField) metadataField.value = JSON.stringify(current);
        assetControls(); show("Add an image description before checkpointing or submitting. Your image is private.");
      }).catch(error => show(error.message || "Image upload failed. Your writing is preserved."))
      .finally(() => { uploads.delete(identity); state(); changed(); });
    return true;
  }
  try {
    const host = document.createElement("div"); host.className = "learning-source-editor"; textarea.before(host);
    view = new EditorView({parent: host, state: EditorState.create({doc: textarea.value, extensions: [lineNumbers(), history(), closeBrackets(), EditorView.lineWrapping,
      autocompletion({override: [completion]}), keymap.of([...closeBracketsKeymap, ...completionKeymap, ...defaultKeymap, ...historyKeymap, ...searchKeymap]),
      EditorView.contentAttributes.of({"aria-label": "Lecture source: Markdown with LaTeX", spellcheck: "true"}),
      EditorView.domEventHandlers({paste(event) { return paste(event); }}),
      EditorView.updateListener.of(update => { if (update.docChanged) { for (const bookmark of uploads.values()) shared.mapUploadBookmark(bookmark, update.changes); changed(); } }),
    ]})});
    textarea.hidden = true;
  } catch (_) { view = null; scope.querySelector(".learning-source-editor")?.remove(); textarea.hidden = false; }
  textarea.addEventListener("input", () => { if (!view) { for (const bookmark of uploads.values()) { bookmark.from = shared.mapOffset(bookmark.from, previous, textarea.value); bookmark.to = shared.mapOffset(bookmark.to, previous, textarea.value); } previous = textarea.value; changed(); } });
  textarea.addEventListener("paste", event => { if (!view) paste(event); });
  form.addEventListener("input", event => { if (event.target !== textarea && !assetsHost?.contains(event.target)) changed(); });
  form.addEventListener("change", changed);
  form.addEventListener("submit", async event => {
    sync();
    if (submitting) return;
    event.preventDefault();
    if (submissionFlight || uploads.size || frozen) { state(); return; }
    submissionFlight = true; state();
    const action = event.submitter;
    try {
      await save();
      if (uploads.size || frozen) return;
      synchronizeAssets();
      if (form.checkValidity && !form.checkValidity()) { form.reportValidity?.(); return; }
      let operation = form.querySelector('[name="operation_id"]');
      if (!operation) { operation = document.createElement("input"); operation.type = "hidden"; operation.name = "operation_id"; form.append(operation); }
      operation.value = shared.operationID(window.crypto);
      submissionFlight = false; state();
      submitting = true;
      form.requestSubmit(action);
    } catch (_) { submitting = false; }
    finally { submissionFlight = false; state(); }
  });
  scope.querySelector("[data-learning-reconcile]")?.addEventListener("click", reconcile);
  scope.querySelectorAll("[data-editor-view]").forEach(button => button.addEventListener("click", () => {
    scope.dataset.view = button.dataset.editorView;
    scope.querySelectorAll("[data-editor-view]").forEach(value => value.setAttribute("aria-pressed", String(value === button)));
    if (button.dataset.editorView === "preview") render();
    view?.requestMeasure();
  }));
  form.addEventListener("keydown", event => { if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === "s") { event.preventDefault(); const button = form.querySelector('[data-learning-action="checkpoint"]'); if (button) form.requestSubmit(button); } });
  window.addEventListener("beforeunload", event => { if (!submitting && (dirty() || uploads.size)) { event.preventDefault(); event.returnValue = ""; } });
  saved = JSON.stringify(payload()); assetControls(); state(); render();
  const api = {source, save, render, reconcile, pendingUploads: () => uploads.size}; instances.set(form, api); return api;
}

function init() { document.querySelectorAll("form[data-learning-editor]").forEach(setup); }
if (typeof window !== "undefined") {
  window.AsterProofLearningEditors = {init};
  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", init, {once: true}); else init();
}
module.exports = {completion, setup};
