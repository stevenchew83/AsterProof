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
  document: {getElementById: id => id === 'statement-library' ? null : element},
  DataTable: function (_selector, options) {
    config = options;
    this.table = () => ({node: () => element});
  },
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

test('Topic and MOHS sort independently and use suggestions only for missing values', () => {
  const problem = config.columns[0].render;
  const topic = config.columns[1].render;
  const mohs = config.columns[2].render;
  const row = {
    ...statement, problem_uuid: 'problem-id',
    classification_url: '/problems/problem-id/ai-suggestions/',
    linked_problem_topic: 'Geometry', linked_problem_mohs: 0,
    linked_problem_mohs_url: '/contest/?year=1991&mohs=0',
  };
  assert.equal(topic(null, 'sort', row), 'Geometry');
  assert.equal(mohs(null, 'sort', row), 0);
  assert.equal(mohs(null, 'sort', {...row, linked_problem_mohs: '10'}), 10);
  assert.equal(mohs(null, 'sort', {...row, linked_problem_mohs: null}), -1);
  assert.doesNotMatch(problem(null, 'display', row), /Suggest with AI/);

  const classification = {phase: 'done', suggestions: {topic: 'Algebra', mohs: 15}};
  const missingTopic = {...row, linked_problem_topic: '', classification};
  assert.match(topic(null, 'display', missingTopic), /Algebra.*>AI</);
  assert.match(mohs(null, 'display', missingTopic), /href="\/contest\/\?year=1991&amp;mohs=0">0<\/a>/);

  const missingMohs = {...row, linked_problem_mohs: null, classification};
  assert.match(topic(null, 'display', missingMohs), />Geometry<\/span>$/);
  assert.match(mohs(null, 'display', missingMohs), />15.*>AI</);
});

test('the last column holds the AI action and explains a partial save', () => {
  const column = config.columns.at(-3);
  const row = {
    ...statement, problem_uuid: 'problem-id', classification_url: '/problems/problem-id/ai-suggestions/',
  };
  assert.equal(column.orderable, false);
  assert.equal(column.render(null, 'display', statement), '');
  assert.match(column.render(null, 'display', row), /Suggest with AI/);
  const partial = column.render(null, 'display', {...row, classification: {phase: 'saved', taxonomyMissing: true}});
  assert.match(partial, /Try AI again/);
  assert.match(partial, /No supported concept found/);
  assert.doesNotMatch(partial, /aria-disabled/);
});

test('the AI action shows the server error and becomes available again at the daily reset', async () => {
  const row = {
    ...statement, problem_uuid: 'problem-id', classification_url: '/problems/problem-id/ai-suggestions/',
  };
  const liveStatus = {textContent: ''};
  const redraws = [];
  let click, reset, response;
  vm.runInNewContext(script, {
    document: {
      getElementById(id) {
        if (id === 'statement-library') return null;
        if (id === 'problem-statements-table-data') return {textContent: JSON.stringify([row])};
        if (id === 'library-classification-status') return liveStatus;
        return element;
      },
    },
    fetch: async () => response,
    window: {
      setTimeout(callback, delay) {
        assert.equal(delay, 1000);
        reset = callback;
      },
    },
    DataTable: function (_selector, options) {
      this.row = () => ({
        node: () => null,
        invalidate: () => ({
          draw: () => redraws.push(options.columns.at(-3).render(null, 'display', options.data[0])),
        }),
      });
      this.table = () => ({node: () => ({addEventListener(_event, handler) { click = handler; }})});
    },
  });
  const clickEvent = {target: {closest: () => ({getAttribute: () => null, dataset: {problemUuid: row.problem_uuid}})}};
  const error = 'OpenAI could not return suggestions for this problem.';
  response = {
    ok: false, status: 502, headers: new Map([['content-type', 'application/json']]),
    json: async () => ({error}),
  };
  await click(clickEvent);
  assert.match(redraws.at(-1), /Try AI again/);
  assert.ok(redraws.at(-1).includes('>' + error + '</div>'));

  response = {
    ok: false, status: 429, headers: new Map([['content-type', 'application/json'], ['Retry-After', '1']]),
    json: async () => ({error: 'Daily limit reached', code: 'daily_limit_reached'}),
  };
  await click(clickEvent);
  assert.match(redraws.at(-1), /aria-disabled="true".*>Daily limit reached<.*>Resets at 08:00 MYT\./);
  assert.doesNotMatch(redraws.at(-1), /Try AI again/);
  assert.match(liveStatus.textContent, /Daily limit reached\. Resets at 08:00 MYT\./);

  reset();
  assert.match(redraws.at(-1), /Suggest with AI/);
  assert.doesNotMatch(redraws.at(-1), /aria-disabled|Daily limit reached/);
});

test('Area and Coverage each display one label with a count and keep all labels in the tooltip', () => {
  const area = config.columns[4].render;
  const coverage = config.columns[5].render;
  const row = {
    ...statement, problem_uuid: 'problem-id', concept_areas: ['First area', 'Second area'],
    concept_coverage: ['First concept', 'Second concept', 'Third concept'].map(display => ({display})),
  };
  const areaHtml = area(null, 'display', row);
  assert.match(areaHtml, /title="First area, Second area"/);
  assert.match(areaHtml, />First area<.*>\+1</);
  assert.doesNotMatch(areaHtml, />Second area</);
  const coverageHtml = coverage(null, 'display', row);
  assert.match(coverageHtml, /title="First concept, Second concept, Third concept"/);
  assert.match(coverageHtml, />First concept<.*>\+2</);
  assert.doesNotMatch(coverageHtml, />Second concept</);

  const saved = {...row, concept_areas: [], concept_coverage: [],
    saved_ai_concepts: [{label: 'First concept', area: 'First area'}, {label: 'Second concept', area: 'Second area'}]};
  assert.match(area(null, 'display', saved), />First area<.*>\+1<.*>AI</);
  assert.match(coverage(null, 'display', saved), />First concept<.*>\+1<.*>AI</);
  assert.equal(coverage(null, 'sort', saved), 'First concept, Second concept');
});

test('unlinked statement completion shows unsolved, solved or unknown-date status', () => {
  const render = row => config.columns[3].render(null, 'display', row);
  assert.ok(render(statement).includes('Unsolved'));
  assert.ok(!render(statement).includes('Not linked'));
  const row = {...statement, user_completion_state_kind: 'unknown',
    user_completion_display: 'Unknown date', user_completion_sort: '1'};
  assert.ok(render(row).includes('Unknown date'));
  assert.equal(config.columns[3].render(null, 'sort', row), '1');
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
    if (id === 'statement-library') return null;
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
    DataTable: function (_selector, options) {
      table = options;
      this.table = () => ({node: () => element});
    },
  });
  for (const row of rows) {
    for (let draw = 0; draw < 2; draw++) {
      const html = table.columns[4].render(null, 'display', row);
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
