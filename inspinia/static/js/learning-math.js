/* Learning-only TeX policy: mathematical packages, no author HTML or extension loading. */
"use strict";

function learningMathConfig() {
  return {
    loader: {load: ["input/tex-base", "[tex]/ams", "output/chtml", "ui/menu", "ui/safe", "a11y/assistive-mml"]},
    tex: {
      packages: ["base", "ams"], inlineMath: [["$", "$"], ["\\(", "\\)"]],
      displayMath: [["$$", "$$"], ["\\[", "\\]"]], processEscapes: true,
      maxBuffer: 64000, maxMacros: 1000,
    },
    options: {
      skipHtmlTags: ["script", "noscript", "style", "textarea", "pre", "code"],
      safeOptions: {
        allow: {URLs: "none", classes: "none", cssIDs: "none", styles: "none"},
        safeProtocols: {http: false, https: false, file: false, javascript: false, data: false},
      },
    },
    startup: {typeset: false},
  };
}

function installLearningMath(global, document) {
  let pending;
  let renderQueue = Promise.resolve();
  function ready() {
    if (pending) return pending;
    if (global.MathJax?.startup?.document) {
      pending = Promise.reject(new Error("A different mathematics policy is already active. Source remains available."));
      pending.catch(() => {});
      return pending;
    }
    global.MathJax = learningMathConfig();
    pending = new Promise((resolve, reject) => {
      const script = document.createElement("script");
      script.src = "https://cdn.jsdelivr.net/npm/mathjax@3.2.2/es5/startup.js";
      script.async = true;
      script.onload = () => Promise.resolve(global.MathJax?.startup?.promise).then(resolve, reject);
      script.onerror = () => reject(new Error("Mathematical rendering is unavailable; your source is preserved."));
      global.MathJax.loader.failed = reject;
      document.head.append(script);
    });
    return pending;
  }
  function typeset(element) {
    renderQueue = renderQueue.catch(() => {}).then(async () => {
      await ready();
      if (!element.isConnected) return;
      global.MathJax.typesetClear?.([element]);
      await global.MathJax.typesetPromise([element]);
    });
    return renderQueue;
  }
  global.AsterProofLearningMath = {ready, typeset};
  const initialize = () => document.querySelectorAll("[data-learning-math]").forEach(element => {
    typeset(element).catch(() => {});
  });
  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", initialize, {once: true});
  else initialize();
  return global.AsterProofLearningMath;
}

if (typeof window !== "undefined") installLearningMath(window, document);
module.exports = {learningMathConfig, installLearningMath};
