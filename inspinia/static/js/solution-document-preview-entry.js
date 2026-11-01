"use strict";
const {renderDocument} = require("./solution-document-preview.js");

async function renderInto(container, source, config = {}) {
  const math = window.MathJax;
  if (math?.typesetClear) math.typesetClear([container]);
  const result = renderDocument(container, source, {...(window.ASTERPROOF_SOLUTION_MEDIA || {}), origin: location.origin, ...config});
  const ready = window.AsterProofMathReady || math?.startup?.promise;
  if (ready) { try { await ready; } catch (_) { /* Source remains visible. */ } }
  if (window.MathJax?.typesetPromise) { try { await window.MathJax.typesetPromise(result.scopes); } catch (_) { /* Source remains visible. */ } }
  return result;
}
function init() {
  document.querySelectorAll("[data-solution-document-source]").forEach(element => {
    if (element.dataset.documentReady) return;
    element.dataset.documentReady = "true";
    const source = element.textContent;
    element.classList.remove("tex2jax_ignore");
    renderInto(element, source);
  });
}
window.AsterProofSolutionDocument = {renderInto, init};
if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", init, {once: true});
else init();
window.addEventListener("asterproof:mathjax-ready", () => {
  document.querySelectorAll("[data-solution-document-source]").forEach(element => { if (window.MathJax?.typesetPromise) window.MathJax.typesetPromise(Array.from(element.querySelectorAll("[data-mathjax-scope]"))).catch(() => {}); });
});
