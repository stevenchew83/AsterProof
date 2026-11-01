"use strict";

const {EditorState, EditorSelection, Prec} = require("@codemirror/state");
const {EditorView, keymap, lineNumbers, highlightActiveLineGutter, drawSelection} = require("@codemirror/view");
const {history, historyKeymap, defaultKeymap} = require("@codemirror/commands");
const {StreamLanguage, syntaxHighlighting, defaultHighlightStyle, bracketMatching} = require("@codemirror/language");
const {stex} = require("@codemirror/legacy-modes/mode/stex");
const {autocompletion, completionKeymap, closeBrackets, closeBracketsKeymap, snippetCompletion, nextSnippetField, prevSnippetField, completionStatus, acceptCompletion} = require("@codemirror/autocomplete");
const {searchKeymap, highlightSelectionMatches} = require("@codemirror/search");
const {ENVIRONMENTS, COMMANDS, unclosedEnvironment, imageSnippet, mapOffset, mapUploadBookmark, uploadReplacementRange} = require("./solution-document-core.js");
const {renderDocument} = require("./solution-document-preview.js");
const {createRecovery} = require("./solution-document-recovery.js");

const FIELDS = ["title", "summary", "problem_statement", "author_name", "pdf_show_author", "pdf_show_date", "pdf_show_footer"];
const instances = new WeakMap();
const language = StreamLanguage.define(stex);
const {snippets, completionSpec} = require("./math-document-editor.js");

function completions(context) {
  if (context.view && context.view.composing) return null;
  const source = context.state.doc.toString();
  const spec = completionSpec(source, context.pos);
  if (!spec) return null;
  const options = spec.names.filter(name => name.startsWith(spec.prefix)).map(name => {
    if (spec.mode === "begin") return snippetCompletion("\\begin{" + name + "}\n  ${}\n\\end{" + name + "}", {label: "\\begin{" + name + "}", type: "keyword", detail: "paired environment"});
    if (spec.mode === "end") return {label: "\\end{" + name + "}", apply: "\\end{" + name + "}", type: "keyword", detail: "close " + name};
    if (name === "begin") return snippetCompletion("\\begin{${environment}}\n  ${}\n\\end{${environment}}", {label: "\\begin", type: "keyword"});
    if (name === "end") { const nearest = unclosedEnvironment(source.slice(0, spec.from)); return {label: "\\end", apply: nearest ? "\\end{" + nearest + "}" : "\\end{}", type: "keyword"}; }
    return snippets[name] ? snippetCompletion(snippets[name], {label: "\\" + name, type: "function"}) : {label: "\\" + name, type: "keyword"};
  });
  // An environment completion consumes an existing closing brace as well.
  return {from: spec.from, to: spec.to, options, filter: false};
}

function field(form, name) {
  return Array.from(form.elements).find(element => element.name === name || element.name.endsWith("-" + name));
}

function createEditorState(doc, extensions = []) {
  // Repeated snippet fields use simultaneous selections to keep their text linked.
  return EditorState.create({doc, extensions: [EditorState.allowMultipleSelections.of(true), extensions]});
}

function setup(root) {
  if (instances.has(root)) return instances.get(root);
  const form = root.matches("form") ? root : root.querySelector("form");
  const textarea = form && (form.querySelector("[data-solution-source]") || form.querySelector('textarea[name$="body_source"]'));
  if (!form || !textarea) return null;
  const scope = root.closest(".solution-workspace-page") || root;
  const workspace = scope.querySelector("[data-editor-workspace]");
  const preview = root.querySelector("[data-document-preview]");
  const status = root.querySelector("[data-preview-status]");
  const saveStatus = scope.querySelector("#solution-save-status");
  const stats = root.querySelector("[data-writing-stats]");
  const uploadFeedback = root.querySelector("[data-upload-feedback]");
  const initialTitle = field(form, "title");
  const config = window.ASTERPROOF_SOLUTION_MEDIA || {};
  const uploadUrl = root.dataset.uploadUrl || config.uploadUrl;
  const pending = new Map();
  let view = null, previous = textarea.value, previewTimer, recovery, previewGeneration = 0;
  let submitting = false, initial = "", boundDirty = form.dataset.bound === "true";
  const submitted = () => Array.from(document.querySelectorAll('button[type="submit"]')).filter(button => button.form === form);
  function snapshot() {
    const fields = {};
    for (const name of FIELDS) {
      const input = field(form, name);
      if (input) fields[name] = input.type === "checkbox" ? input.checked : input.value;
    }
    return {body_source: textarea.value, fields};
  }
  const dirty = () => boundDirty || JSON.stringify(snapshot()) !== initial;
  function updateState() {
    if (saveStatus) { saveStatus.textContent = pending.size ? "Uploading image…" : dirty() ? "Unsaved changes" : form.dataset.saved === "true" ? "Saved" : "Not saved yet"; saveStatus.dataset.dirty = String(dirty()); }
    if (stats) { const text = textarea.value.trim(); stats.textContent = (text ? text.split(/\s+/).length : 0) + " words · " + textarea.value.length.toLocaleString() + " characters"; }
    submitted().forEach(button => { button.disabled = pending.size > 0; });
    form.dispatchEvent(new CustomEvent("asterproof:editor-state", {bubbles: true}));
  }
  function schedule() {
    updateState();
    clearTimeout(previewTimer);
    previewTimer = setTimeout(render, 180);
    if (recovery) recovery.changed();
  }
  function sync() {
    if (!view) return;
    textarea.value = view.state.doc.toString();
    previous = textarea.value;
    textarea.dispatchEvent(new Event("input", {bubbles: true}));
  }
  function mapPending(changes) {
    for (const bookmark of pending.values()) mapUploadBookmark(bookmark, changes);
  }
  function typedInput(editor, from, to, text) {
    if (editor.composing || text.length !== 1) return false;
    const prefix = editor.state.doc.sliceString(0, from);
    // Escaped literal braces/brackets must not acquire an extra closing character.
    const slashes = /\\+$/.exec(prefix);
    if (slashes && slashes[0].length % 2 && "{[(".includes(text)) {
      editor.dispatch({changes: {from, to, insert: text}, selection: {anchor: from + 1}, userEvent: "input.type"});
      return true;
    }
    const begin = text === "}" && /\\begin\{([A-Za-z*]+)$/.exec(prefix);
    if (!begin || !ENVIRONMENTS.includes(begin[1])) return false;
    const rest = editor.state.doc.sliceString(to);
    if (rest.includes("\\end{" + begin[1] + "}")) return false;
    const consume = rest.startsWith("}") ? to + 1 : to;
    const insert = "}\n  \n\\end{" + begin[1] + "}";
    editor.dispatch({changes: {from, to: consume, insert}, selection: {anchor: from + 4}, userEvent: "input.type"});
    return true;
  }
  const theme = EditorView.theme({
    "&": {fontSize: "14px", color: "var(--document-ink)", backgroundColor: "var(--document-surface)"},
    "&.cm-focused": {outline: "2px solid var(--document-accent)", outlineOffset: "2px"},
    ".cm-scroller": {fontFamily: "var(--ins-font-monospace, ui-monospace, monospace)", lineHeight: "1.8", overflow: "auto"},
    ".cm-content": {minHeight: "28rem", padding: "16px 0", caretColor: "var(--document-ink)"},
    ".cm-line": {padding: "0 16px 0 10px"},
    ".cm-gutters": {backgroundColor: "var(--document-surface)", color: "var(--document-muted)", borderRight: "1px solid var(--document-line)"},
    ".cm-activeLineGutter": {backgroundColor: "var(--document-soft)"},
    ".cm-cursor": {borderLeftColor: "var(--document-ink)"},
    ".cm-selectionBackground, &.cm-focused .cm-selectionBackground": {backgroundColor: "var(--document-selection)"},
    ".cm-tooltip": {backgroundColor: "var(--document-surface)", color: "var(--document-ink)", border: "1px solid var(--document-line)", borderRadius: "4px"},
    ".cm-tooltip-autocomplete > ul > li[aria-selected]": {backgroundColor: "var(--document-accent)", color: "#fff"},
    ".cm-matchingBracket": {backgroundColor: "var(--document-soft)", outline: "1px solid var(--document-accent)"},
    ".cm-panels": {backgroundColor: "var(--document-surface)", color: "var(--document-ink)"},
  });
  try {
    const host = document.createElement("div");
    host.className = "solution-source-editor";
    textarea.before(host);
    view = new EditorView({parent: host, state: createEditorState(textarea.value, [
      lineNumbers(), highlightActiveLineGutter(), drawSelection(), history(), language,
      syntaxHighlighting(defaultHighlightStyle, {fallback: true}), bracketMatching(), closeBrackets(),
      language.data.of({closeBrackets: {brackets: ["(", "[", "{"]}}),
      EditorView.lineWrapping, EditorView.contentAttributes.of({"aria-label": textarea.labels?.[0]?.textContent || "Your solution", "aria-describedby": "solution-source-help", "spellcheck": "false", "autocapitalize": "off"}),
      Prec.highest(EditorView.inputHandler.of(typedInput)),
      autocompletion({override: [completions], activateOnTyping: true}),
      keymap.of([{key: "Tab", run: stateView => nextSnippetField(stateView) || (completionStatus(stateView.state) === "active" && acceptCompletion(stateView))}, {key: "Shift-Tab", run: prevSnippetField}, ...closeBracketsKeymap, ...completionKeymap, ...defaultKeymap, ...historyKeymap, ...searchKeymap]),
      highlightSelectionMatches(), theme,
      EditorView.domEventHandlers({paste(event) { return paste(event); }}),
      EditorView.updateListener.of(update => { if (update.docChanged) { mapPending(update.changes); sync(); } }),
    ])});
    textarea.hidden = true;
    textarea.setAttribute("aria-hidden", "true");
    textarea.tabIndex = -1;
  } catch (_) {
    view = null;
    root.querySelector(".solution-source-editor")?.remove();
    textarea.hidden = false;
    textarea.removeAttribute("aria-hidden");
    const fallback = root.querySelector("[data-editor-fallback]");
    if (fallback) { fallback.hidden = false; fallback.textContent = "The text editor is available. Autocomplete could not load; you can keep writing and save."; }
  }
  async function render() {
    if (!preview) return;
    const generation = ++previewGeneration;
    const math = window.MathJax;
    if (math && math.typesetClear) math.typesetClear([preview]);
    const rendered = renderDocument(preview, textarea.value, {...config, origin: location.origin});
    const title = root.querySelector("[data-preview-title]");
    if (title) title.textContent = initialTitle?.value || "My solution";
    const summary = root.querySelector("[data-preview-summary]");
    if (summary) { summary.textContent = field(form, "summary")?.value || ""; summary.hidden = !summary.textContent; }
    const statement = root.querySelector("[data-preview-statement]");
    if (statement) { statement.textContent = field(form, "problem_statement")?.value || ""; statement.hidden = !statement.textContent; }
    const warning = root.querySelector("[data-preview-warning]");
    if (warning) { warning.textContent = rendered.warnings.join(" "); warning.hidden = !rendered.warnings.length; }
    const ready = window.AsterProofMathReady || math?.startup?.promise;
    if (ready) { try { await ready; } catch (_) { /* Text preview remains usable. */ } }
    if (generation !== previewGeneration) return;
    const currentMath = window.MathJax;
    if (currentMath && typeof currentMath.typesetPromise === "function") {
      try {
        await currentMath.typesetPromise(rendered.scopes.concat(statement && !statement.hidden ? [statement] : []));
        if (generation === previewGeneration && status) status.textContent = "Up to date";
      } catch (_) { if (generation === previewGeneration && status) status.textContent = "Some math could not render; your source is preserved."; }
    } else if (status) status.textContent = "Text preview · math rendering is unavailable";
  }
  function source() { return view ? view.state.doc.toString() : textarea.value; }
  function setSource(value) {
    value = String(value || "");
    if (view) view.dispatch({changes: {from: 0, to: view.state.doc.length, insert: value}});
    else { textarea.value = value; textarea.dispatchEvent(new Event("input", {bubbles: true})); }
  }
  function focusRange(start, end = start) {
    const length = source().length;
    start = Math.max(0, Math.min(length, start)); end = Math.max(start, Math.min(length, end));
    if (view) { view.dispatch({selection: EditorSelection.single(start, end), scrollIntoView: true}); view.focus(); }
    else { textarea.focus(); textarea.setSelectionRange(start, end); }
  }
  function insert(template) {
    if (view) {
      const selection = view.state.selection.main;
      const value = view.state.sliceDoc(selection.from, selection.to);
      const text = template.replace("${}", value);
      const caret = selection.from + template.indexOf("${}");
      view.dispatch({changes: {from: selection.from, to: selection.to, insert: text}, selection: {anchor: caret, head: caret + value.length}, userEvent: "input"}); view.focus();
    } else {
      const start = textarea.selectionStart, end = textarea.selectionEnd;
      const selected = textarea.value.slice(start, end), text = template.replace("${}", selected);
      textarea.setRangeText(text, start, end, "end"); textarea.dispatchEvent(new Event("input", {bubbles: true})); textarea.focus();
    }
  }
  function showUploadError(message) { if (uploadFeedback) { uploadFeedback.textContent = message; uploadFeedback.hidden = !message; } }
  function paste(event) {
    if (!uploadUrl) return false;
    const clipboard = event.clipboardData;
    const item = clipboard && Array.from(clipboard.items || []).find(value => value.type.startsWith("image/"));
    const file = item?.getAsFile() || clipboard && Array.from(clipboard.files || []).find(value => value.type.startsWith("image/"));
    if (!file) return false;
    event.preventDefault();
    const selected = view ? view.state.selection.main : {from: textarea.selectionStart, to: textarea.selectionEnd};
    const bookmark = {from: selected.from, to: selected.to, selected: source().slice(selected.from, selected.to)};
    const id = Symbol("upload"); pending.set(id, bookmark); updateState(); showUploadError("");
    const data = new FormData(); data.append("image", file);
    fetch(uploadUrl, {method: "POST", body: data, credentials: "same-origin", headers: {"X-CSRFToken": form.querySelector('[name="csrfmiddlewaretoken"]').value}})
      .then(async response => { const payload = await response.json(); if (!response.ok) throw new Error(payload.error || "The image could not be uploaded."); return payload; })
      .then(payload => {
        const text = imageSnippet(payload.path);
        const current = source();
        const replacement = uploadReplacementRange(bookmark, current);
        if (view) view.dispatch({changes: {...replacement, insert: text}, userEvent: "input.paste"});
        else { textarea.value = current.slice(0, replacement.from) + text + current.slice(replacement.to); textarea.dispatchEvent(new Event("input", {bubbles: true})); }
      }).catch(error => showUploadError(error.message || "The image could not be uploaded. Your writing is still here."))
      .finally(() => { pending.delete(id); updateState(); });
    return true;
  }
  textarea.addEventListener("input", () => {
    if (view && textarea.value !== view.state.doc.toString()) { setSource(textarea.value); return; }
    if (!view) {
      for (const bookmark of pending.values()) { bookmark.from = mapOffset(bookmark.from, previous, textarea.value); bookmark.to = mapOffset(bookmark.to, previous, textarea.value); }
      previous = textarea.value;
    }
    schedule();
  });
  textarea.addEventListener("paste", event => { if (!view) paste(event); });
  form.addEventListener("input", event => { if (event.target !== textarea) schedule(); });
  form.addEventListener("change", schedule);
  form.addEventListener("submit", event => {
    if (pending.size) { event.preventDefault(); showUploadError("Wait for the image upload to finish before saving."); return; }
    sync();
    if (recovery) recovery.flush();
    submitting = true;
    // PDF downloads leave this page open, so continue guarding unsaved writing.
    if (event.submitter?.value === "download_pdf") submitting = false;
  });
  document.addEventListener("keydown", event => {
    if (!(event.ctrlKey || event.metaKey) || event.key.toLowerCase() !== "s") return;
    const collapsed = root.closest("#inline-draft-editor");
    if (collapsed?.classList.contains("d-none")) return;
    const save = scope.querySelector("#solution-save");
    if (save && !save.disabled && !view?.composing) { event.preventDefault(); form.requestSubmit(save); }
  });
  window.addEventListener("beforeunload", event => { if (!submitting && (dirty() || pending.size)) { event.preventDefault(); event.returnValue = ""; } });
  const wide = window.matchMedia("(min-width: 1200px)");
  function setPane(name) {
    if (!workspace) return;
    if (name === "split" && !wide.matches) name = "write";
    workspace.dataset.view = name;
    scope.querySelectorAll("[data-editor-view]").forEach(button => button.setAttribute("aria-pressed", String(button.dataset.editorView === name)));
    if (view) view.requestMeasure();
  }
  scope.querySelectorAll("[data-editor-view]").forEach(button => button.addEventListener("click", () => setPane(button.dataset.editorView)));
  scope.querySelectorAll("[data-start-writing]").forEach(link => link.addEventListener("click", () => setPane("write")));
  if (wide.addEventListener) wide.addEventListener("change", () => { if (!wide.matches && workspace?.dataset.view === "split") setPane("write"); });
  setPane(wide.matches ? "split" : "write");
  root.querySelectorAll("[data-insert-source]").forEach(button => button.addEventListener("click", () => insert({inline: "$${}$", display: "\\[\n${}\n\\]", fraction: "\\frac{${}}{}", claim: "\\begin{claim}\n${}\n\\end{claim}", proof: "\\begin{proof}\n${}\n\\end{proof}", align: "\\begin{align*}\n${}\n\\end{align*}", matrix: "\\begin{pmatrix}\n${}\n\\end{pmatrix}"}[button.dataset.insertSource])));
  recovery = createRecovery(root, {snapshot, restore(saved) {
    for (const [name, value] of Object.entries(saved.fields)) { const input = field(form, name); if (input) { if (input.type === "checkbox") input.checked = Boolean(value); else input.value = String(value); } }
    setSource(saved.body_source); schedule(); form.dispatchEvent(new Event("change", {bubbles: true}));
  }});
  initial = JSON.stringify(snapshot());
  updateState(); render();
  window.addEventListener("asterproof:mathjax-ready", () => { clearTimeout(previewTimer); render(); });
  document.addEventListener("asterproof:math-ready", () => { clearTimeout(previewTimer); render(); });
  scope.querySelectorAll("[data-document-views], .solution-source-tools").forEach(element => { element.hidden = false; });
  function setSaved(savedSnapshot) { boundDirty = false; initial = JSON.stringify(savedSnapshot || snapshot()); form.dataset.saved = "true"; updateState(); }
  form.addEventListener("asterproof:solution-saved", event => setSaved(event.detail?.savedSnapshot));
  const api = {source, setSource, snapshot, dirty, focusRange, preview: render, setPane, setSaved, pendingUploads: () => pending.size, form, root};
  instances.set(root, api); instances.set(form, api); instances.set(textarea, api);
  root.dispatchEvent(new CustomEvent("asterproof:editor-ready", {bubbles: true, detail: api}));
  return api;
}

function init() { document.querySelectorAll("[data-solution-document-editor]").forEach(setup); }
if (typeof window !== "undefined") {
  window.AsterProofDocumentEditors = {get: node => instances.get(node) || instances.get(node?.closest?.("[data-solution-document-editor]")), init};
  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", init, {once: true});
  else init();
}

module.exports = {completionSpec, completions, createEditorState};
