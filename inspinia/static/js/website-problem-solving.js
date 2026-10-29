/* Public, in-memory writing example. Account solutions use the authenticated editor. */
(function () {
  "use strict";

  const demo = document.querySelector("[data-solving-demo]");
  if (!demo) return;

  const sources = Array.from(demo.querySelectorAll("[data-demo-source]"));
  const previews = sources.map(function (source) {
    return demo.querySelector('[data-demo-preview="' + source.dataset.demoSource + '"]');
  });
  const initialValues = sources.map(function (source) { return source.value; });
  const status = demo.querySelector("[data-demo-preview-status]");
  const reset = demo.querySelector("[data-demo-reset]");
  let timer;
  let pending = Promise.resolve();

  function render() {
    // Serialize MathJax work so fast edits cannot leave an older preview on screen.
    pending = pending.then(async function () {
      const math = window.MathJax;
      if (math && math.startup && math.startup.promise) await math.startup.promise;
      if (math && math.typesetClear) math.typesetClear(previews);
      sources.forEach(function (source, index) {
        // Student input is text, never HTML.
        previews[index].textContent = source.value;
      });
      if (math && math.typesetPromise) {
        await math.typesetPromise(previews);
        status.textContent = "Updates as you write";
      } else {
        status.textContent = "Text preview · math rendering unavailable";
      }
    }).catch(function () {
      status.textContent = "Preview unavailable · your text is still here";
    });
  }

  sources.forEach(function (source) {
    source.addEventListener("input", function () {
      clearTimeout(timer);
      timer = setTimeout(render, 180);
    });
  });
  reset.hidden = false;
  reset.addEventListener("click", function () {
    clearTimeout(timer);
    sources.forEach(function (source, index) { source.value = initialValues[index]; });
    render();
    sources[0].focus();
  });
  // The shared MathJax script is deferred and may still be loading at this point.
  if (document.readyState === "complete") render();
  else window.addEventListener("load", render, { once: true });
}());
