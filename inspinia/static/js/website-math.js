/* Public math loads once. The homepage waits until its editor is used or preview is visible. */
(function () {
  "use strict";
  const source = document.currentScript;
  const lazy = source.hasAttribute("data-lazy-math");
  const editor = document.querySelector("[data-solution-preview]");
  let pending;
  function load() {
    if (pending) return pending;
    window.MathJax = {
      tex: {
        inlineMath: [["$", "$"], ["\\(", "\\)"]],
        displayMath: [["$$", "$$"], ["\\[", "\\]"]],
        processEscapes: true
      },
      options: {skipHtmlTags: ["script", "noscript", "style", "textarea", "pre", "code"]},
      // The writer owns its preview pass; scanning its initial markup repeats that work.
      startup: {typeset: !lazy && !editor}
    };
    if (editor) {
      // Keep the combined bundle's features, split into separate script tasks.
      window.MathJax.loader = {load: ["input/tex", "input/mml", "output/chtml", "ui/menu"]};
    }
    pending = new Promise(function (resolve, reject) {
      if (editor) window.MathJax.loader.failed = function (error) {
        // Components can fail before onload attaches to MathJax's startup promise.
        const startup = window.MathJax && window.MathJax.startup;
        if (startup && startup.promise) startup.promise.catch(reject);
        // The loader also tracks promises for dependencies provided by a component.
        window.MathJax.loader.ready().catch(reject);
        reject(error);
      };
      const script = document.createElement("script");
      script.src = editor ? source.dataset.previewMathSrc : source.dataset.mathSrc;
      script.async = true;
      script.onload = async function () {
        try {
          await window.MathJax.startup.promise;
          document.dispatchEvent(new Event("asterproof:math-ready"));
          resolve();
        } catch (error) { reject(error); }
      };
      script.onerror = reject;
      document.head.appendChild(script);
    }).catch(function () {
      // A CDN failure must not stop plain-text preview updates or PDF submission.
      window.MathJax = null;
    });
    window.AsterProofMathReady = pending;
    return pending;
  }
  function request() { load(); }
  if (!lazy) { request(); return; }
  if (!editor) return;
  editor.addEventListener("focusin", request, {once: true});
  editor.addEventListener("input", request, {once: true});
  const preview = editor.querySelector(".public-tool-preview");
  if (!window.IntersectionObserver) { request(); return; }
  const observer = new IntersectionObserver(function (entries) {
    if (entries.some(function (entry) { return entry.isIntersecting; })) {
      observer.disconnect();
      request();
    }
  });
  observer.observe(preview);
}());
