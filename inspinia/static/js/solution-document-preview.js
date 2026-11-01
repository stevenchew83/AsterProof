"use strict";

const {parseDocument, MANAGED_IMAGE} = require("./solution-document-core.js");

function imageUrl(path, config) {
  if (!MANAGED_IMAGE.test(path)) return "";
  const prefix = String(config.mediaUrlPrefix || config.baseUrl || "");
  if (!prefix) return "";
  try {
    const base = new URL(prefix.endsWith("/") ? prefix : prefix + "/", config.origin || "https://asterproof.invalid/");
    if (!["http:", "https:"].includes(base.protocol)) return "";
    const url = new URL(path, base);
    return prefix.startsWith("/") ? url.pathname : url.href;
  } catch (_) { return ""; }
}

function renderDocument(container, source, config = {}) {
  const document = container.ownerDocument;
  const parsed = parseDocument(source);
  const scopes = [];
  const labels = {claim: "Claim", proof: "Proof", fact: "Observation", remark: "Remark"};
  function append(parent, nodes) {
    for (const node of nodes) {
      if (node.kind === "text") { parent.appendChild(document.createTextNode(node.text)); continue; }
      if (node.kind === "raw" || node.kind === "item") {
        const raw = document.createElement("span");
        raw.className = "solution-source-fallback tex2jax_ignore";
        raw.textContent = node.text || "\\item" + (node.label ? "[" + node.label + "]" : "");
        parent.appendChild(raw);
        continue;
      }
      if (node.kind === "math") {
        const math = document.createElement(node.display ? "div" : "span");
        math.className = "solution-document-math";
        math.dataset.mathjaxScope = "true";
        math.textContent = node.text;
        scopes.push(math);
        parent.appendChild(math);
        continue;
      }
      if (node.kind === "image") {
        const url = imageUrl(node.path, config);
        if (!url) {
          const raw = document.createElement("span");
          raw.className = "solution-source-fallback tex2jax_ignore";
          raw.textContent = "\\includegraphics{" + node.path + "}";
          parent.appendChild(raw);
          continue;
        }
        const image = document.createElement("img");
        image.className = "solution-body-image";
        image.src = url;
        image.alt = "Solution diagram";
        image.loading = "lazy";
        image.style.width = node.width + "%";
        parent.appendChild(image);
        continue;
      }
      if (node.kind === "style" || node.kind === "heading") {
        const tag = node.kind === "heading" ? (node.name.startsWith("subsection") ? "h4" : node.name.startsWith("paragraph") ? "h5" : "h3") : ({textbf: "strong", textit: "em", emph: "em", texttt: "code", textrm: "span", textsf: "span"}[node.name] || "span");
        const element = document.createElement(tag);
        if (node.kind === "heading") element.className = "solution-document-heading";
        append(element, node.children);
        parent.appendChild(element);
        continue;
      }
      if (node.kind === "environment") {
        if (["itemize", "enumerate"].includes(node.name)) {
          const list = document.createElement(node.name === "enumerate" ? "ol" : "ul");
          list.className = "solution-document-list";
          let item = null;
          for (const child of node.children) {
            if (child.kind === "item") {
              item = document.createElement("li");
              if (child.label) { const label = document.createElement("strong"); label.textContent = child.label + " "; item.appendChild(label); }
              list.appendChild(item);
            } else if (item) append(item, [child]);
            else if (child.kind !== "text" || child.text.trim()) {
              item = document.createElement("li"); list.appendChild(item); append(item, [child]);
            }
          }
          parent.appendChild(list);
          continue;
        }
        const section = document.createElement("section");
        section.className = "solution-document-environment solution-document-" + node.name;
        const label = document.createElement("div");
        label.className = "solution-document-environment-label";
        label.textContent = labels[node.name] + (node.title ? " · " : "");
        if (node.title) append(label, parseDocument(node.title).nodes);
        section.appendChild(label);
        const body = document.createElement("div");
        append(body, node.children);
        section.appendChild(body);
        parent.appendChild(section);
      }
    }
  }
  const fragment = document.createDocumentFragment();
  append(fragment, parsed.nodes);
  container.replaceChildren(fragment);
  container.classList.add("solution-document-rendered");
  return {warnings: parsed.warnings, scopes};
}

module.exports = {renderDocument, imageUrl};
