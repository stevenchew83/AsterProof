const assert = require('node:assert/strict');
const {readFileSync} = require('node:fs');
const {test} = require('node:test');
const vm = require('node:vm');

test('all shared proofs capture their LaTeX before MathJax changes later papers', async () => {
  const template = readFileSync(require.resolve('../../inspinia/templates/solutions/partials/shared-solution-math.html'), 'utf8');
  const bootstrap = Array.from(template.matchAll(/<script>([\s\S]*?)<\/script>/g)).at(-1)[1];
  const nodes = ['$x^2+y^2$', '$BD/DC=AB/AC$', '$n^2\\equiv 1$'].map(textContent => ({textContent}));
  const papers = nodes.map(node => ({querySelectorAll: () => [node]}));
  const document = {
    querySelector: () => papers[0],
    querySelectorAll: selector => selector === '.public-shared-paper' ? papers : nodes,
  };
  const captured = [];
  const window = {AsterProofSolutionLatex: {initSolutionListBodies(root) {
    // The hybrid renderer captures source synchronously; MathJax may then
    // auto-typeset every paper before an awaited initializer is called again.
    captured.push(...Array.from(root.querySelectorAll('.solution-block-body-latex'), node => node.textContent));
    return Promise.resolve().then(() => { nodes.forEach(node => { node.textContent = 'Rendered mathematics'; }); });
  }}};
  vm.runInNewContext(bootstrap, {document, window});
  await window.asterProofSharedMathReady;
  assert.deepEqual(captured, ['$x^2+y^2$', '$BD/DC=AB/AC$', '$n^2\\equiv 1$']);
});
