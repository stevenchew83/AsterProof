(() => {
  "use strict";
  const panel = document.querySelector("[data-newsletter-progress]");
  let running = false;
  let stopping = false;
  let pauseUrl;
  let csrf;

  const show = (data, text) => {
    if (!panel) return;
    panel.hidden = false;
    panel.querySelector("[data-newsletter-status]").textContent = text || data.status;
    if (data.counts) {
      const count = data.counts;
      panel.querySelector("[data-newsletter-result]").textContent = `${count.processed} of ${count.total} processed · ${count.accepted} accepted · ${count.skipped} skipped · ${count.failed + count.unknown} need attention`;
      panel.querySelector(".progress-bar").style.width = `${count.percent}%`;
      panel.querySelector("[role=progressbar]").setAttribute("aria-valuenow", String(count.percent));
    }
    if (data.campaign_url) panel.querySelector("[data-newsletter-campaign-link]").href = data.campaign_url;
    panel.querySelector("[data-newsletter-stop]").hidden = !running;
  };

  const post = async (url, body) => {
    const response = await fetch(url, {
      method: "POST", credentials: "same-origin", body,
      headers: { "Accept": "application/json", "X-CSRFToken": csrf },
    });
    const data = await response.json();
    if (data.error || !response.ok) {
      show(data, data.error || "Sending stopped. Check delivery history before continuing.");
      const error = new Error("Newsletter request stopped");
      error.newsletterHandled = true;
      throw error;
    }
    return data;
  };

  document.querySelectorAll("form[data-newsletter-send]").forEach(form => {
    form.addEventListener("submit", async event => {
      event.preventDefault();
      if (running || !form.reportValidity()) return;
      running = true;
      stopping = false;
      csrf = form.querySelector("[name=csrfmiddlewaretoken]").value;
      const button = form.querySelector("button[type=submit]");
      button.disabled = true;
      show({}, "Preparing to send…");
      try {
        let data = await post(form.action, new FormData(form));
        pauseUrl = data.pause_url;
        show(data, "Sending · Keep this page open");
        while (data.status === "sending" && !stopping) {
          await new Promise(resolve => setTimeout(resolve, 3200));
          if (stopping) break;
          const body = new FormData();
          body.set("csrfmiddlewaretoken", csrf);
          data = await post(data.step_url, body);
          show(data, data.status === "completed" ? "Campaign completed" : "Sending · Keep this page open");
        }
        if (data.status === "completed") {
          running = false;
          window.location.assign(data.campaign_url);
        }
        else if (!stopping) show(data, "Sending paused. Review the campaign before continuing.");
      } catch (error) {
        if (panel && !error.newsletterHandled) {
          show({}, "Sending stopped. Check delivery history before continuing.");
        }
        if (panel) {
          panel.querySelector("[data-newsletter-result]").textContent = "No request will be retried automatically. Check delivery history before continuing.";
        }
      } finally {
        running = false;
        button.disabled = false;
        if (panel) panel.querySelector("[data-newsletter-stop]").hidden = true;
      }
    });
  });

  document.querySelector("[data-newsletter-stop]")?.addEventListener("click", async () => {
    stopping = true;
    if (!pauseUrl) return;
    try {
      const body = new FormData();
      body.set("csrfmiddlewaretoken", csrf);
      const data = await post(pauseUrl, body);
      show(data, "Paused. Any email already in progress can finish.");
    } catch (_error) {
      show({}, "Sending stopped here. Check the campaign before continuing.");
    }
  });

  window.addEventListener("beforeunload", event => {
    if (running && !stopping) { event.preventDefault(); event.returnValue = ""; }
  });
  document.querySelectorAll("[data-preview-size]").forEach(button => {
    button.addEventListener("click", () => {
      document.querySelector("[data-preview-stage]")?.classList.toggle("is-mobile", button.dataset.previewSize === "mobile");
      document.querySelectorAll("[data-preview-size]").forEach(item => item.setAttribute("aria-pressed", String(item === button)));
    });
  });
  document.querySelector("[data-newsletter-draft]")?.addEventListener("input", () => {
    const caption = document.querySelector("[data-preview-caption]");
    if (caption) caption.textContent = "Save to refresh preview";
  });
})();
