const assert = require('node:assert/strict');
const {readFileSync} = require('node:fs');
const {test} = require('node:test');
const vm = require('node:vm');

const template = readFileSync(require.resolve('../../inspinia/templates/pages/completion-record-list.html'), 'utf8');
const source = [...template.matchAll(/<script>([\s\S]*?)<\/script>/g)].at(-1)[1];
const record = {
  completion_id: 42, user_label: 'Ada Lovelace', user_email: 'ada@example.test', user_url: '/users/2/',
  problem_label: 'IMO 2026 P3', problem: 'P3', contest: 'IMO', year: 2026, topic: 'Algebra',
  problem_url: '/solutions/42/', areas: ['Inequalities and optimization', 'Equations and polynomials'],
  mohs: 0, status: 'checked', status_label: 'Checked', solution_status: 'published',
  solution_status_label: 'Published', completion_datetime: '2026-10-31 16:27',
  completion_date_sort: '2026-10-31T16:27:00+08:00', updated_at_sort: '2026-10-31T08:30:00Z',
  key_technique: 'Inversion', post_mortem: 'State the equality case.',
};
function table(width = 1440) {
  let options;
  const visibility = new Map();
  vm.runInNewContext(source, {
    document: {getElementById: id => id.endsWith('-data') ? {textContent: JSON.stringify([record])} : {addEventListener() {}}},
    window: {matchMedia: query => ({matches: width <= Number(query.match(/[\d.]+/)[0]), addEventListener() {}})},
    DataTable: function (_selector, config) {
      options = config;
      this.column = index => ({visible: visible => visibility.set(index, visible)});
      this.columns = {adjust: () => ({draw() {}})};
    },
  });
  function column(title) { return options.columns.find(item => item.title === title); }
  function render(title, type, overrides = {}) {
    const row = {...record, ...overrides};
    const definition = column(title);
    return definition.render(row[definition.data], type, row);
  }
  return {options, column, render, visibility};
}

test('problem leads the inventory while every existing field and latest-update order remain available', () => {
  const app = table();
  const titles = Array.from(app.options.columns, item => item.title);
  assert.ok(titles.indexOf('Problem') < titles.indexOf('User'));
  for (const title of ['Topic', 'Area', 'MOHS', 'Status', 'Completed', 'Solution']) assert.ok(titles.includes(title));
  assert.equal(app.options.columns[app.options.order[0][0]].data, 'updated_at_sort');
  assert.equal(app.render('MOHS', 'display'), '0');
  assert.ok(app.render('Problem', 'display').includes('class="completion-record-problem-code">2026 P3</span>'));
  const customLabel = app.render('Problem', 'display', {problem_label: 'A custom problem label'});
  assert.ok(customLabel.includes('A custom problem label'));
  assert.ok(!customLabel.includes('completion-record-problem-code'));
});

test('compact completion dates preserve full timestamps for sorting, filtering and accessible details', () => {
  const app = table();
  const html = app.render('Completed', 'display');
  assert.ok(html.includes('title="2026-10-31 16:27"'));
  assert.ok(html.includes('class="visually-hidden"> 16:27'));
  assert.equal(app.render('Completed', 'sort'), record.completion_date_sort);
  assert.equal(app.render('Completed', 'filter'), record.completion_datetime);
  assert.ok(app.render('Completed', 'display', {completion_datetime: 'Unknown'}).includes('Unknown'));
});

test('hidden mobile fields and secondary mapped areas remain in quick-find search', () => {
  const app = table(390);
  for (const title of ['MOHS', 'Status', 'Completed', 'Solution']) {
    assert.equal(app.visibility.get(app.options.columns.indexOf(app.column(title))), false);
  }
  const search = app.render('Loaded search', 'filter');
  for (const value of [record.areas[1], record.user_email, record.key_technique, record.post_mortem, 'Published']) {
    assert.ok(search.includes(value), value);
  }
});

test('row identity, status and date renderers escape untrusted text and attribute values', () => {
  const app = table();
  const unsafe = '\"><img src=x onerror=alert(1)>';
  const overrides = Object.fromEntries(['user_label', 'user_email', 'user_url', 'problem_label', 'problem_url',
    'status_label', 'solution_status_label', 'completion_datetime', 'completion_date_sort'].map(key => [key, unsafe]));
  for (const title of ['Problem', 'User', 'Status', 'Solution', 'Completed']) {
    const html = app.render(title, 'display', overrides);
    assert.ok(!html.includes('<img'), title);
    assert.ok(html.includes('&lt;img'), title);
  }
});
