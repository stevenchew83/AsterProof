"use strict";

const TTL = 7 * 24 * 60 * 60 * 1000;
const MAX_BYTES = 1000000;
const LEGACY_KEY = "asterproof.solution-writer.draft.v1";
const {decode: decodeLegacy} = require("./solution-draft-recovery.js");
const {convertLegacyBlock} = require("./solution-document-core.js");

function recoveryKey(owner, problem) {
  return "asterproof.solution-document.v2:" + encodeURIComponent(owner || "anonymous") + ":" + encodeURIComponent(problem || "public-writer");
}

function decode(raw, now = Date.now()) {
  if (typeof raw !== "string" || raw.length > MAX_BYTES) return null;
  try {
    const saved = JSON.parse(raw);
    if (saved.version !== 2 || !Number.isFinite(saved.savedAt) || !Number.isFinite(saved.expiresAt) ||
      saved.savedAt > now + 60000 || saved.expiresAt <= now || saved.expiresAt <= saved.savedAt ||
      saved.expiresAt - saved.savedAt > TTL || !saved.document || typeof saved.document.body_source !== "string" ||
      saved.document.body_source.length > 200000 || !saved.document.fields || typeof saved.document.fields !== "object" ||
      Object.values(saved.document.fields).some(value => typeof value !== "string" && typeof value !== "boolean")) return null;
    return saved;
  } catch (_) { return null; }
}

function createRecovery(root, options) {
  const panel = root.querySelector("[data-draft-recovery]");
  if (!panel) return null;
  const enable = panel.querySelector("[data-draft-enable]");
  const status = panel.querySelector("[data-draft-status]");
  const offer = panel.querySelector("[data-draft-offer]");
  const offerText = panel.querySelector("[data-draft-offer-text]");
  const clear = panel.querySelector("[data-draft-clear]");
  const key = recoveryKey(root.dataset.owner, root.dataset.problem);
  let knownRaw = null, awaitingRestore = false, legacyRaw = null, timer;
  function failed() {
    enable.checked = false;
    status.textContent = "Device storage is unavailable. Your writing is still open here.";
  }
  function load() {
    const raw = window.localStorage.getItem(key);
    let saved = decode(raw);
    legacyRaw = null;
    if (!raw && !root.dataset.problem && (!root.dataset.owner || root.dataset.owner === "anonymous")) {
      const candidate = window.localStorage.getItem(LEGACY_KEY);
      const legacy = decodeLegacy(candidate, Date.now());
      if (legacy) {
        let types = {};
        try { types = JSON.parse(root.ownerDocument.getElementById("solution-block-type-slugs")?.textContent || "{}") || {}; } catch (_) { /* Preserve all text even if metadata is unavailable. */ }
        const {blocks, ...fields} = legacy.document;
        const body_source = blocks.map(block => convertLegacyBlock(block, types)).join("\n\n");
        saved = {document: {body_source, fields}, savedAt: legacy.savedAt, expiresAt: legacy.expiresAt};
        legacyRaw = candidate;
      }
    }
    knownRaw = raw;
    if (raw && !saved) { window.localStorage.removeItem(key); knownRaw = null; }
    awaitingRestore = Boolean(saved && JSON.stringify(saved.document) !== JSON.stringify(options.snapshot()));
    enable.checked = Boolean(saved && !awaitingRestore);
    clear.hidden = !saved;
    offer.hidden = !awaitingRestore;
    if (awaitingRestore) {
      offerText.textContent = legacyRaw ? "An older block-based draft is available. Restore it as one document; your original device draft stays available until recovery succeeds." : "A recovery copy is available for this document. Restore it to replace the writing currently open here.";
      status.textContent = "Restore or clear the recovery copy before saving another device draft.";
    } else status.textContent = saved ? "Recovery copy saved on this device. It expires after seven days without edits." : "Device recovery is off. Your writing stays open in this tab.";
    return saved;
  }
  function persist() {
    clearTimeout(timer);
    if (!enable.checked || awaitingRestore) return;
    try {
      if (window.localStorage.getItem(key) !== knownRaw) { load(); return; }
      const savedAt = Date.now();
      const raw = JSON.stringify({version: 2, savedAt, expiresAt: savedAt + TTL, document: options.snapshot()});
      if (raw.length > MAX_BYTES) { status.textContent = "This document is too large for device recovery. Save your writing in your workspace."; return; }
      window.localStorage.setItem(key, raw);
      if (legacyRaw && window.localStorage.getItem(LEGACY_KEY) === legacyRaw) window.localStorage.removeItem(LEGACY_KEY);
      legacyRaw = null;
      knownRaw = raw;
      clear.hidden = false;
      status.textContent = "Recovery copy saved on this device. It expires after seven days without edits.";
    } catch (_) { failed(); }
  }
  function remove() {
    clearTimeout(timer);
    try {
      window.localStorage.removeItem(key);
      if (legacyRaw && window.localStorage.getItem(LEGACY_KEY) === legacyRaw) window.localStorage.removeItem(LEGACY_KEY);
      knownRaw = null; awaitingRestore = false; enable.checked = false;
      offer.hidden = true; clear.hidden = true;
      status.textContent = "Device recovery cleared. Your writing is still open here.";
    } catch (_) { failed(); }
  }
  enable.disabled = false;
  enable.addEventListener("change", () => {
    if (!enable.checked) { remove(); return; }
    if (awaitingRestore) { enable.checked = false; return; }
    persist();
  });
  clear.addEventListener("click", remove);
  panel.querySelector("[data-draft-restore]").addEventListener("click", () => {
    try {
      const saved = load();
      if (!saved) return;
      options.restore(saved.document);
      awaitingRestore = false; offer.hidden = true; enable.checked = true;
      persist();
    } catch (_) { failed(); }
  });
  window.addEventListener("storage", event => { if (event.key === key || event.key === null) { clearTimeout(timer); try { load(); } catch (_) { failed(); } } });
  window.addEventListener("pagehide", persist);
  try { load(); } catch (_) { failed(); }
  return {changed() { clearTimeout(timer); timer = setTimeout(persist, 300); }, flush: persist};
}

module.exports = {TTL, MAX_BYTES, LEGACY_KEY, recoveryKey, decode, createRecovery};
