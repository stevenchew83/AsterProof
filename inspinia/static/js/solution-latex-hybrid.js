/**
 * Hybrid render for solution block bodies: MathJax on text spans, <img> for allowlisted
 * \includegraphics{solution_body_images/<hex>.<ext>} paths.
 */
(function () {
  "use strict";

  // Allow optional whitespace after \includegraphics and before { so small edits
  // (or rare browser formatting) still match; otherwise the whole line falls through
  // to MathJax, which renders \includegraphics as a link and misparses _ in paths.
  var INCLUDE_RE = /\\includegraphics\s*(\[[^\]]*\])?\s*\{([^}]*)\}/g;
  var ALLOWED_PATH = /^solution_body_images\/[0-9a-f]{32}\.(png|jpg|jpeg|gif|webp)$/i;

  function normalizePath(path) {
    if (!path || typeof path !== "string") return "";
    var s = path.trim().replace(/\\/g, "/").replace(/^\//, "");
    if (s.indexOf("..") !== -1 || s.indexOf("//") !== -1 || s.indexOf(":") !== -1) return "";
    return s;
  }

  function isAllowedPath(path) {
    var n = normalizePath(path);
    return ALLOWED_PATH.test(n);
  }

  function joinMediaUrl(baseUrl, path) {
    var base = baseUrl || "";
    var p = normalizePath(path);
    if (!p) return "";
    if (!base.endsWith("/")) base += "/";
    if (p.startsWith("/")) p = p.slice(1);
    try {
      return new URL(p, base).href;
    } catch (e) {
      return base + p;
    }
  }

  function parseIncludeGraphics(text) {
    var src = text == null ? "" : String(text);
    var parts = [];
    var last = 0;
    var m;
    INCLUDE_RE.lastIndex = 0;
    while ((m = INCLUDE_RE.exec(src)) !== null) {
      if (m.index > last) {
        parts.push({ type: "text", content: src.slice(last, m.index) });
      }
      parts.push({
        type: "img",
        bracket: m[1] || "",
        path: (m[2] || "").trim(),
        raw: m[0],
      });
      last = INCLUDE_RE.lastIndex;
    }
    if (last < src.length) {
      parts.push({ type: "text", content: src.slice(last) });
    }
    return parts;
  }

  function buildBodyFragment(text, baseUrl) {
    var frag = document.createDocumentFragment();
    var parts = parseIncludeGraphics(text);
    if (!parts.length) {
      parts.push({ type: "text", content: text == null ? "" : String(text) });
    }
    parts.forEach(function (p) {
      if (p.type === "text") {
        var span = document.createElement("span");
        span.setAttribute("data-mathjax-scope", "true");
        span.className = "solution-latex-text";
        span.textContent = p.content;
        frag.appendChild(span);
        return;
      }
      if (isAllowedPath(p.path)) {
        var img = document.createElement("img");
        img.className = "solution-body-image img-fluid d-block my-2";
        img.alt = "";
        img.loading = "lazy";
        img.src = joinMediaUrl(baseUrl, p.path);
        frag.appendChild(img);
        return;
      }
      var fb = document.createElement("span");
      fb.setAttribute("data-mathjax-scope", "true");
      fb.className = "solution-latex-text";
      fb.textContent = p.raw;
      frag.appendChild(fb);
    });
    return frag;
  }

  function mathJaxReady() {
    return new Promise(function (resolve) {
      function hasMj() {
        return window.MathJax && typeof window.MathJax.typesetPromise === "function";
      }
      if (hasMj()) {
        resolve();
        return;
      }
      window.addEventListener(
        "asterproof:mathjax-ready",
        function () {
          resolve();
        },
        { once: true },
      );
      var n = 0;
      var t = window.setInterval(function () {
        n += 1;
        if (hasMj()) {
          window.clearInterval(t);
          resolve();
        } else if (n > 200) {
          window.clearInterval(t);
          resolve();
        }
      }, 25);
    });
  }

  function typesetElement(el) {
    if (!el) return Promise.resolve();
    return mathJaxReady().then(function () {
      if (!window.MathJax || typeof window.MathJax.typesetPromise !== "function") return;
      var targets = Array.from(el.querySelectorAll("[data-mathjax-scope]"));
      if (!targets.length) return;
      if (typeof window.MathJax.typesetClear === "function") {
        window.MathJax.typesetClear(targets);
      }
      return window.MathJax.typesetPromise(targets).catch(function () {});
    });
  }

  /**
   * Replace el contents with hybrid rendering; returns Promise (MathJax).
   */
  function renderInto(el, text, baseUrl) {
    if (!el) return Promise.resolve();
    var prev = Array.from(el.querySelectorAll("[data-mathjax-scope]"));
    if (prev.length && window.MathJax && typeof window.MathJax.typesetClear === "function") {
      window.MathJax.typesetClear(prev);
    }
    el.textContent = "";
    el.removeAttribute("data-mathjax-scope");
    el.appendChild(buildBodyFragment(text, baseUrl));
    return typesetElement(el);
  }

  function initSolutionListBodies(root, baseUrl) {
    if (!root) return Promise.resolve();
    var nodes = root.querySelectorAll(".solution-block-body-latex");
    var chain = Promise.resolve();
    nodes.forEach(function (node) {
      var raw = node.textContent || "";
      chain = chain.then(function () {
        return renderInto(node, raw, baseUrl);
      });
    });
    return chain;
  }

  window.AsterProofSolutionLatex = {
    isAllowedPath: isAllowedPath,
    parseIncludeGraphics: parseIncludeGraphics,
    renderInto: renderInto,
    initSolutionListBodies: initSolutionListBodies,
    mathJaxReady: mathJaxReady,
    insertGraphicsAtCursor: function (textarea, canonicalPath) {
      if (!textarea || !canonicalPath) return;
      var snippet = "\\includegraphics[width=0.9\\linewidth]{" + canonicalPath + "}";
      var start = textarea.selectionStart;
      var end = textarea.selectionEnd;
      var val = textarea.value;
      textarea.value = val.slice(0, start) + snippet + val.slice(end);
      var pos = start + snippet.length;
      textarea.selectionStart = textarea.selectionEnd = pos;
      textarea.dispatchEvent(new Event("input", { bubbles: true }));
    },
  };
})();
