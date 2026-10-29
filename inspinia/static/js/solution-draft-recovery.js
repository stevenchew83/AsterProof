/* Optional device recovery. Stored text is assigned to form controls, never HTML. */
(function (scope) {
  "use strict";
  const KEY = "asterproof.solution-writer.draft.v1";
  const TTL = 7 * 24 * 60 * 60 * 1000;
  const text = (value, limit) => typeof value === "string" && value.length <= limit;

  function validDocument(doc) {
    return doc && text(doc.title, 160) && text(doc.author_name, 100) && text(doc.problem_statement, 12000) &&
      ["pdf_show_author", "pdf_show_date", "pdf_show_footer"].every(key => typeof doc[key] === "boolean") &&
      Array.isArray(doc.blocks) && doc.blocks.length <= 32 && doc.blocks.every(block => block &&
        text(block.block_type, 30) && text(block.title, 300) && text(block.body_source, 12000) &&
        ["latex", "plain_text"].includes(block.body_format)) && JSON.stringify(doc).length <= 100000;
  }

  function decode(raw, now) {
    if (typeof raw !== "string" || raw.length > 400000) return null;
    try {
      const value = JSON.parse(raw);
      if (value.version !== 1 || !Number.isFinite(value.savedAt) || !Number.isFinite(value.expiresAt) ||
          value.savedAt > now + 60000 || value.expiresAt <= now || value.expiresAt <= value.savedAt ||
          value.expiresAt - value.savedAt > TTL || !validDocument(value.document)) return null;
      return value;
    } catch (_) { return null; }
  }

  function create(options) {
    const root = options.root.querySelector("[data-draft-recovery]");
    if (!root) return null;
    const enable = root.querySelector("[data-draft-enable]");
    const status = root.querySelector("[data-draft-status]");
    const offer = root.querySelector("[data-draft-offer]");
    const offerText = root.querySelector("[data-draft-offer-text]");
    const clear = root.querySelector("[data-draft-clear]");
    let knownRaw = null, awaitingRestore = false, timer;
    root.hidden = false;

    function failed() {
      enable.checked = false;
      status.textContent = "Device storage is unavailable. Your writing is still open here; continue in your workspace or download a PDF.";
    }

    function load() {
      const raw = scope.localStorage.getItem(KEY);
      const saved = decode(raw, Date.now());
      knownRaw = raw;
      if (raw && !saved) {
        scope.localStorage.removeItem(KEY);
        knownRaw = null;
      }
      clear.hidden = !saved;
      awaitingRestore = Boolean(saved && JSON.stringify(saved.document) !== JSON.stringify(options.snapshot()));
      enable.checked = Boolean(saved && !awaitingRestore);
      offer.hidden = !awaitingRestore;
      if (awaitingRestore) {
        offerText.textContent = "Device draft available: " + (saved.document.title || "Untitled solution") +
          ". Restoring replaces the writing currently in this editor.";
        status.textContent = "Restore the device draft, or clear it before keeping a different draft.";
      } else {
        status.textContent = saved ? "Recovery copy saved on this device. It expires after seven days without edits." :
          "Device recovery is off. Your writing stays open in this tab.";
      }
      return saved;
    }

    function persist() {
      clearTimeout(timer);
      if (!enable.checked || awaitingRestore) return;
      const document = options.snapshot();
      if (!validDocument(document)) {
        status.textContent = "This draft is too large for device recovery. Your current writing is still here.";
        return;
      }
      try {
        // A stale tab must not replace a newer device draft.
        if (scope.localStorage.getItem(KEY) !== knownRaw) { load(); return; }
        const savedAt = Date.now();
        const raw = JSON.stringify({version: 1, savedAt, expiresAt: savedAt + TTL, document});
        scope.localStorage.setItem(KEY, raw);
        knownRaw = raw;
        clear.hidden = false;
        status.textContent = "Recovery copy saved on this device. It expires after seven days without edits.";
      } catch (_) { failed(); }
    }

    function remove() {
      clearTimeout(timer);
      try {
        scope.localStorage.removeItem(KEY);
        knownRaw = null;
        awaitingRestore = false;
        enable.checked = false;
        offer.hidden = true;
        clear.hidden = true;
        status.textContent = "Device draft cleared. Your current writing is still open here.";
      } catch (_) { failed(); }
    }

    enable.addEventListener("change", function () {
      if (!enable.checked) { remove(); return; }
      if (awaitingRestore) {
        enable.checked = false;
        status.textContent = "Restore or clear the existing device draft first. Your current writing has not replaced it.";
        return;
      }
      persist();
    });
    clear.addEventListener("click", remove);
    root.querySelector("[data-draft-restore]").addEventListener("click", function () {
      try {
        const saved = load();
        if (!saved) return;
        options.restore(saved.document);
        awaitingRestore = false;
        offer.hidden = true;
        enable.checked = true;
        persist();
      } catch (_) { failed(); }
    });
    scope.addEventListener("storage", function (event) {
      if (event.key !== KEY && event.key !== null) return;
      clearTimeout(timer);
      try { load(); } catch (_) { failed(); }
    });
    scope.addEventListener("pagehide", persist);
    try { load(); } catch (_) { failed(); }
    return {
      changed: function () { clearTimeout(timer); timer = setTimeout(persist, 250); },
      flush: persist,
    };
  }

  scope.AsterProofDraftRecovery = {create};
  if (typeof module !== "undefined" && module.exports) module.exports = {decode, validDocument, create, KEY, TTL};
}(typeof window === "undefined" ? globalThis : window));
