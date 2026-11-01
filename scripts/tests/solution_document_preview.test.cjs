const assert = require('node:assert/strict');
const {test} = require('node:test');
const {renderDocument, imageUrl} = require('../../inspinia/static/js/solution-document-preview.js');

function dom() {
  const document = {createElement: tag => node(tag), createTextNode: text => node('#text', text), createDocumentFragment: () => node('#fragment')};
  function node(tagName, text = '') {
    return {tagName, ownerDocument: document, children: [], dataset: {}, style: {}, classList: {add() {}},
      appendChild(child) { if (child.tagName === '#fragment') this.children.push(...child.children); else this.children.push(child); },
      replaceChildren(child) { this.children = []; this.appendChild(child); },
      get textContent() { return text + this.children.map(child => child.textContent).join(''); },
      set textContent(value) { text = value; this.children = []; },
    };
  }
  return node('div');
}
function descendants(node) { return [node, ...node.children.flatMap(descendants)]; }

test('source containing HTML is emitted as text, never as an executable element', () => {
  const container = dom();
  renderDocument(container, '<script>alert(1)</script><img src=x onerror=alert(1)>');
  assert.equal(container.textContent, '<script>alert(1)</script><img src=x onerror=alert(1)>');
  assert.equal(descendants(container).some(node => ['script', 'img'].includes(node.tagName)), false);
});

test('math scopes include only explicit mathematics, keeping unsupported source out of MathJax', () => {
  const container = dom();
  const result = renderDocument(container, 'Prose $x$ \\unknown{x} \\[y=1\\]');
  assert.deepEqual(result.scopes.map(node => node.textContent), ['$x$', '\\[y=1\\]']);
  assert.equal(result.warnings.length > 0, true);
});

test('nested list output uses real list items and claim proof remain separate', () => {
  const container = dom();
  renderDocument(container, '\\begin{claim}Claim\\end{claim}\\begin{proof}\\begin{enumerate}\\item A\\item B\\end{enumerate}\\end{proof}');
  const elements = descendants(container);
  assert.equal(elements.filter(node => node.tagName === 'section').length, 2);
  assert.equal(elements.filter(node => node.tagName === 'ol').length, 1);
  assert.equal(elements.filter(node => node.tagName === 'li').length, 2);
});

test('image resolution accepts only managed paths through a safe configured media prefix', () => {
  const path = 'solution_body_images/' + 'b'.repeat(32) + '.png';
  assert.equal(imageUrl(path, {mediaUrlPrefix: '/media/'}), '/media/' + path);
  assert.equal(imageUrl(path, {mediaUrlPrefix: 'https://storage.example/media/'}), 'https://storage.example/media/' + path);
  assert.equal(imageUrl(path, {mediaUrlPrefix: 'javascript:alert(1)'}), '');
  assert.equal(imageUrl('../secret', {mediaUrlPrefix: '/media/'}), '');
  const container = dom();
  renderDocument(container, '\\includegraphics{' + path + '}', {mediaUrlPrefix: '/media/'});
  const image = descendants(container).find(node => node.tagName === 'img');
  assert.equal(image.src, '/media/' + path);
  assert.equal(image.style.width, '90%');
});
