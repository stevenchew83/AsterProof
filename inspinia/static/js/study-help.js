/* Private, explicit reveals for archive Study Help. */
"use strict";

(() => {
  const root = document.querySelector("[data-study-help]");
  if (!root) return;
  const draft = root.hasAttribute("data-study-help-draft");
  if (draft) {
    // Keep controls outside the statement's scroll area. This deferred script runs before MathJax.
    root.closest(".solution-reference-body").after(root);
    window.MathJax.tex.packages["[-]"] = ["require", "autoload", "html"];
    window.MathJax.options.safeOptions.allow.URLs = "none";
  }
  const find = selector => root.querySelector(selector);
  const labels = {
    hint: "Get a hint",
    stronger_hint: "Get a second hint",
    solution: "Full solution",
    alternative: "Try a different approach",
  };
  const responseLabels = {
    hint: "First hint", stronger_hint: "Second hint", solution: "Full solution", alternative: "Alternative solution",
  };
  const proof = action => action === "solution" || action === "alternative";
  const actionOrder = Object.keys(labels).filter(action => !draft || !proof(action));
  const token = find("[name=csrfmiddlewaretoken]").value;
  const actions = find("[data-actions]");
  const feedback = find("[data-feedback]");
  const confirmation = find("[data-confirmation]");
  const answer = find("[data-answer]");
  const answerBody = find("[data-answer-body]");
  const history = find("[data-history]");
  const historyList = find("[data-history-list]");
  let state, confirmationData, autoOpenId, openId, timer, focusLabel, busy = false;
  let statusRequest = 0;
  const dateFormat = new Intl.DateTimeFormat("en-MY", {
    dateStyle: "medium", timeZone: "Asia/Kuala_Lumpur",
  });

  function button(label, style, handler) {
    const node = document.createElement("button");
    node.type = "button";
    node.className = "btn btn-sm " + style;
    node.textContent = label;
    node.addEventListener("click", handler);
    return node;
  }

  function note(message) {
    if (feedback.textContent !== message) feedback.textContent = message;
  }

  async function request(url, payload, keepalive = false) {
    const result = await fetch(url, payload ? {
      method: "POST",
      credentials: "same-origin",
      headers: {"Content-Type": "application/json", "X-CSRFToken": token},
      body: JSON.stringify(payload),
      keepalive,
    } : {credentials: "same-origin", cache: "no-store"});
    if (result.redirected) throw Object.assign(new Error("AI study help is unavailable."), {code: "unavailable"});
    let data;
    try { data = await result.json(); } catch { throw new Error("Study help couldn’t be reached."); }
    if (!result.ok) throw Object.assign(new Error(data.message || "Study help is unavailable."), data);
    return data;
  }

  function click(action, interactionKey) {
    request(root.dataset.clickUrl, {action, interaction_key: interactionKey}, true).catch(() => {});
  }

  function closeAnswer() {
    window.MathJax?.typesetClear?.([answerBody]);
    answerBody.replaceChildren();
    answer.hidden = true;
    openId = undefined;
  }

  function present(next) {
    state = next;
    root.hidden = false;
    const quota = find("[data-quota]");
    const limits = [
      next.account_remaining + (next.account_remaining === 1 ? " AI credit left" : " AI credits left"),
      next.statement_hints_used + " of " + next.statement_hint_limit + " hints used here",
    ];
    if (!draft) {
      limits.push(
        next.solutions_left + (next.solutions_left === 1 ? " solution credit left" : " solution credits left"),
        next.statement_solutions_used + " of " + next.statement_solution_limit + " used here",
      );
    }
    quota.textContent = limits.join(" · ");
    if (confirmationData && (
      next.revision !== confirmationData.revision ||
      next.actions[confirmationData.action]?.slot !== confirmationData.slot
    )) {
      confirmationData = undefined;
      confirmation.hidden = true;
    }
    const message = next.pending_here ? "Generating your AI response…" : next.message || next.failure || (
      next.account_remaining === 0 ? "You’ve used all your AI credits." :
      !draft && next.solutions_left === 0 ? "You’ve used all your free solution credits." :
      !draft && next.statement_solutions_used >= next.statement_solution_limit ? "Both solution slots are used." : ""
    );
    note(message);
    const saved = next.saved.filter(item => actionOrder.includes(item.action));
    if (openId && !saved.some(item => item.id === openId)) closeAnswer();
    const focusedText = root.contains(document.activeElement) ? document.activeElement.textContent : "";
    const currentHint = saved.find(item => item.action === "hint");
    const currentProof = saved.find(item => item.current && proof(item.action));
    actions.replaceChildren();
    if (currentHint && openId !== currentHint.id) {
      actions.append(button("View saved hint", "btn-light border text-body-emphasis", () => show(currentHint, "View saved hint")));
    }
    for (const action of actionOrder) {
      if (action === "alternative" && currentProof && openId !== currentProof.id) {
        actions.append(button("View saved solution", "btn-light border text-body-emphasis", () => show(currentProof, "View saved solution")));
      }
      const option = next.actions[action];
      if (option) {
        actions.append(button(labels[action], proof(action) ? "btn-light border text-body-emphasis" : "btn-primary bg-primary-subtle text-body-emphasis", () => {
          begin(action, option);
        }));
      }
    }
    history.hidden = !saved.length;
    find("[data-history-label]").textContent = "My saved responses (" + saved.length + ")";
    historyList.replaceChildren();
    for (const item of saved) {
      const row = document.createElement("li");
      row.className = "d-flex flex-wrap align-items-center gap-2 py-1";
      const title = responseLabels[item.action];
      const meta = document.createElement("span");
      meta.className = "small text-body-secondary";
      meta.textContent = dateFormat.format(new Date(item.created_at)) + (item.current ? "" : " · Earlier revision");
      row.append(button("View " + title.toLowerCase(), "btn-light border text-body-emphasis", () => {
        show(item, "View " + title.toLowerCase());
      }), meta);
      historyList.append(row);
    }
    if (focusedText) {
      [...actions.querySelectorAll("button"), ...historyList.querySelectorAll("button")]
        .find(item => item.textContent === focusedText && item.getClientRects().length)?.focus();
    }
    clearTimeout(timer);
    if (next.pending && !document.hidden) timer = setTimeout(refresh, 2000);
    if (autoOpenId && !next.pending) {
      const item = saved.find(response => response.id === autoOpenId);
      autoOpenId = undefined;
      if (item) show(item, labels[item.action], true);
    }
  }

  function showError(error) {
    if (error.code === "unavailable" && !state) return;
    root.hidden = false;
    if (["assistance_restricted", "unavailable", "inactive_statement"].includes(error.code)) {
      closeAnswer();
      history.hidden = true;
      actions.replaceChildren();
      find("[data-quota]").textContent = "";
      confirmation.hidden = true;
      confirmationData = undefined;
      state = undefined;
    }
    if (error.status) present(error.status);
    note(error.message || "Study help couldn’t be reached. Reload the page to try again.");
  }

  async function refresh() {
    if (busy) return;
    const sequence = ++statusRequest;
    try {
      const next = await request(root.dataset.statusUrl);
      if (sequence === statusRequest && !busy) present(next);
    } catch (error) {
      if (sequence === statusRequest && !busy) showError(error);
    }
  }

  function begin(action, option) {
    if (busy || !state) return;
    const interactionKey = crypto.randomUUID();
    click(action, interactionKey);
    const data = {
      request_key: crypto.randomUUID(), interaction_key: interactionKey,
      action, revision: state.revision, slot: option.slot, prior_id: option.prior_id,
      confirmed: proof(action),
    };
    if (proof(action)) {
      confirmationData = data;
      find("[data-confirm-label]").textContent = action === "alternative" ?
        "Generate a different proof for 1 credit?" : "Reveal a complete proof for 1 credit?";
      confirmation.hidden = false;
      find("[data-confirm]").focus();
    } else {
      generate(data);
    }
  }

  async function generate(data) {
    if (busy) return;
    statusRequest++;
    busy = true;
    confirmation.hidden = true;
    confirmationData = undefined;
    actions.querySelectorAll("button").forEach(item => { item.disabled = true; });
    note("Requesting AI study help…");
    feedback.focus({preventScroll: true});
    try {
      const result = await request(root.dataset.requestUrl, data);
      if (!proof(data.action)) autoOpenId = result.id;
      busy = false;
      present(result.status);
    } catch (error) {
      busy = false;
      actions.querySelectorAll("button").forEach(item => { item.disabled = false; });
      showError(error);
      if (!error.code) timer = setTimeout(refresh, 2000);
    }
  }

  async function show(item, triggerLabel, automatic = false) {
    if (busy) return;
    statusRequest++;
    busy = true;
    focusLabel = triggerLabel;
    try {
      const result = await request(root.dataset.revealUrl, {
        response_id: item.id, interaction_key: crypto.randomUUID(),
        automatic,
      });
      openId = item.id;
      find("[data-answer-title]").textContent = responseLabels[item.action] +
        (result.response.current ? "" : " · Earlier revision");
      window.MathJax?.typesetClear?.([answerBody]);
      answerBody.textContent = result.response.body;
      answer.hidden = false;
      present(result.status);
      find("[data-answer-title]").focus({preventScroll: false});
      const renderMath = () => window.MathJax?.typesetPromise?.([answerBody]).catch(() => {});
      if (window.MathJax?.typesetPromise) renderMath();
      else window.addEventListener("asterproof:mathjax-ready", renderMath, {once: true});
    } catch (error) {
      showError(error);
    } finally {
      busy = false;
    }
  }

  find("[data-close]").addEventListener("click", () => {
    closeAnswer();
    if (state) present(state);
    [...root.querySelectorAll("button")]
      .find(item => item.textContent === focusLabel && item.getClientRects().length)?.focus();
  });
  find("[data-confirm]").addEventListener("click", () => {
    if (confirmationData) generate(confirmationData);
  });
  function cancel() {
    const action = confirmationData?.action;
    confirmationData = undefined;
    confirmation.hidden = true;
    [...actions.querySelectorAll("button")].find(item => item.textContent === labels[action])?.focus();
  }
  find("[data-cancel]").addEventListener("click", cancel);
  confirmation.addEventListener("keydown", event => {
    if (event.key === "Escape") cancel();
  });
  document.addEventListener("visibilitychange", () => {
    if (document.hidden) clearTimeout(timer);
    else refresh();
  });
  refresh();
})();
