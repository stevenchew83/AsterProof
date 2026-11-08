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
  const controls = find("[data-controls]");
  const actions = find("[data-actions]");
  const hintCost = find("[data-hint-cost]");
  const quota = find("[data-quota]");
  const feedback = find("[data-feedback]");
  const confirmation = find("[data-confirmation]");
  const answer = find("[data-answer]");
  const answerBody = find("[data-answer-body]");
  const answerLevel = find("[data-answer-level]");
  const copyFeedback = find("[data-copy-feedback]");
  const history = find("[data-history]");
  const historyList = find("[data-history-list]");
  let state, confirmationData, autoOpenId, openId, answerSource, timer, returnFocus, busy = false;
  let statusRequest = 0;
  const dateFormat = new Intl.DateTimeFormat("en-MY", {
    dateStyle: "medium", timeZone: "Asia/Kuala_Lumpur",
  });

  const savedFocus = item => "saved:" + item.id;
  const actionFocus = action => "action:" + action;

  function button(label, style, key, handler) {
    const node = document.createElement("button");
    node.type = "button";
    node.className = "btn btn-sm " + style;
    node.textContent = label;
    node.dataset.studyHelpFocus = key;
    node.addEventListener("click", handler);
    return node;
  }

  function focusControl(key) {
    if (!key) return;
    [...root.querySelectorAll("[data-study-help-focus]")]
      .find(item => item.dataset.studyHelpFocus === key && item.getClientRects().length)?.focus();
  }

  function metric(value, label) {
    const item = document.createElement("li");
    const number = document.createElement("strong");
    number.textContent = value;
    item.append(number, " " + label);
    return item;
  }

  function note(message, tone = "neutral") {
    if (feedback.textContent !== message) feedback.textContent = message;
    feedback.dataset.tone = tone;
    feedback.hidden = !message;
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
    answerSource = undefined;
  }

  function present(next) {
    state = next;
    root.hidden = false;
    const limits = [
      metric(next.account_remaining, next.account_remaining === 1 ? "AI credit left" : "AI credits left"),
      metric(next.statement_hints_used + " / " + next.statement_hint_limit, "hints used here"),
    ];
    if (!draft) {
      limits.push(
        metric(next.solutions_left, next.solutions_left === 1 ? "solution credit left" : "solution credits left"),
        metric(next.statement_solutions_used + " / " + next.statement_solution_limit, "solutions used here"),
      );
    }
    quota.replaceChildren(...limits);
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
    note(message, next.pending_here ? "loading" : !next.message && next.failure ? "error" : "neutral");
    const saved = next.saved.filter(item => actionOrder.includes(item.action))
      .sort((left, right) => actionOrder.indexOf(left.action) - actionOrder.indexOf(right.action));
    if (openId && !saved.some(item => item.id === openId)) closeAnswer();
    const focusedKey = root.contains(document.activeElement) ? document.activeElement.dataset.studyHelpFocus : undefined;
    actions.replaceChildren();
    for (const action of actionOrder) {
      const option = next.actions[action];
      if (option) {
        const style = proof(action) ? "btn-outline-secondary" : "btn-primary";
        actions.append(button(labels[action], style, actionFocus(action), () => begin(action, option)));
      }
    }
    controls.hidden = !actions.childElementCount;
    hintCost.hidden = !(next.actions.hint || next.actions.stronger_hint);
    history.hidden = !saved.length;
    historyList.replaceChildren();
    for (const item of saved) {
      const row = document.createElement("li");
      const title = responseLabels[item.action];
      const date = dateFormat.format(new Date(item.created_at));
      const label = item.current ? title : title + " · " + date;
      const select = button(label, "study-help-saved-button", savedFocus(item), () => show(item));
      select.setAttribute("aria-pressed", String(item.id === openId));
      select.setAttribute("aria-controls", "study-help-response");
      select.title = item.current ? "Saved " + date : "Earlier revision";
      row.append(select);
      historyList.append(row);
    }
    focusControl(focusedKey);
    clearTimeout(timer);
    if (next.pending && !document.hidden) timer = setTimeout(refresh, 2000);
    if (autoOpenId && !next.pending) {
      const item = saved.find(response => response.id === autoOpenId);
      autoOpenId = undefined;
      if (item) show(item, true);
    }
  }

  function showError(error) {
    if (error.code === "unavailable" && !state) return;
    root.hidden = false;
    if (["assistance_restricted", "unavailable", "inactive_statement"].includes(error.code)) {
      closeAnswer();
      history.hidden = true;
      actions.replaceChildren();
      controls.hidden = true;
      quota.replaceChildren();
      confirmation.hidden = true;
      confirmationData = undefined;
      state = undefined;
    }
    if (error.status) present(error.status);
    note(error.message || "Study help couldn’t be reached. Reload the page to try again.", "error");
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
    note("Requesting AI study help…", "loading");
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

  async function show(item, automatic = false) {
    if (busy || item.id === openId) return;
    statusRequest++;
    busy = true;
    try {
      const result = await request(root.dataset.revealUrl, {
        response_id: item.id, interaction_key: crypto.randomUUID(),
        automatic,
      });
      openId = item.id;
      returnFocus = savedFocus(item);
      answerSource = result.response.body;
      const level = !proof(item.action) && /^Hint \(Level ([1-4])\):[ \t]+/.exec(answerSource);
      find("[data-answer-title]").textContent = responseLabels[item.action] +
        (result.response.current ? "" : " · Earlier revision");
      answerLevel.hidden = !level;
      answerLevel.textContent = level ? "Level " + level[1] : "";
      copyFeedback.textContent = "";
      window.MathJax?.typesetClear?.([answerBody]);
      answerBody.textContent = level ? answerSource.slice(level[0].length) : answerSource;
      answer.hidden = false;
      present(result.status);
      find("[data-answer-title]").focus({preventScroll: false});
      const renderMath = () => window.MathJax?.typesetPromise?.([answerBody]).catch(() => {});
      if (window.MathJax?.typesetPromise) await renderMath();
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
    focusControl(returnFocus);
  });
  find("[data-copy]").addEventListener("click", async () => {
    if (!answerSource) return;
    const copiedId = openId;
    try {
      await navigator.clipboard.writeText(answerSource);
      if (openId === copiedId) copyFeedback.textContent = "Copied";
    } catch {
      if (openId === copiedId) copyFeedback.textContent = "Copy unavailable. Select the response to copy it.";
    }
  });
  find("[data-confirm]").addEventListener("click", () => {
    if (confirmationData) generate(confirmationData);
  });
  function cancel() {
    const action = confirmationData?.action;
    confirmationData = undefined;
    confirmation.hidden = true;
    focusControl(actionFocus(action));
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
