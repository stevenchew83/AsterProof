const assert = require('node:assert/strict');
const {readFileSync} = require('node:fs');
const {test} = require('node:test');
const vm = require('node:vm');

const template = readFileSync(require.resolve('../../inspinia/templates/pages/user-solution-record-list.html'), 'utf8');
const script = template.match(/<script>([\s\S]*?)<\/script>/)[1];
let config;
vm.runInNewContext(script, {
  document: {getElementById: () => ({textContent: '[]'})},
  DataTable: function (_selector, options) { config = options; },
});
const row = {
  problem_label: 'IMO 2026 P2', title: 'Circle inversion', contest: 'IMO', year: 2026,
  problem: 'P2', topic: 'Geometry', mohs: 0, block_count: 1, summary_length: 42,
  user_label: 'Mary Cartwright', user_email: 'mary@example.test', user_url: '/users/2/',
  status: 'published', status_label: 'Published', published_at: '2026-10-30 12:00',
  updated_at: '2026-10-31 16:27', updated_at_sort: '2026-10-31T08:27:00+00:00',
  solution_url: '/solutions/1/?solution=2#solution-2', archive_url: '/archive/#imo-p2', pdf_url: '/pdf/2/',
};
function render(column, type, overrides = {}) {
  const record = {...row, ...overrides};
  const definition = config.columns[column];
  return definition.render(record[definition.data], type, record);
}

test('problem sorting uses its label and default order uses the updated date column', () => {
  assert.equal(render(0, 'sort'), row.problem_label);
  assert.equal(render(3, 'sort'), row.updated_at_sort);
  assert.equal(config.columns[config.order[0][0]].data, 'updated_at');
});

test('disclosed metadata stays searchable, including custom titles, emails and publication dates', () => {
  const search = render(0, 'filter');
  for (const value of [row.title, row.topic, 'MOHS 0', '1 block', '42 summary chars', row.published_at]) {
    assert.ok(search.includes(value), value);
  }
  assert.ok(render(1, 'filter').includes(row.user_email));
  const html = render(0, 'display');
  assert.ok(html.includes('<details'));
  assert.ok(html.includes('<dt>MOHS</dt><dd>0</dd>'));
  assert.ok(html.includes(row.user_email));
  assert.ok(html.includes(row.solution_url.replaceAll('&', '&amp;')));
  assert.ok(render(0, 'display', {mohs: ''}).includes('<dt>MOHS</dt><dd>—</dd>'));
});

test('all display renderers escape user-controlled text and attribute values', () => {
  const unsafe = '\"><img src=x onerror=alert(1)>';
  const overrides = Object.fromEntries(['problem_label', 'title', 'topic', 'user_label', 'user_email',
    'user_url', 'status_label', 'updated_at', 'updated_at_sort', 'solution_url', 'archive_url', 'pdf_url']
    .map(key => [key, unsafe]));
  for (let column = 0; column < config.columns.length; column++) {
    const html = render(column, 'display', overrides);
    assert.ok(!html.includes('<img'), `column ${column}`);
    assert.ok(html.includes('&lt;img'), `column ${column}`);
  }
});

test('drafts and published rows have distinct accessible status text and optional actions', () => {
  assert.ok(render(2, 'display').includes('ti-circle-check'));
  assert.ok(render(2, 'display', {status: 'draft', status_label: 'Draft'}).includes('ti-pencil'));
  const html = render(4, 'display');
  for (const label of ['Open solution', 'Open archive problem', 'Download Evan PDF']) {
    assert.ok(html.includes(`aria-label="${label}"`));
  }
  const optional = render(4, 'display', {archive_url: '', pdf_url: ''});
  assert.ok(!optional.includes('Open archive problem'));
  assert.ok(!optional.includes('Download Evan PDF'));
});
