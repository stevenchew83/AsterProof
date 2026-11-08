/* Format-neutral completion and selection helpers shared by mathematical editors. */
"use strict";

const core = require("./solution-document-core.js");
const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;
const snippets = {
  frac: "\\frac{${}}{${}}", dfrac: "\\dfrac{${}}{${}}", sqrt: "\\sqrt{${}}", binom: "\\binom{${}}{${}}",
  text: "\\text{${}}", textbf: "\\textbf{${}}", textit: "\\textit{${}}", emph: "\\emph{${}}", mathbb: "\\mathbb{${}}", mathcal: "\\mathcal{${}}", operatorname: "\\operatorname{${}}",
  section: "\\section*{${}}", subsection: "\\subsection*{${}}", paragraph: "\\paragraph{${}}",
};

function completionSpec(source, position) {
  const before = source.slice(0, position);
  const environment = /\\(begin|end)\{([A-Za-z*]*)$/.exec(before);
  if (environment) {
    const nearest = core.unclosedEnvironment(before.slice(0, environment.index));
    const names = environment[1] === "end" ? nearest ? [nearest] : [] : core.ENVIRONMENTS;
    return {from: environment.index, to: source[position] === "}" ? position + 1 : position, names, mode: environment[1], prefix: environment[2]};
  }
  const command = /\\([A-Za-z]*)$/.exec(before);
  return command ? {from: command.index, to: position, names: [...Object.keys(snippets), ...core.COMMANDS, "begin", "end"], mode: "command", prefix: command[1]} : null;
}

function managedImageSnippet(id, alt = "") {
  if (!UUID.test(String(id))) throw new Error("The upload returned an invalid managed image identity.");
  const text = String(alt).replace(/\\/g, "\\\\").replace(/\]/g, "\\]").replace(/[\r\n]/g, " ");
  return "![" + text + "](asset:" + String(id).toLowerCase() + ")";
}

function collectAssetMetadata(source, previous = []) {
  const byID = new Map((Array.isArray(previous) ? previous : []).filter(value => value && UUID.test(String(value.id))).map(value => [String(value.id).toLowerCase(), value]));
  const referenced = new Map();
  const pattern = /!\[((?:\\.|[^\]\\])*)\]\(\s*asset:([0-9a-f-]{36})\s*\)/gi;
  for (const match of String(source).matchAll(pattern)) {
    const id = match[2].toLowerCase();
    if (!UUID.test(id)) continue;
    const existing = byID.get(id) || {};
    referenced.set(id, {id, alt: match[1].replace(/\\([\\\]])/g, "$1"), caption: existing.caption || "", credit: existing.credit || ""});
  }
  return Array.from(referenced.values());
}

function setImageDescription(source, id, alt) {
  if (!UUID.test(String(id))) throw new Error("Choose a managed image identity.");
  const pattern = new RegExp("!\\[((?:\\\\.|[^\\]\\\\])*)\\]\\(\\s*asset:" + id + "\\s*\\)", "gi");
  return String(source).replace(pattern, () => managedImageSnippet(id, alt));
}

function safeEndpoint(value, origin) {
  const url = new URL(value, origin);
  if (url.origin !== origin || !["https:", "http:"].includes(url.protocol) || url.username || url.password) throw new Error("Use a same-origin learning endpoint.");
  return url.href;
}

function operationID(crypto) {
  if (crypto?.randomUUID) return crypto.randomUUID();
  if (!crypto?.getRandomValues) throw new Error("Secure save identifiers are unavailable; use the normal form save.");
  const bytes = crypto.getRandomValues(new Uint8Array(16));
  bytes[6] = (bytes[6] & 15) | 64; bytes[8] = (bytes[8] & 63) | 128;
  const hex = Array.from(bytes, value => value.toString(16).padStart(2, "0")).join("");
  return [hex.slice(0, 8), hex.slice(8, 12), hex.slice(12, 16), hex.slice(16, 20), hex.slice(20)].join("-");
}

function canonicalJSON(value) {
  function ordered(item) {
    if (Array.isArray(item)) return item.map(ordered);
    if (item && typeof item === "object") {
      const result = Object.create(null);
      for (const key of Object.keys(item).sort()) result[key] = ordered(item[key]);
      return result;
    }
    return item;
  }
  return JSON.stringify(ordered(value));
}

module.exports = {completionSpec, snippets, managedImageSnippet, collectAssetMetadata, setImageDescription, safeEndpoint, operationID, canonicalJSON,
  mapOffset: core.mapOffset, mapUploadBookmark: core.mapUploadBookmark, uploadReplacementRange: core.uploadReplacementRange};
