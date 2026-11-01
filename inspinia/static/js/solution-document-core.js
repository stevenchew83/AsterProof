/* Shared, deliberately bounded LaTeX-body vocabulary. This never interprets HTML. */
"use strict";

const STRUCTURAL_ENVIRONMENTS = ["claim", "proof", "fact", "remark", "itemize", "enumerate"];
const MATH_ENVIRONMENTS = ["align", "align*", "aligned", "alignedat", "gather", "gather*", "gathered", "equation", "equation*", "split", "cases", "matrix", "pmatrix", "bmatrix", "Bmatrix", "vmatrix", "Vmatrix", "smallmatrix"];
const ENVIRONMENTS = [...STRUCTURAL_ENVIRONMENTS, ...MATH_ENVIRONMENTS];
const COMMANDS = ["alpha", "beta", "gamma", "delta", "epsilon", "theta", "lambda", "mu", "pi", "rho", "sigma", "phi", "omega", "sum", "prod", "int", "lim", "infty", "leq", "geq", "neq", "equiv", "pmod", "cdot", "times", "in", "subseteq", "forall", "exists", "implies", "iff", "angle", "triangle", "perp", "parallel", "sin", "cos", "tan", "log", "ln", "gcd", "ldots", "cdots", "dots", "quad", "qquad"];
const MANAGED_IMAGE = /^solution_body_images\/[0-9a-f]{32}\.(?:png|jpe?g|gif|webp)$/i;

function escaped(source, position) {
  let count = 0;
  while (position > 0 && source[--position] === "\\") count++;
  return count % 2 === 1;
}

function group(source, start, opening = "{", closing = "}") {
  if (source[start] !== opening) return null;
  let depth = 1;
  for (let index = start + 1; index < source.length; index++) {
    if (source[index] === "\\") { index++; continue; }
    if (source[index] === "%") { const newline = source.indexOf("\n", index); if (newline < 0) return null; index = newline; continue; }
    if (source[index] === opening) depth++;
    if (source[index] === closing && --depth === 0) return {value: source.slice(start + 1, index), end: index + 1};
  }
  return null;
}

function closingEnvironment(source, start, name) {
  const pattern = /\\(begin|end)\s*\{([A-Za-z*]+)\}/g;
  pattern.lastIndex = start;
  let depth = 1;
  for (let match; (match = pattern.exec(source));) {
    if (escaped(source, match.index) || match[2] !== name) continue;
    depth += match[1] === "begin" ? 1 : -1;
    if (!depth) return {start: match.index, end: pattern.lastIndex};
  }
  return null;
}

function parseDocument(source) {
  source = String(source || "");
  const warnings = new Set();
  function parse(value, depth = 0) {
    if (depth > 32) {
      warnings.add("Deeply nested content is shown as source.");
      return [{kind: "raw", text: value}];
    }
    const nodes = [];
    let buffer = "";
    const flush = () => { if (buffer) nodes.push({kind: "text", text: buffer}); buffer = ""; };
    for (let index = 0; index < value.length;) {
      const tail = value.slice(index);
      if (value[index] === "%" && !escaped(value, index)) {
        const newline = value.indexOf("\n", index);
        index = newline < 0 ? value.length : newline;
        continue;
      }
      const delimiter = tail.startsWith("\\[") ? ["\\[", "\\]"] : tail.startsWith("\\(") ? ["\\(", "\\)"] : tail.startsWith("$$") ? ["$$", "$$"] : tail.startsWith("$") ? ["$", "$"] : null;
      if (delimiter) {
        let end = value.indexOf(delimiter[1], index + delimiter[0].length);
        while (end >= 0 && escaped(value, end)) end = value.indexOf(delimiter[1], end + delimiter[1].length);
        if (end >= 0) {
          flush();
          const next = end + delimiter[1].length;
          nodes.push({kind: "math", text: value.slice(index, next), display: delimiter[0] === "\\[" || delimiter[0] === "$$"});
          index = next;
          continue;
        }
        warnings.add("An equation delimiter is unfinished; its source is preserved.");
      }
      const begin = /^\\begin\s*\{([A-Za-z*]+)\}/.exec(tail);
      if (begin) {
        const end = closingEnvironment(value, index + begin[0].length, begin[1]);
        if (end) {
          flush();
          const whole = value.slice(index, end.end);
          if (MATH_ENVIRONMENTS.includes(begin[1])) nodes.push({kind: "math", text: whole, display: true});
          else if (STRUCTURAL_ENVIRONMENTS.includes(begin[1])) {
            let contentStart = index + begin[0].length;
            let title = "";
            const optional = group(value, contentStart, "[", "]");
            if (optional) { title = optional.value; contentStart = optional.end; }
            const children = parse(value.slice(contentStart, end.start), depth + 1);
            nodes.push({kind: "environment", name: begin[1], title, children});
          } else {
            warnings.add("Some commands are shown as source because preview does not support them.");
            nodes.push({kind: "raw", text: whole});
          }
          index = end.end;
          continue;
        }
        warnings.add("An environment is unfinished; its source is preserved.");
      }
      const image = /^\\includegraphics\s*(\[[^\]]*\])?\s*\{([^}]*)\}/.exec(tail);
      if (image) {
        flush();
        const path = image[2].trim();
        const width = image[1] && /^\[width=(0?\.\d+|1(?:\.0+)?)\\linewidth\]$/.exec(image[1]);
        if (MANAGED_IMAGE.test(path) && (!image[1] || width)) nodes.push({kind: "image", path, width: width ? Math.min(100, Number(width[1]) * 100) : 90});
        else { nodes.push({kind: "raw", text: image[0]}); warnings.add("Only uploaded solution images are displayed in preview."); }
        index += image[0].length;
        continue;
      }
      const command = /^\\(section\*?|subsection\*?|paragraph\*?|textbf|textit|emph|texttt|textrm|textsf|textbackslash|textasciitilde|textasciicircum)\s*/.exec(tail);
      if (command) {
        const contents = group(value, index + command[0].length);
        if (contents) {
          flush();
          const literal = {textbackslash: "\\", textasciitilde: "~", textasciicircum: "^"}[command[1]];
          if (literal) nodes.push({kind: "text", text: literal});
          else nodes.push({kind: /^(?:sub)?section|^paragraph/.test(command[1]) ? "heading" : "style", name: command[1], children: parse(contents.value, depth + 1)});
          index = contents.end;
          continue;
        }
      }
      if (/^\\item(?:\s|\[|$)/.test(tail)) {
        flush();
        index += 5;
        const label = group(value, index, "[", "]");
        nodes.push({kind: "item", label: label ? label.value : ""});
        if (label) index = label.end;
        continue;
      }
      if (value[index] === "\\" && /[{}$%&#_]/.test(value[index + 1] || "\0")) {
        buffer += value[index + 1]; index += 2; continue;
      }
      if (tail.startsWith("\\\\")) { buffer += "\n"; index += 2; continue; }
      if (value[index] === "\\" && /^[A-Za-z]/.test(value[index + 1] || "")) {
        const unknown = /^\\[A-Za-z@]+\*?/.exec(tail)[0];
        flush(); nodes.push({kind: "raw", text: unknown}); index += unknown.length;
        warnings.add("Some commands are shown as source because preview does not support them.");
        continue;
      }
      buffer += value[index++];
    }
    flush();
    return nodes;
  }
  return {nodes: parse(source), warnings: Array.from(warnings)};
}

function unclosedEnvironment(source) {
  const stack = [];
  // Remove comments, keeping escaped percent signs and escaped control sequences.
  source = String(source || "").split("\n").map(line => {
    for (let i = 0; i < line.length; i++) if (line[i] === "%" && !escaped(line, i)) return line.slice(0, i);
    return line;
  }).join("\n");
  const pattern = /\\(begin|end)\s*\{([A-Za-z*]+)\}/g;
  for (let match; (match = pattern.exec(source));) {
    if (escaped(source, match.index)) continue;
    if (match[1] === "begin") stack.push(match[2]);
    else if (stack[stack.length - 1] === match[2]) stack.pop();
  }
  return stack[stack.length - 1] || "";
}

function imageSnippet(path) {
  if (!MANAGED_IMAGE.test(String(path || ""))) throw new Error("The upload returned an invalid image reference.");
  return "\\includegraphics[width=0.9\\linewidth]{" + path + "}";
}

function mapOffset(position, previous, next) {
  let start = 0;
  while (start < previous.length && start < next.length && previous[start] === next[start]) start++;
  let oldEnd = previous.length, newEnd = next.length;
  while (oldEnd > start && newEnd > start && previous[oldEnd - 1] === next[newEnd - 1]) { oldEnd--; newEnd--; }
  if (position <= start) return position;
  return position >= oldEnd ? position + newEnd - oldEnd : newEnd;
}

function mapUploadBookmark(bookmark, changes) {
  const empty = bookmark.from === bookmark.to;
  bookmark.from = changes.mapPos(bookmark.from, -1);
  bookmark.to = changes.mapPos(bookmark.to, empty ? -1 : 1);
}

function uploadReplacementRange(bookmark, source) {
  // Replace the originally selected text only if it is still untouched.
  return {from: bookmark.from, to: source.slice(bookmark.from, bookmark.to) === bookmark.selected ? bookmark.to : bookmark.from};
}

function escapeLiteralText(value) {
  const escapes = {"\\": "\\textbackslash{}", "{": "\\{", "}": "\\}", "$": "\\$", "&": "\\&", "#": "\\#", "%": "\\%", "_": "\\_", "~": "\\textasciitilde{}", "^": "\\textasciicircum{}"};
  return Array.from(String(value || ""), character => escapes[character] || character).join("");
}

function convertLegacyBlock(block, types = {}) {
  const type = types[String(block.block_type)] || (block.slug ? {slug: block.slug, label: block.label || ""} : {slug: "plain", label: ""});
  let body = block.body_source || "", title = block.title || "";
  if (block.body_format === "plain_text") { body = escapeLiteralText(body); title = escapeLiteralText(title); }
  const environment = (name, source, heading = "") => "\\begin{" + name + "}" + (heading ? "[" + heading + "]" : "") + "\n" + source + "\n\\end{" + name + "}";
  const join = values => values.filter(Boolean).join("\n\n");
  if (type.slug === "plain") return join([title, body]);
  if (type.slug === "claim") return title && body ? environment("claim", title) + "\n\n" + environment("proof", body) : title || body ? environment("claim", title || body) : "";
  if (type.slug === "proof") return title || body ? environment("proof", body, title) : "";
  if (["observation", "remark"].includes(type.slug)) return environment(type.slug === "observation" ? "fact" : "remark", join([title, body]));
  const caption = title || escapeLiteralText(type.label);
  if (["section", "part"].includes(type.slug)) return "\\" + (type.slug === "section" ? "section" : "subsection") + "*{" + caption + "}" + (body ? "\n\n" + body : "");
  if (["case", "subcase", "idea", "computation", "conclusion"].includes(type.slug)) return "\\textbf{" + caption.replace(/\.+$/, "") + ".}" + (body ? "\n\n" + body : "");
  return "\\paragraph{" + escapeLiteralText([type.label, block.title || ""].filter(Boolean).join(" — ")) + "}" + (body ? "\n\n" + body : "");
}

module.exports = {ENVIRONMENTS, COMMANDS, MANAGED_IMAGE, parseDocument, unclosedEnvironment, imageSnippet, mapOffset, mapUploadBookmark, uploadReplacementRange, escapeLiteralText, convertLegacyBlock};
