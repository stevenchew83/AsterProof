const assert = require("node:assert/strict");
const {test} = require("node:test");
const {learningMathConfig} = require("../../inspinia/static/js/learning-math.js");
const {completionSpec} = require("../../inspinia/static/js/math-document-editor.js");

test("learning math only loads mathematical packages and blocks author extension/HTML attributes", () => {
  const config = learningMathConfig();
  assert.deepEqual(config.tex.packages, ["base", "ams"]);
  assert.ok(config.loader.load.includes("ui/safe"));
  assert.ok(config.loader.load.includes("a11y/assistive-mml"));
  for (const name of ["[tex]/require", "[tex]/autoload", "[tex]/html"]) assert.ok(!config.loader.load.includes(name));
  assert.deepEqual(config.options.safeOptions.allow, {URLs: "none", classes: "none", cssIDs: "none", styles: "none"});
  assert.ok(Object.values(config.options.safeOptions.safeProtocols).every(value => value === false));
  assert.ok(config.options.skipHtmlTags.includes("pre"));
});

test("extracted completion spec preserves solution command and paired-environment ranges", () => {
  assert.equal(completionSpec("Text \\fr", 8).prefix, "fr");
  const source = "\\begin{align*}\nx=1\n\\end{al}";
  const result = completionSpec(source, source.length - 1);
  assert.equal(result.mode, "end");
  assert.deepEqual(result.names, ["align*"]);
  assert.equal(result.to, source.length);
});
