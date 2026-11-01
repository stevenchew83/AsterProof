const assert = require('node:assert/strict');
const {readFileSync} = require('node:fs');
const {test} = require('node:test');
const vm = require('node:vm');

const template = readFileSync(require.resolve('../../inspinia/templates/pages/problem-statement-analytics.html'), 'utf8');
const source = [...template.matchAll(/<script>([\s\S]*?)<\/script>/g)].at(-1)[1];

function dashboard({emptyMode = false, chartsAvailable = true, tableAvailable = true} = {}) {
  function element(attrs = {}) {
    const classes = new Set(['d-none']);
    const span = {textContent:''};
    return {style:{}, textContent:'', open:false, handlers:{},
      getAttribute: key => attrs[key], setAttribute: (key, value) => { attrs[key] = value; },
      addEventListener: function (event, handler) { this.handlers[event] = handler; },
      querySelector: () => span,
      classList:{add: x => classes.add(x), remove: x => classes.delete(x),
        toggle: (x, enabled) => enabled ? classes.add(x) : classes.delete(x)},
      hasClass: x => classes.has(x),
    };
  }
  const modes = ['backlog','lowCoverage','volume','recent','all'].map(mode => element({'data-statement-heatmap-mode':mode}));
  const filters = ['all','unlinked','low-coverage','recent','complete'].map(filter => element({'data-statement-analytics-filter':filter}));
  const payload = {years:['2020','2026'], metric_label:'Unlinked statement rows', max_value:3,
    series:[{name:'Demo Contest',data:[{x:'2026',y:3,url:'/master/?contest=Demo&year=2026'}]}]};
  const views = Object.fromEntries(['backlog','lowCoverage','volume','recent','all'].map(mode => [mode,payload]));
  if (emptyMode) views.lowCoverage = {...payload, series:[]};
  const elements = Object.fromEntries(['statement-analytics-dashboard','chart-statement-heatmap-alert',
    'problem-statement-analytics-table-alert','statement-analytics-heatmap-frame','statement-analytics-trends',
    'statement-heatmap-heading','statement-heatmap-scope','statement-analytics-columns',
    'chart-statement-heatmap','chart-year-bars'].map(id => [id,element()]));
  elements['problem-statement-dashboard-charts-data'] = {textContent:JSON.stringify({statementHeatmapViews:views,
    statementYearBarChart:{labels:['2020','2026'],values:[8,12]}})};
  elements['problem-statement-dashboard-table-data'] = {textContent:JSON.stringify([{contest_year:2026,contest_name:'Demo'}])};
  const instances = [];
  const columnChanges = [];
  const location = {href:''};
  let options;
  let draws = 0;
  function Charts(el, config) {
    this.el = el; this.config = config; this.destroyed = false;
    this.render = () => {};
    this.destroy = () => { this.destroyed = true; };
    instances.push(this);
  }
  function Table(_selector, config) {
    options = config;
    this.draw = () => { draws += 1; };
    this.columns = indexes => ({visible: show => columnChanges.push({indexes:[...indexes],show})});
  }
  Table.ext = {search:[]};
  vm.runInNewContext(source, {
    document:{documentElement:{}, getElementById:id => elements[id],
      querySelector:selector => elements[selector.slice(1)],
      querySelectorAll:selector => selector.includes('heatmap') ? modes : filters},
    getComputedStyle:() => ({getPropertyValue:() => ''}),
    window:{location},
    ApexCharts:chartsAvailable ? Charts : undefined,
    DataTable:tableAvailable ? Table : undefined,
  });
  return {elements, modes, filters, instances, columnChanges, options, location,
    predicate:Table.ext.search[0], draws:() => draws};
}

test('directory filters keep their existing row semantics and do not affect another table', () => {
  const app = dashboard();
  const settings = {nTable:{id:'problem-statement-analytics-table'}};
  const row = {has_unlinked:true,is_low_coverage:false,is_recent:true,link_rate:60};
  for (const [index, expected] of [[1,true],[2,false],[3,true],[4,false],[0,true]]) {
    app.filters[index].handlers.click();
    assert.equal(app.predicate(settings,[],0,row), expected);
    assert.equal(app.predicate({nTable:{id:'unrelated'}},[],0,row), true);
    assert.equal(app.filters[index].getAttribute('aria-pressed'), 'true');
    assert.equal(app.instances.length, 1);
  }
  assert.equal(app.draws(), 5);
});

test('more columns preserves the table and toggles supplemental columns accessibly', () => {
  const app = dashboard();
  const button = app.elements['statement-analytics-columns'];
  button.handlers.click();
  button.handlers.click();
  assert.deepEqual(app.columnChanges,[{indexes:[3,6],show:true},{indexes:[3,6],show:false}]);
  assert.equal(button.getAttribute('aria-pressed'),'false');
  assert.equal(button.querySelector('span').textContent,'More columns');
  assert.equal(app.options.pageLength,25);
  assert.equal(app.options.columns.length,8);
});

test('display renderers escape contest text and preserve raw numeric sorting', () => {
  const app = dashboard();
  const row = {contest_year_url:'/master/?contest=A&year=2026',link_rate_label:'75%',linked_count:3,statement_count:4};
  const renderContest = app.options.columns[1].render;
  const html = renderContest('<Demo "Contest">','display',row);
  assert.ok(html.includes('&lt;Demo &quot;Contest&quot;&gt;'));
  assert.ok(html.includes('contest=A&amp;year=2026'));
  assert.ok(!html.includes('<Demo'));
  assert.equal(renderContest('Demo','filter',row),'Demo');
  assert.equal(app.options.columns[5].render(75,'sort',row),75);
  assert.equal(app.options.columns[5].render(75,'filter',row),'75%');
});

test('heatmap modes retain point navigation and clear stale charts for empty modes', () => {
  const app = dashboard({emptyMode:true});
  app.modes[2].handlers.click();
  assert.equal(app.instances[0].destroyed,true);
  assert.equal(app.elements['statement-heatmap-heading'].textContent,'Statement volume heatmap');
  assert.equal(app.modes[2].getAttribute('aria-pressed'),'true');
  assert.equal(app.instances[1].config.series[0].data[0].url,'/master/?contest=Demo&year=2026');
  app.instances[1].config.chart.events.dataPointSelection(null,null,{seriesIndex:0,dataPointIndex:0});
  assert.equal(app.location.href,'/master/?contest=Demo&year=2026');
  app.modes[1].handlers.click();
  assert.equal(app.instances[1].destroyed,true);
  assert.equal(app.elements['chart-statement-heatmap-alert'].hasClass('d-none'),false);
  assert.ok(app.elements['statement-heatmap-scope'].textContent.includes('0 contests'));
  app.modes[4].handlers.click();
  assert.equal(app.elements['chart-statement-heatmap-alert'].hasClass('d-none'),true);
  assert.equal(app.elements['statement-analytics-heatmap-frame'].hasClass('is-all-mode'),true);
});

test('the year chart initializes once when its native disclosure opens', () => {
  const app = dashboard();
  const details = app.elements['statement-analytics-trends'];
  assert.equal(app.instances.length,1);
  details.open = true;
  details.handlers.toggle();
  details.open = false;
  details.handlers.toggle();
  details.open = true;
  details.handlers.toggle();
  assert.equal(app.instances.length,2);
  assert.equal(app.instances[1].config.chart.type,'bar');
  assert.deepEqual([...app.instances[1].config.series[0].data],[8,12]);
});

test('chart or table dependencies can fail independently with visible feedback', () => {
  const withoutCharts = dashboard({chartsAvailable:false});
  assert.ok(withoutCharts.options);
  assert.equal(withoutCharts.elements['chart-statement-heatmap-alert'].hasClass('d-none'),false);
  const withoutTable = dashboard({tableAvailable:false});
  assert.equal(withoutTable.instances.length,1);
  assert.equal(withoutTable.elements['problem-statement-analytics-table-alert'].hasClass('d-none'),false);
});
