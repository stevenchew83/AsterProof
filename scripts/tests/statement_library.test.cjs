const assert = require('node:assert/strict');
const {readFileSync} = require('node:fs');
const {test} = require('node:test');
const vm = require('node:vm');

const template = readFileSync(require.resolve('../../inspinia/templates/pages/problem-statement-list.html'), 'utf8');
const script = [...template.matchAll(/<script>([\s\S]*?)<\/script>/g)]
  .find(match => match[1].includes('new DataTable("#problem-statements-table"'))[1]
  .replace('{{ csrf_token|escapejs }}', 'synthetic-csrf-token');
let config;
const element = {textContent: '[]', addEventListener() {}, querySelectorAll: () => []};
vm.runInNewContext(script, {
  document: {getElementById: () => element},
  DataTable: function (_selector, options) { config = options; },
});
const statement = {
  contest_year_problem: 'Canada National Olympiad 1991 P5',
  statement_detail_url: '/dashboard/problem-statements/statement-id/',
  solution_start_url: '/solutions/statements/statement-id/write/',
  is_linked: false,
  user_completion_state_kind: 'unsolved', user_completion_display: 'Unsolved',
  user_completion_state_label: 'Unsolved', user_completion_sort: '0',
};

test('new uploads render a CSRF-protected start form on each table draw', () => {
  for (let draw = 0; draw < 2; draw++) {
    const html = config.columns[0].render(null, 'display', statement);
    assert.ok(html.includes(`<form method="post" action="${statement.solution_start_url}"`));
    assert.ok(html.includes('name="csrfmiddlewaretoken" value="synthetic-csrf-token"'));
    assert.ok(html.includes(`aria-label="Start solution for ${statement.contest_year_problem}"`));
    assert.ok(html.includes('type="submit"'));
    assert.ok(html.includes('Open statement'));
  }
});

test('linked rows retain their existing solution destination', () => {
  const html = config.columns[0].render(null, 'display', {
    ...statement, is_linked: true, solution_start_url: '',
    problem_destination_url: '/solutions/problems/problem-id/', problem_destination_label: 'View',
  });
  assert.ok(html.includes('href="/solutions/problems/problem-id/"'));
  assert.ok(!html.includes('<form'));
});

test('unlinked statement completion shows unsolved, solved or unknown-date status', () => {
  const render = row => config.columns[2].render(null, 'display', row);
  assert.ok(render(statement).includes('Unsolved'));
  assert.ok(!render(statement).includes('Not linked'));
  const row = {...statement, user_completion_state_kind: 'unknown',
    user_completion_display: 'Unknown date', user_completion_sort: '1'};
  assert.ok(render(row).includes('Unknown date'));
  assert.equal(config.columns[2].render(null, 'sort', row), '1');
  assert.ok(render({...row, user_completion_state_kind: 'solved',
    user_completion_display: '2026-11-01'}).includes('2026-11-01'));
});

test('start forms escape problem labels and action attributes', () => {
  const html = config.columns[0].render(null, 'display', {
    ...statement, contest_year_problem: '\"><img src=x onerror=alert(1)>',
    solution_start_url: '/write/?x="&y=1',
  });
  assert.ok(!html.includes('<img'));
  assert.ok(html.includes('&lt;img'));
  assert.ok(html.includes('action="/write/?x=&quot;&amp;y=1"'));
});

test('record-only problems retain distinct taxonomy dialogs across table redraws', () => {
  const rows = ['first', 'second'].map(id => ({
    problem_uuid: id, statement_uuid: '', has_statement: false,
    contest_year_problem: `Legacy problem ${id}`, concept_coverage_status: 'Untagged',
    statement_detail_url: `/solutions/problems/${id}/`,
  }));
  const elements = new Map();
  let clickHandler, dialogOpened = false, table;
  const getElementById = id => {
    if (!elements.has(id)) elements.set(id, {
      textContent: id === 'problem-statements-table-data' ? JSON.stringify(rows) : '',
      addEventListener(event, handler) {
        if (id === 'problem-statements-table' && event === 'click') clickHandler = handler;
      },
      querySelectorAll: () => [], replaceChildren() {}, appendChild() {},
      showModal() { dialogOpened = true; },
    });
    return elements.get(id);
  };
  vm.runInNewContext(script, {
    document: {getElementById, createElement: () => ({})},
    DataTable: function (_selector, options) { table = options; },
  });
  for (const row of rows) {
    for (let draw = 0; draw < 2; draw++) {
      const html = table.columns[3].render(null, 'display', row);
      assert.ok(html.includes(`data-problem-uuid="${row.problem_uuid}"`));
      dialogOpened = false;
      clickHandler({target: {closest: () => ({getAttribute: () => row.problem_uuid})}});
      assert.equal(dialogOpened, true);
      assert.equal(getElementById('statement-taxonomy-title').textContent, row.contest_year_problem);
      assert.equal(getElementById('statement-taxonomy-detail').href, row.statement_detail_url);
      assert.equal(getElementById('statement-taxonomy-detail').textContent, 'Open problem');
    }
  }
});
