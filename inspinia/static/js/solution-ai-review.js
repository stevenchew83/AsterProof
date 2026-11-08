/* Private, explicit revision-bound coaching. No provider credentials reach this module. */
(function () {
  "use strict";
  function init() {
    const node = document.getElementById("solution-review-config");
    const form = document.getElementById("solution-editor-form");
    const coach = document.querySelector("[data-ai-coach]");
    if (!node || !form || !coach || coach.dataset.initialized) return;
    coach.dataset.initialized = "true";
    let config;
    try { config = JSON.parse(node.textContent); } catch (_) { return; }
    const source = form.querySelector("[data-solution-source]");
    const start = coach.querySelector("[data-review-start]");
    const status = coach.querySelector("[data-review-status]");
    const report = coach.querySelector("[data-review-report]");
    const reviewed = coach.querySelector("[data-review-source]");
    const details = coach.querySelector("[data-review-source-details]");
    const csrf = form.querySelector('[name="csrfmiddlewaretoken"]');
    if (!source || !csrf) return;
    let busy = false, last = null, statusUrl = "", timer, pollGeneration = 0, errorMessage = false;
    let requestKey = "", requestRevision = "", requestPending = false;
    const scope = form.closest("[data-solution-document-editor]") || form;
    const recoveryKey = "asterproof.solution-review:" + (scope.dataset.owner || "") + ":" + config.createUrl;
    const editor = () => window.AsterProofDocumentEditors && window.AsterProofDocumentEditors.get(form);
    const text = () => editor() ? editor().source() : source.value;
    function snapshot() {
      if (editor()) return editor().snapshot();
      const fields = {};
      ["title", "summary", "problem_statement", "author_name", "pdf_show_author", "pdf_show_date", "pdf_show_footer"].forEach(name => {
        const input = Array.from(form.elements || []).find(element => element.name === name || element.name.endsWith("-" + name));
        if (input) fields[name] = input.type === "checkbox" ? input.checked : input.value;
      });
      return {body_source: source.value, fields};
    }
    function message(value, error) { errorMessage = Boolean(error); status.textContent = value; status.classList.toggle("text-danger", errorMessage); }
    function update() {
      const dirty = editor() ? editor().dirty() : true;
      const pending = editor() && editor().pendingUploads();
      start.textContent = !config.enabled ? "New AI reviews are unavailable" : dirty || !config.revisionId ? "Save and review" : "Review my solution";
      if (config.enabled && !dirty && requestKey && requestRevision === config.revisionId && !statusUrl) start.textContent = "Check review request";
      if (config.enabled && last && last.status === "outcome_unknown" && last.revision_id === config.revisionId && !dirty) start.textContent = "Check review status";
      start.disabled = !config.enabled || busy || Boolean(pending);
      if (!errorMessage && last && last.status === "completed" && (last.stale || last.reviewed_source !== text())) {
        message("This feedback concerns an earlier version. Open ‘Writing reviewed’ to see the exact source.");
      }
    }
    async function json(response) {
      if (response.redirected || response.status === 401) throw new Error("Sign in again before saving or reviewing. Your writing is still here.");
      let data;
      try { data = await response.json(); } catch (_) { throw new Error("The service could not respond. Your writing is still here."); }
      if (!response.ok) throw new Error(data.error || "This request could not be completed. Your writing is still here.");
      return data;
    }
    function persist() {
      try { sessionStorage.setItem(recoveryKey, JSON.stringify({version: 2, url: statusUrl, key: requestKey, revision: requestRevision, pending: requestPending})); } catch (_) { /* Recovery is optional. */ }
    }
    function remember(url) {
      const parsed = new URL(url, window.location.origin);
      if (parsed.origin !== window.location.origin || !parsed.pathname.startsWith(config.createUrl)) throw new Error("Invalid review location.");
      if (statusUrl !== parsed.pathname) { clearTimeout(timer); pollGeneration += 1; }
      statusUrl = parsed.pathname;
      persist();
    }
    async function save() {
      if (editor() && editor().pendingUploads()) throw new Error("Wait for the image upload to finish before reviewing.");
      const savedSnapshot = snapshot();
      const data = new FormData(form);
      data.set("action", form.querySelector('[name="writer_draft_token"]') ? "save_draft" : "save");
      message("Saving the version to review…");
      const result = await json(await fetch(form.getAttribute("action") || window.location.href, {
        method: "POST", body: data, credentials: "same-origin", headers: {"X-Requested-With": "XMLHttpRequest"},
      }));
      config.revisionId = result.revision_id;
      config.editVersion = result.edit_version;
      form.querySelector('[name$="base_version"]').value = result.edit_version;
      form.querySelector('[name$="editor_context"]').value = result.editor_context;
      const handoff = form.querySelector('[name="writer_draft_token"]');
      if (handoff) handoff.remove();
      form.dispatchEvent(new CustomEvent("asterproof:solution-saved", {bubbles: true, detail: {...result, savedSnapshot}}));
    }
    function paragraph(parent, value, className) {
      const p = document.createElement("p"); p.textContent = value;
      if (className) p.className = className;
      parent.appendChild(p); return p;
    }
    function show(data) {
      last = data; report.replaceChildren();
      reviewed.textContent = data.reviewed_source || "";
      details.hidden = data.status !== "completed";
      if (data.status !== "completed") return;
      const feedback = data.feedback || data;
      const labels = {no_issues_found: "No issues found", gap_found: "A gap needs attention", incomplete: "This proof is incomplete", unable_to_assess: "More context is needed"};
      paragraph(report, labels[feedback.assessment] || "Coaching feedback", "fw-semibold mt-3");
      paragraph(report, feedback.summary || "");
      (feedback.strengths || []).forEach(value => paragraph(report, value, "text-muted fs-sm"));
      (feedback.findings || []).forEach(finding => {
        const section = document.createElement("section"); section.className = "border rounded p-3 mb-3";
        if (finding.quote) {
          const quote = document.createElement("blockquote"); quote.className = "fs-sm tex2jax_ignore";
          quote.textContent = finding.quote; section.appendChild(quote);
        }
        paragraph(section, finding.explanation || "");
        if (finding.anchor && Number.isInteger(finding.anchor.line)) {
          const jump = document.createElement("button"); jump.type = "button";
          jump.className = "btn btn-link btn-sm p-0 mb-2"; jump.textContent = "Show this passage";
          jump.addEventListener("click", () => {
            const lines = (data.reviewed_source || "").split("\n");
            const first = Math.max(0, finding.anchor.line - 1), end = Math.max(first + 1, finding.anchor.end_line);
            const before = lines.slice(0, first).join("\n") + (first ? "\n" : "");
            const passage = lines.slice(first, end).join("\n");
            if (!data.stale && data.reviewed_source === text() && editor()) {
              editor().setPane("write"); editor().focusRange(before.length, before.length + passage.length);
            } else {
              details.open = true; reviewed.replaceChildren(document.createTextNode(before));
              const mark = document.createElement("mark"); mark.textContent = passage; reviewed.appendChild(mark);
              reviewed.appendChild(document.createTextNode((end < lines.length ? "\n" : "") + lines.slice(end).join("\n")));
              mark.scrollIntoView({block: "center"});
            }
          });
          section.appendChild(jump);
        }
        (finding.hints || []).forEach((hint, index) => paragraph(section, "Hint " + (index + 1) + ": " + hint, "fs-sm"));
        if (finding.reveal_url && finding.hint_count > (finding.released_level || 0)) {
          const more = document.createElement("button"); more.type = "button";
          more.className = "btn btn-outline-secondary btn-sm";
          more.textContent = finding.released_level ? "Reveal hint 2" : "Reveal hint 1";
          more.addEventListener("click", async () => {
            const generation = pollGeneration, target = statusUrl;
            more.disabled = true;
            try {
              const next = await json(await fetch(finding.reveal_url, {method: "POST", credentials: "same-origin",
                headers: {"Content-Type": "application/json", "X-CSRFToken": csrf.value},
                body: JSON.stringify({level: (finding.released_level || 0) + 1})}));
              if (generation !== pollGeneration || target !== statusUrl) return;
              show(next);
            } catch (error) {
              if (generation !== pollGeneration || target !== statusUrl) return;
              message(error.message, true); more.disabled = false;
            }
          });
          section.appendChild(more);
        }
        report.appendChild(section);
      });
      if (feedback.next_step) paragraph(report, feedback.next_step);
      (feedback.limitations || []).forEach(value => paragraph(report, value, "text-muted fs-sm"));

    }
    async function poll() {
      if (!statusUrl) return;
      clearTimeout(timer);
      const generation = ++pollGeneration, target = statusUrl;
      try {
        const data = await json(await fetch(target, {credentials: "same-origin", cache: "no-store"}));
        if (generation !== pollGeneration || target !== statusUrl) return;
        show(data);
        if (["queued", "running"].includes(data.status)) {
          busy = true; message(data.status === "queued" ? "Your saved proof is queued for review. You can continue writing." : "Reviewing your saved proof. You can continue writing.");
          timer = setTimeout(poll, document.hidden ? 10000 : 2000);
        } else {
          busy = false;
          const labels = {completed: "Feedback is ready for the saved version.", failed: "The review could not be completed. Your writing is saved.", outcome_unknown: "The provider’s outcome is uncertain. This request will not be sent again automatically.", expired: "This review expired before processing. Your writing is saved."};
          message(labels[data.status] || "Review status is unavailable.", data.status !== "completed");
        }
        update();
      } catch (error) { if (generation !== pollGeneration || target !== statusUrl) return; busy = false; message(error.message, true); update(); }
    }
    start.addEventListener("click", async function () {
      if (busy || !config.enabled) return;
      const acknowledgement = coach.querySelector("[data-review-acknowledgement]");
      if (!config.acknowledged && !(acknowledgement && acknowledgement.checked)) {
        const explanation = acknowledgement && acknowledgement.closest("details");
        if (explanation) explanation.open = true;
        message("Read what is sent for review and acknowledge it before requesting feedback.", true); return;
      }
      if (editor() && editor().pendingUploads()) { message("Wait for the image upload to finish before reviewing.", true); return; }
      busy = true; update();
      clearTimeout(timer); pollGeneration += 1;
      try {
        const runExplicitSave = editor()?.runExplicitSave;
        await (runExplicitSave ? runExplicitSave(save) : save());
        if (!requestPending && last && last.revision_id === config.revisionId && !last.stale && last.reviewed_source === text() && ["completed", "queued", "running", "outcome_unknown"].includes(last.status)) {
          await poll(); return;
        }
        if (requestRevision !== config.revisionId || !requestKey || !requestPending && last && ["failed", "expired"].includes(last.status)) {
          requestKey = crypto.randomUUID(); requestRevision = config.revisionId;
        }
        // Persist before dispatch: reloading after a lost response must check the
        // same idempotency key rather than silently create another paid attempt.
        requestPending = true; statusUrl = ""; last = null; report.replaceChildren(); details.hidden = true; persist();
        const statement = coach.querySelector("[data-review-statement]");
        const body = {
          revision_id: config.revisionId, idempotency_key: requestKey,
          acknowledged: Boolean(acknowledgement && acknowledgement.checked),
          statement_text: statement ? statement.value : "",
          statement_confirmed: Boolean(coach.querySelector("[data-review-statement-confirmed]:checked")),
        };
        const data = await json(await fetch(config.createUrl, {method: "POST", credentials: "same-origin",
          headers: {"Content-Type": "application/json", "X-CSRFToken": csrf.value}, body: JSON.stringify(body)}));
        config.acknowledged = true; requestPending = false;
        remember(data.status_url); await poll();
      } catch (error) { busy = false; message(error.message, true); update(); }
    });
    form.addEventListener("input", update);
    form.addEventListener("asterproof:editor-state", update);
    window.addEventListener("asterproof:editor-ready", update);
    form.addEventListener("asterproof:solution-saved", event => { config.revisionId = event.detail.revision_id; update(); });
    message(config.enabled ? "Review is available to this pilot account." : "New reviews are unavailable. Saved feedback remains private and readable.");
    try {
      const raw = sessionStorage.getItem(recoveryKey);
      if (raw) {
        let saved;
        try { saved = JSON.parse(raw); } catch (_) { saved = {url: raw}; }
        if (saved && typeof saved === "object") {
          if (saved.version === 2 && typeof saved.key === "string" && /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i.test(saved.key) && typeof saved.revision === "string") {
            requestKey = saved.key; requestRevision = saved.revision; requestPending = saved.pending === true;
          }
          if (!config.latestStatusUrl && typeof saved.url === "string" && saved.url) remember(saved.url);
        }
      }
      if (config.latestStatusUrl) remember(config.latestStatusUrl);
      if (statusUrl) { busy = true; poll(); }
    } catch (_) { /* No recovery. */ }
    update();
  }
  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", init, {once: true}); else init();
  window.addEventListener("asterproof:editor-ready", init);
}());
