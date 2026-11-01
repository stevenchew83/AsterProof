/* Estimated visible-page time and a fixed vocabulary of learning actions. */
(function () {
  "use strict";
  var element = document.getElementById("learning-activity-config");
  if (!element || window.top !== window.self) return;
  var config;
  try { config = JSON.parse(element.textContent); } catch (_) { return; }
  var endpoint = new URL(config.endpoint, location.href);
  if (endpoint.origin !== location.origin) return;
  var rules = config.rules || [];
  var generic = new Set(["submit_form", "open_page", "other_button"]);
  var clicks = {};
  var totalClicks = 0;
  var sequence = 0;
  var visibleMs = 0;
  var previous = performance.now();
  var visible = document.visibilityState === "visible";
  var paused = false;
  var stopped = false;
  var pending = null;
  var lastClicked = null;
  var lastClickAt = 0;

  function tick() {
    var now = performance.now();
    // Clamp gaps caused by device sleep or suspended browser execution.
    if (visible && !paused) visibleMs += Math.max(0, Math.min(now - previous, 15000));
    previous = now;
  }
  function flush() {
    if (stopped) return;
    tick();
    if (pending !== null) { window.clearTimeout(pending); pending = null; }
    sequence += 1;
    var body = JSON.stringify({token:config.token, sequence:sequence,
      visible_ms:Math.min(Math.round(visibleMs), 43200000), clicks:Object.assign({}, clicks)});
    // Cumulative snapshots are safe when unload and heartbeat requests race.
    window.fetch(endpoint.href, {method:"POST", credentials:"same-origin", keepalive:true,
      headers:{"Content-Type":"application/json", "X-CSRFToken":config.csrf}, body:body,
    }).then(function (response) {
      if (response.status === 400 || response.status === 401 || response.status === 403) stopped = true;
    }).catch(function () { /* The next snapshot includes any unsent measurements. */ });
  }
  function match(rule, control) { return rule.selector && control.matches(rule.selector); }
  function actionFor(control) {
    var rule = rules.find(function (item) { return !generic.has(item.key) && match(item, control); });
    if (rule) return rule.key;
    // Only compare against fixed labels. Never send DOM text, input values or hrefs.
    var label = (control.getAttribute("aria-label") || control.textContent || "").replace(/\s+/g," ").trim().toLowerCase();
    rule = rules.find(function (item) { return item.texts && item.texts.includes(label); });
    if (rule) return rule.key;
    rule = rules.find(function (item) { return generic.has(item.key) && match(item, control); });
    return rule ? rule.key : null;
  }
  function record(control) {
    if (stopped || !control || control.disabled || totalClicks >= 2000) return;
    if (!control.closest(".content-page,main,.problem-page")) return;
    var action = actionFor(control);
    if (!action) return;
    clicks[action] = (clicks[action] || 0) + 1;
    totalClicks += 1;
    if (pending === null) pending = window.setTimeout(flush, 800);
  }
  document.addEventListener("click", function (event) {
    if (event.isTrusted === false || !event.target || !event.target.closest) return;
    var control = event.target.closest("button,input[type=submit],[role=button],a.btn,summary");
    if (!control) return;
    lastClicked = control;
    lastClickAt = performance.now();
    record(control);
  }, true);
  document.addEventListener("submit", function (event) {
    if (event.isTrusted === false) return;
    var control = event.submitter;
    if (!(control === lastClicked && performance.now() - lastClickAt < 1000)) {
      if (control) record(control);
      else if (event.target.closest(".content-page,main,.problem-page") && totalClicks < 2000) {
        clicks.submit_form = (clicks.submit_form || 0) + 1;
        totalClicks += 1;
      }
    }
    flush();
  }, true);
  document.addEventListener("visibilitychange", function () {
    tick();
    visible = document.visibilityState === "visible";
    if (!visible) flush();
  });
  window.addEventListener("pagehide", function () { flush(); paused = true; });
  window.addEventListener("pageshow", function () {
    previous = performance.now(); paused = false; visible = document.visibilityState === "visible";
  });
  window.setInterval(tick, 5000);
  window.setInterval(function () { if (!paused && visible) flush(); }, 30000);
  flush();
})();
