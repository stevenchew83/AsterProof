(() => {
  "use strict";
  if (!window.fetch || !window.AbortController || !window.SubmitEvent || !("submitter" in SubmitEvent.prototype)) return;

  const pending = new WeakSet();
  const unconfirmed = "Could not confirm the change. Reload the page to check its current state.";

  // The solution reader's reviewed template keeps its existing list picker and form.
  for (const form of document.querySelectorAll("form.problem-list-add-form")) {
    form.dataset.inlineAction = "";
    form.dataset.inlineActionRegion = "";
    const feedback = document.createElement("p");
    feedback.dataset.inlineActionFeedback = "";
    feedback.className = "small mb-0";
    feedback.setAttribute("role", "status");
    feedback.setAttribute("aria-atomic", "true");
    feedback.tabIndex = -1;
    form.append(feedback);
  }

  function replaceContent(content, html, fallback) {
    const active = document.activeElement;
    const restoreFocus = content.contains(active);
    const focusId = active?.id || active?.closest("[data-inline-action-focus]")?.dataset.inlineActionFocus;
    const disclosures = new Map(
      Array.from(content.querySelectorAll("details[id]"), node => [node.id, node.open]),
    );
    const values = Array.from(content.querySelectorAll("[data-inline-action-preserve-value][id]"), input => [
      input.id, input.value,
    ]);
    content.innerHTML = html;
    for (const [id, open] of disclosures) {
      const node = document.getElementById(id);
      if (content.contains(node)) node.open = open;
    }
    for (const [id, value] of values) {
      const input = document.getElementById(id);
      if (content.contains(input)) input.value = value;
    }
    if (restoreFocus) {
      const target = focusId ? document.getElementById(focusId) : null;
      const next = content.contains(target) ? target : content.querySelector("[data-inline-action-success-focus]");
      (next || fallback).focus({preventScroll: true});
    }
  }

  async function readPage(response) {
    if (!response.ok || !response.headers.get("content-type")?.includes("text/html")) {
      throw new Error(unconfirmed);
    }
    const page = new DOMParser().parseFromString(await response.text(), "text/html");
    const error = page.querySelector("[data-inline-action-page-error]");
    if (error) throw new Error(error.textContent.trim());
    return page;
  }

  async function readRedirectedPage(response, region, signal) {
    if (!response.redirected) throw new Error(unconfirmed);
    const landed = new URL(response.url);
    const current = new URL(window.location.href);
    if (landed.origin !== current.origin) throw new Error(unconfirmed);
    if (landed.pathname !== current.pathname) return {url: landed.href};

    let page = await readPage(response);
    // Some native redirects omit the current pagination query.
    if (landed.search !== current.search) {
      const currentPage = await fetch(current, {
        credentials: "same-origin",
        headers: {Accept: "text/html"},
        redirect: "manual",
        signal,
      });
      page = await readPage(currentPage);
    }
    const content = page.getElementById(region.id)?.querySelector(":scope > [data-inline-action-content]");
    if (!content) throw new Error("Reload the page to see the current state.");
    return {
      html: content.innerHTML,
      message: content.querySelector("[data-inline-action-success-focus]") ? "" : "Saved.",
    };
  }

  document.addEventListener("submit", async event => {
    const form = event.target;
    if (event.defaultPrevented || !form.matches("form[data-inline-action]")) return;

    const region = form.closest("[data-inline-action-region]");
    if (!region) return;
    const feedback = region.querySelector(":scope > [data-inline-action-feedback]");
    if (!feedback) return;
    const pageMode = form.dataset.inlineAction === "page";
    const submitter = event.submitter;
    const action = submitter?.getAttribute("formaction") || form.getAttribute("action");
    const endpoint = new URL(action || window.location.href, window.location.href);
    if (endpoint.origin !== window.location.origin) return;

    event.preventDefault();
    if (pending.has(region)) return;
    const data = new FormData(form);
    if (submitter?.name) data.append(submitter.name, submitter.value);

    pending.add(region);
    region.setAttribute("aria-busy", "true");
    const buttons = Array.from(region.querySelectorAll("form[data-inline-action] button[type=submit]"))
      .filter(button => !button.hasAttribute("aria-disabled"));
    buttons.forEach(button => button.setAttribute("aria-disabled", "true"));
    feedback.textContent = "Saving…";
    feedback.classList.remove("text-danger", "text-success");
    const controller = new AbortController();
    const timeout = window.setTimeout(() => controller.abort(), 15000);
    try {
      const response = await fetch(endpoint, {
        method: "POST",
        body: data,
        credentials: "same-origin",
        headers: {Accept: pageMode ? "text/html" : "application/json"},
        redirect: pageMode ? "follow" : "manual",
        signal: controller.signal,
      });
      if (response.type === "opaqueredirect") {
        throw new Error("Your session may have changed. Reload the page before continuing.");
      }
      const json = response.headers.get("content-type")?.includes("application/json");
      let result = json ? await response.json() : {};
      if (!response.ok) {
        const message = response.status === 403 ? "This action is no longer allowed. Reload the page." :
          response.status === 404 ? "This item is no longer available. Reload the page." :
            unconfirmed;
        throw new Error(result.message || message);
      }
      if (pageMode) result = await readRedirectedPage(response, region, controller.signal);
      else if (!json) throw new Error(unconfirmed);
      const url = result.url && new URL(result.url, window.location.href);
      if (url && url.origin !== window.location.origin) throw new Error("Unexpected response. Reload the page.");
      const content = region.querySelector(":scope > [data-inline-action-content]");
      if (url && result.html === undefined) {
        window.location.assign(url.href);
        return;
      }
      if (content) {
        if (typeof result.html !== "string") throw new Error("Reload the page to see the current state.");
        if (url && url.pathname === window.location.pathname) {
          url.hash = window.location.hash;
          window.history.replaceState(window.history.state, "", url.href);
        }
        replaceContent(content, result.html, feedback);
      }
      feedback.textContent = result.message ?? "Saved.";
      feedback.classList.add("text-success");
    } catch (error) {
      feedback.textContent = controller.signal.aborted || error instanceof TypeError ?
        unconfirmed : error.message;
      feedback.classList.add("text-danger");
    } finally {
      window.clearTimeout(timeout);
      buttons.forEach(button => button.removeAttribute("aria-disabled"));
      region.removeAttribute("aria-busy");
      pending.delete(region);
    }
  });
})();
