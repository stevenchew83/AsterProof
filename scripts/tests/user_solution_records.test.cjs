const assert = require('node:assert/strict');
const {readFileSync} = require('node:fs');
const {test} = require('node:test');
const vm = require('node:vm');

const template = readFileSync(require.resolve('../../inspinia/templates/pages/user-solution-record-list.html'), 'utf8');
const script = template.match(/<script>([\s\S]*?)<\/script>/)[1];
function loadConfig(showAiReviews) {
  const renderedScript = script.replace(
    /\{% if user_solution_record_show_ai_reviews %\}([\s\S]*?)(?:\{% else %\}([\s\S]*?))?\{% endif %\}/g,
    (_match, whenEnabled, whenDisabled) => showAiReviews ? whenEnabled : (whenDisabled ?? ''),
  );
  let config;
  vm.runInNewContext(renderedScript, {
    document: {getElementById: () => ({textContent: '[]'})},
    DataTable: function (_selector, options) {
      config = options;
      this.table = () => ({node: () => ({addEventListener() {}})});
      this.rows = () => ({every() {}});
    },
  });
  return config;
}
const config = loadConfig(false);
const row = {
  problem_label: 'IMO 2026 P2', title: 'Circle inversion', contest: 'IMO', year: 2026,
  problem: 'P2', topic: 'Geometry', mohs: 0, block_count: 1, summary_length: 42,
  user_label: 'Mary Cartwright', user_email: 'mary@example.test', user_url: '/users/2/',
  status: 'published', status_label: 'Published',
  published_at: '2026-10-30 12:00', published_at_sort: '2026-10-30T04:00:00+00:00',
  updated_at: '2026-10-31 16:27', updated_at_sort: '2026-10-31T08:27:00+00:00',
  solution_url: '/solutions/1/?solution=2#solution-2', archive_url: '/archive/#imo-p2', pdf_url: '/pdf/2/',
};
function render(field, type, overrides = {}) {
  const record = {...row, ...overrides};
  const definition = config.columns.find(column => column.data === field);
  return definition.render(record[field], type, record);
}

test('Topic precedes MOHS with and without AI review and the default date order is preserved', () => {
  assert.equal(render('problem_label', 'sort'), row.problem_label);
  assert.equal(render('updated_at', 'sort'), row.updated_at_sort);
  for (const tableConfig of [config, loadConfig(true)]) {
    const ordering = Array.from(tableConfig.order, ({name, dir}) => [
      tableConfig.columns.find(column => column.name === name).data, dir,
    ]);
    assert.deepEqual(ordering, [['published_at', 'desc'], ['updated_at', 'desc']]);
    const mohsIndex = tableConfig.columns.findIndex(column => column.data === 'mohs');
    assert.equal(tableConfig.columns[mohsIndex].title, 'MOHS');
    assert.equal(tableConfig.columns[mohsIndex - 1].title, 'Topic');
  }
  assert.equal(render('topic', 'display'), 'Geometry');
  assert.equal(render('topic', 'display', {topic: ''}), '—');
});

test('the MOHS column displays zero and unknown scores and sorts numerically', () => {
  assert.equal(render('mohs', 'display'), '0');
  assert.equal(render('mohs', 'display', {mohs: null}), '—');
  assert.equal(render('mohs', 'sort', {mohs: 12}), 12);
  assert.equal(render('mohs', 'sort', {mohs: null}), -1);
});

test('disclosed metadata stays searchable, including custom titles, emails and publication dates', () => {
  const search = render('problem_label', 'filter');
  for (const value of [row.title, row.topic, 'MOHS 0', '1 block', '42 summary chars']) {
    assert.ok(search.includes(value), value);
  }
  assert.ok(render('user_label', 'filter').includes(row.user_email));
  assert.equal(render('published_at', 'filter'), row.published_at);
  const html = render('problem_label', 'display');
  assert.ok(html.includes('<details'));
  assert.ok(html.includes('<dt>MOHS</dt><dd>0</dd>'));
  assert.ok(html.includes(row.user_email));
  assert.ok(html.includes(row.solution_url.replaceAll('&', '&amp;')));
  assert.ok(render('problem_label', 'display', {mohs: ''}).includes('<dt>MOHS</dt><dd>—</dd>'));
});

test('all display renderers escape user-controlled text and attribute values', () => {
  const unsafe = '\"><img src=x onerror=alert(1)>';
  const overrides = Object.fromEntries(['problem_label', 'title', 'topic', 'mohs', 'user_label', 'user_email',
    'user_url', 'status_label', 'published_at', 'published_at_sort', 'updated_at', 'updated_at_sort',
    'solution_url', 'archive_url', 'pdf_url']
    .map(key => [key, unsafe]));
  for (const {data} of config.columns) {
    const html = render(data, 'display', overrides);
    assert.ok(!html.includes('<img'), `column ${data}`);
    assert.ok(html.includes('&lt;img'), `column ${data}`);
  }
});

test('drafts and published rows have distinct accessible status text and optional actions', () => {
  assert.ok(render('status_label', 'display').includes('ti-circle-check'));
  assert.ok(render('status_label', 'display', {status: 'draft', status_label: 'Draft'}).includes('ti-pencil'));
  const html = render('solution_url', 'display');
  for (const label of ['Open solution', 'Open archive problem', 'Download Evan PDF']) {
    assert.ok(html.includes(`aria-label="${label}"`));
  }
  const optional = render('solution_url', 'display', {archive_url: '', pdf_url: ''});
  assert.ok(!optional.includes('Open archive problem'));
  assert.ok(!optional.includes('Download Evan PDF'));
});
