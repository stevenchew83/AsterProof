const assert = require('node:assert/strict');
const {test} = require('node:test');
const {EditorState} = require('@codemirror/state');
const {nextSnippetField} = require('@codemirror/autocomplete');
const {deleteGroupBackward} = require('@codemirror/commands');
const {parseDocument, escapeLiteralText, convertLegacyBlock, unclosedEnvironment, imageSnippet, mapOffset, mapUploadBookmark, uploadReplacementRange} = require('../../inspinia/static/js/solution-document-core.js');
const {completions, completionSpec, createEditorState} = require('../../inspinia/static/js/solution-document-editor.js');
const {decode, recoveryKey, TTL} = require('../../inspinia/static/js/solution-document-recovery.js');
const fixtures = require('./fixtures/solution-document-conformance.json');

function text(nodes) { return nodes.map(node => node.text || (node.children ? text(node.children) : '')).join(''); }

for (const fixture of fixtures) test('legacy conversion conformance: ' + fixture.name, () => {
  assert.equal(convertLegacyBlock(fixture.block), fixture.source);
  assert.equal(parseDocument(fixture.source).warnings.length, 0);
});

test('claim statements and proofs form separate, safely renderable environments', () => {
  const source = convertLegacyBlock({slug: 'claim', title: '$n$ is even.', body_source: 'Write $n=2k$.'});
  const parsed = parseDocument(source);
  assert.deepEqual(parsed.nodes.filter(node => node.kind === 'environment').map(node => node.name), ['claim', 'proof']);
  assert.deepEqual(parsed.warnings, []);
  assert.equal(parsed.nodes[0].children.filter(node => node.kind === 'math')[0].text, '$n$');
});

test('converted plain text stays literal even when it resembles executable LaTeX', () => {
  const original = '\\begin{claim} $x$ <img src=x onerror=alert(1)> 50% & {n}_#~^';
  const parsed = parseDocument(escapeLiteralText(original));
  assert.ok(parsed.nodes.every(node => node.kind === 'text'));
  assert.equal(text(parsed.nodes), original);
  assert.deepEqual(parsed.warnings, []);
});

test('nested lists, prose formatting and legacy headings retain semantic structure', () => {
  const parsed = parseDocument('\\paragraph{A \\textbf{claim}}\n\\begin{enumerate}\n\\item First\n\\item Second \\begin{itemize}\\item Nested\\end{itemize}\n\\end{enumerate}');
  assert.equal(parsed.nodes[0].kind, 'heading');
  assert.equal(parsed.nodes[0].children[1].kind, 'style');
  const list = parsed.nodes.find(node => node.name === 'enumerate');
  assert.equal(list.children.filter(node => node.kind === 'item').length, 2);
  assert.equal(list.children.find(node => node.name === 'itemize').children[0].kind, 'item');
});

test('unknown and unfinished constructs retain readable source with a warning', () => {
  const unknown = '\\begin{unknown}<script>alert(1)</script>\\end{unknown}';
  assert.equal(parseDocument(unknown).nodes[0].text, unknown);
  assert.equal(parseDocument('Before \\begin{proof}missing end').warnings.length > 0, true);
  assert.equal(text(parseDocument('Before $unfinished').nodes), 'Before $unfinished');
});

test('managed image parser rejects arbitrary URLs, traversal and unbounded options', () => {
  const path = 'solution_body_images/' + 'a'.repeat(32) + '.png';
  assert.equal(parseDocument(imageSnippet(path)).nodes[0].kind, 'image');
  for (const bad of ['https://example.com/image.png', '../secrets', 'javascript:alert(1)', 'solution_body_images/../x.png']) {
    assert.throws(() => imageSnippet(bad));
    assert.equal(parseDocument('\\includegraphics{' + bad + '}').nodes[0].kind, 'raw');
  }
  assert.equal(parseDocument('\\includegraphics[width=10000\\linewidth]{' + path + '}').nodes[0].kind, 'raw');
  assert.equal(parseDocument('% \\includegraphics{' + path + '}\nText').nodes.some(node => node.kind === 'image'), false);
});

test('end suggestions follow the innermost unclosed environment and ignore comments', () => {
  const source = '\\begin{proof}\n% \\begin{claim}\n\\begin{align*}x=1\\end{align*}\n\\end{';
  assert.equal(unclosedEnvironment(source), 'proof');
  assert.deepEqual(completionSpec(source, source.length).names, ['proof']);
  const state = EditorState.create({doc: source});
  assert.equal(completions({state, pos: source.length}).options[0].apply, '\\end{proof}');
});

test('generic begin completion links both names through typing and snippet navigation', () => {
  let state = createEditorState('\\beg');
  state = state.update({selection: {anchor: state.doc.length}}).state;
  const result = completions({state, pos: state.doc.length});
  const completion = result.options.find(value => value.label === '\\begin');
  const editor = {get state() { return state; }, dispatch(transaction) { state = transaction.state; }};
  completion.apply(editor, completion, result.from, result.to);
  assert.equal(state.selection.ranges.length, 2);
  let name = '';
  for (const character of 'proof') {
    name += character;
    state = state.update(state.replaceSelection(character)).state;
    assert.equal(state.doc.toString(), '\\begin{' + name + '}\n  \n\\end{' + name + '}');
  }
  assert.equal(deleteGroupBackward(editor), true);
  state = state.update(state.replaceSelection('claim')).state;
  assert.equal(state.doc.toString(), '\\begin{claim}\n  \n\\end{claim}');
  assert.equal(nextSnippetField(editor), true);
  state = state.update(state.replaceSelection('Body')).state;
  assert.equal(state.doc.toString(), '\\begin{claim}\n  Body\n\\end{claim}');
});

test('fraction completion has empty navigable fields and remains one undoable transaction', () => {
  let state = EditorState.create({doc: '\\fra', selection: {anchor: 4}});
  const result = completions({state, pos: 4});
  const completion = result.options.find(value => value.label === '\\frac');
  const editor = {get state() { return state; }, dispatch(transaction) { state = transaction.state; }};
  completion.apply(editor, completion, result.from, result.to);
  assert.equal(state.doc.toString(), '\\frac{}{}');
  assert.equal(state.selection.main.from, 6);
  assert.equal(nextSnippetField(editor), true);
  assert.equal(state.selection.main.from, 8);
});

test('environment completion consumes the existing brace and pairs the same name', () => {
  const source = '\\begin{ali}';
  let state = EditorState.create({doc: source, selection: {anchor: source.length - 1}});
  const result = completions({state, pos: source.length - 1});
  const completion = result.options.find(value => value.label === '\\begin{align*}');
  completion.apply({get state() { return state; }, dispatch(transaction) { state = transaction.state; }}, completion, result.from, result.to);
  assert.equal(state.doc.toString(), '\\begin{align*}\n  \n\\end{align*}');
});

test('fallback upload bookmarks track edits before the insertion point', () => {
  assert.equal(mapOffset(6, 'BeforeAfter', 'New BeforeAfter'), 10);
  assert.equal(mapOffset(6, 'BeforeAfter', 'BeforeTypedAfter'), 6);
  assert.equal(mapOffset(6, 'BeforeAfter', 'BefAfter'), 3);
});

test('an asynchronous image upload keeps its intended insertion point through CodeMirror edits', () => {
  let state = EditorState.create({doc: 'BeforeAfter'});
  const bookmark = {from: 6, to: 6, selected: ''};
  for (const changes of [{from: 0, insert: 'Prefix '}, {from: 13, insert: 'typed'}]) {
    const transaction = state.update({changes});
    mapUploadBookmark(bookmark, transaction.changes); state = transaction.state;
  }
  const replacement = uploadReplacementRange(bookmark, state.doc.toString());
  const result = state.update({changes: {...replacement, insert: '[image]'}}).state.doc.toString();
  assert.equal(result, 'Prefix Before[image]typedAfter');
});

test('completing an upload never deletes new writing inside the original selection', () => {
  let state = EditorState.create({doc: 'BeforeAfter'});
  const bookmark = {from: 6, to: 11, selected: 'After'};
  const transaction = state.update({changes: {from: 8, insert: 'new'}});
  mapUploadBookmark(bookmark, transaction.changes); state = transaction.state;
  const replacement = uploadReplacementRange(bookmark, state.doc.toString());
  assert.equal(state.update({changes: {...replacement, insert: '[image]'}}).state.doc.toString(), 'Before[image]Afnewter');
});

test('recovery is scoped by account and problem and rejects expiry or invalid data', () => {
  assert.notEqual(recoveryKey('a', 'same'), recoveryKey('b', 'same'));
  assert.notEqual(recoveryKey('a', 'one'), recoveryKey('a', 'two'));
  const now = 1000000000;
  const saved = {version: 2, savedAt: now, expiresAt: now + TTL, document: {body_source: '$x$', fields: {title: 'A', pdf_show_date: false}}};
  assert.deepEqual(decode(JSON.stringify(saved), now).document, saved.document);
  assert.equal(decode(JSON.stringify(saved), now + TTL), null);
  assert.equal(decode(JSON.stringify({...saved, expiresAt: now + TTL + 1}), now), null);
  assert.equal(decode(JSON.stringify({...saved, document: {body_source: '$x$', fields: {title: {html: 'x'}}}}), now), null);
});
