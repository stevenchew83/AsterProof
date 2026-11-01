const assert = require('node:assert/strict');
const {readFileSync} = require('node:fs');
const {test} = require('node:test');
const vm = require('node:vm');

const template = readFileSync(require.resolve('../../inspinia/templates/pages/completion-progress-analytics.html'), 'utf8');
const source = [...template.matchAll(/<script>([\s\S]*?)<\/script>/g)].at(-1)[1];

function dashboard({shared = false, editable = false} = {}) {
  const elements = new Map();
  const chartConfigs = [];
  let tableOptions;
  let expanded = false;
  function element(id, attrs = {}) {
    const node = {id, value: '30d', offsetWidth: 900, textContent: '', handlers: {},
      getAttribute: key => attrs[key] ?? null,
      addEventListener(event, listener) { this.handlers[event] = listener; }};
    elements.set(id, node);
    return node;
  }
  element(shared ? 'shared-progress-dashboard' : 'completion-progress-dashboard');
  for (const id of ['range', 'start', 'end', 'advanced-filters']) element('completion-progress-' + id);
  element('completion-progress-table', {'data-show-difficulty': 'true', 'data-can-edit-difficulty': String(editable)});
  const chartData = {
    dailyCompletions: {labels: ['2026-10-30', '2026-10-31'], values: [1, 2]},
    dailyMohs: {labels: ['2026-10-30', '2026-10-31'], totalValues: [0, 30], averageValues: [0, 15]},
    dailyTopicMix: {labels: [], series: []}, topicTotals: {labels: [], values: []},
    mohsDistribution: {labels: [], values: []}, topicMohsHeatmap: {series: []}, solutionStatus: {values: []},
  };
  element('completion-progress-chart-data').textContent = JSON.stringify(chartData);
  element('completion-progress-table-data').textContent = JSON.stringify([{contest: 'IMO', year: 2026}]);
  for (const id of ['daily', 'mohs']) element('chart-completion-progress-' + id, shared ? {} : {'data-chart-height': '260'});
  vm.runInNewContext(source, {
    document: {
      getElementById: id => elements.get(id) ?? null,
      querySelector: selector => selector.startsWith('#') ? elements.get(selector.slice(1)) ?? null : null,
      querySelectorAll: () => [],
    },
    window: {bootstrap: {Collapse: {getOrCreateInstance: () => ({show() { expanded = true; }})}}},
    getComputedStyle: () => ({getPropertyValue: key => key === '--ins-primary-text-emphasis' ? '#13795b' : ''}),
    ApexCharts: function (el, config) { chartConfigs.push({id:el.id, ...config}); this.render = () => Promise.resolve(); },
    DataTable: function (_selector, config) { tableOptions = config; },
  });
  return {elements, tableOptions, chartConfigs, expanded: () => expanded};
}

test('custom dates expand when chosen and editing a date selects the custom range', () => {
  const app = dashboard();
  const range = app.elements.get('completion-progress-range');
  range.handlers.change();
  assert.equal(app.expanded(), false);
  range.value = 'custom';
  range.handlers.change();
  assert.equal(app.expanded(), true);
  for (const id of ['start', 'end']) {
    range.value = '30d';
    app.elements.get('completion-progress-' + id).handlers.change();
    assert.equal(range.value, 'custom');
  }
});

test('compact charts retain their original series, zero values and theme color', () => {
  const app = dashboard();
  const daily = app.chartConfigs.find(chart => chart.id.endsWith('-daily'));
  const mohs = app.chartConfigs.find(chart => chart.id.endsWith('-mohs'));
  assert.equal(daily.chart.height, 260);
  assert.equal(daily.colors[0], '#13795b');
  assert.deepEqual(Array.from(daily.series[0].data), [1, 2]);
  assert.deepEqual(Array.from(mohs.series[0].data), [0, 30]);
  assert.equal(mohs.yaxis.length, 2);
});

test('redundant columns stay searchable while default ordering, paging and difficulty access survive', () => {
  for (const editable of [false, true]) {
    const options = dashboard({editable}).tableOptions;
    for (const key of ['contest', 'year']) {
      const column = options.columns.find(item => item.data === key);
      assert.equal(column.visible, false);
      assert.notEqual(column.searchable, false);
    }
    assert.equal(options.columns[options.order[0][0]].data, 'updated_at');
    assert.deepEqual(Array.from(options.lengthMenu), [10, 25, 50, 100]);
    const rating = options.columns.find(item => item.data === 'user_difficulty_rating');
    const html = rating.render(0, 'display', {difficulty_statement_uuid:'demo', average_difficulty_display:'0.0', difficulty_rating_count:1});
    assert.equal(html.includes('js-completion-progress-difficulty-save'), editable);
    assert.ok(html.includes('0'));
  }
});

test('shared learner dashboards retain their own chart sizing and table configuration', () => {
  const app = dashboard({shared:true});
  assert.equal(app.chartConfigs.find(chart => chart.id.endsWith('-daily')).chart.height, 230);
  assert.notEqual(app.tableOptions.columns.find(column => column.data === 'contest').visible, false);
  assert.equal(app.elements.get('completion-progress-range').handlers.change, undefined);
});
