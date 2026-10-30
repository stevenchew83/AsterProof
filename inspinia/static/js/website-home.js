/* Keep the SVG illustration lightweight; load the optional 3D scene on request. */
(function () {
  "use strict";
  const root = document.querySelector("[data-geometry-src]");
  if (!root) return;
  const toggle = root.querySelector("[data-motion-toggle]");
  toggle.hidden = false;
  toggle.textContent = "Play motion";
  toggle.setAttribute("aria-label", "Play geometry animation");
  toggle.removeAttribute("aria-pressed");
  toggle.addEventListener("click", function () {
    toggle.disabled = true;
    const script = document.createElement("script");
    script.src = root.dataset.geometrySrc;
    script.onload = function () {
      toggle.disabled = false;
      toggle.hidden = root.dataset.geometryState !== "ready";
    };
    script.onerror = function () { toggle.hidden = true; };
    document.head.appendChild(script);
  }, {once: true});
}());
