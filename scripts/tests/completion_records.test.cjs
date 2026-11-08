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
  solution_status_label: 'Published', solution_url: '/solutions/entries/42/', completion_datetime: '2026-10-31 16:27',
  ai_review: {label: 'Draft ready', score: 0, url: '/solutions/entries/42/#ai-review'},
  completion_date_sort: '2026-10-31T16:27:00+08:00', updated_at_sort: '2026-10-31T08:30:00Z',
  key_technique: 'Inversion', post_mortem: 'State the equality case.',
};
function table(width = 1440) {
  let options;
  let onGridClick;
  let detailHtml;
  const visibility = new Map();
  const grid = {hasAttribute: name => name === 'data-ai-reviews', addEventListener: (_event, listener) => onGridClick = listener};
  vm.runInNewContext(source, {
    document: {getElementById: id => id.endsWith('-data') ? {textContent: JSON.stringify([record])} : grid},
    window: {matchMedia: query => ({matches: width <= Number(query.match(/[\d.]+/)[0]), addEventListener() {}})},
    DataTable: function (_selector, config) {
      options = config;
      this.column = index => ({visible: visible => visibility.set(index, visible)});
      this.columns = {adjust: () => ({draw() {}})};
      const child = html => ({show() { detailHtml = html; }});
      child.isShown = () => false;
      this.row = () => ({data: () => record, child});
    },
  });
  function column(title) { return options.columns.find(item => item.title === title); }
  function render(title, type, overrides = {}) {
    const row = {...record, ...overrides};
    const definition = column(title);
    return definition.render(row[definition.data], type, row);
  }
  function expandDetails() {
    const row = {classList: {add() {}}};
    const button = {closest: () => row, querySelector: () => null, getAttribute: () => null, setAttribute() {}};
    onGridClick({target: {closest: () => button}});
    return detailHtml;
  }
  return {options, column, render, visibility, expandDetails};
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
  for (const title of ['Topic', 'Area', 'MOHS', 'Status', 'Completed', 'Solution']) {
    assert.equal(app.visibility.get(app.options.columns.indexOf(app.column(title))), false);
  }
  assert.match(app.render('User', 'display'), /completion-record-mobile-status d-sm-none">Checked/);
  const search = app.render('Loaded search', 'filter');
  for (const value of [record.areas[1], record.user_email, record.key_technique, record.post_mortem, 'Published']) {
    assert.ok(search.includes(value), value);
  }
});

test('AI review follows Solution on desktop and appears in expanded mobile details', () => {
  const desktop = table();
  const reviewColumn = desktop.options.columns.indexOf(desktop.column('AI review'));
  assert.equal(desktop.options.columns[reviewColumn - 1].title, 'Solution');
  assert.equal(desktop.visibility.get(reviewColumn), true);
  assert.equal(desktop.render('AI review', 'sort'), 0);
  assert.match(desktop.render('AI review', 'display', {ai_review: null}), /No solution to review/);

  const mobile = table(390);
  assert.equal(mobile.visibility.get(reviewColumn), false);
  assert.match(mobile.expandDetails(), /<dt>AI review<\/dt>.*href="\/solutions\/entries\/42\/#ai-review".*>0\/7 · Draft ready<\/span>.*progress-bar/);
  assert.match(mobile.render('Loaded search', 'filter'), /0\/7 · Draft ready/);
});

test('AI review bars scale to seven and distinguish zero from an unscored review', () => {
  const app = table();
  for (const [score, tone] of [[0, 'danger'], [4, 'warning'], [6, 'success'], [7, 'success']]) {
    const ai_review = {...record.ai_review, score};
    const html = app.render('AI review', 'display', {ai_review});
    const fill = html.match(/progress-bar bg-(\w+)" style="width:([\d.]+)%/);
    assert.equal(fill[1], tone);
    assert.ok(Math.abs(Number(fill[2]) * 7 / 100 - score) < 0.001);
    assert.ok(html.includes(`${score}/7 · Draft ready`));
    assert.equal(app.render('AI review', 'sort', {ai_review}), score);
  }
  const ai_review = {...record.ai_review, score: null, label: 'Not reviewed'};
  const html = app.render('AI review', 'display', {ai_review});
  assert.match(html, /Not reviewed/);
  assert.doesNotMatch(html, /progress-bar|\/7/);
  assert.equal(app.render('AI review', 'sort', {ai_review}), -1);
});

test('solution status links directly to the solution when a URL is available', () => {
  const app = table();
  assert.match(app.render('Solution', 'display'), /href="\/solutions\/entries\/42\/".*>Published<\/a>/);
  assert.match(table(390).expandDetails(), /<dt>Solution<\/dt><dd><a .*href="\/solutions\/entries\/42\/".*>Published<\/a>/);
  const html = app.render('Solution', 'display', {solution_url: '', solution_status: '', solution_status_label: 'No solution'});
  assert.match(html, /No solution/);
  assert.doesNotMatch(html, /href=/);
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
