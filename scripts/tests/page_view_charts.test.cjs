const assert = require('node:assert/strict');
const {readFileSync} = require('node:fs');
const {test} = require('node:test');
const vm = require('node:vm');

const source = readFileSync(require.resolve('../../inspinia/static/js/page-view-charts.js'), 'utf8');
const payload = {
  timeline: {granularity:'day', labels:['2026-10-04','2026-10-05'], series:[
    {name:'Statement', data:[0,1]}, {name:'Solution',data:[1,2]},
    {name:'List',data:[0,0]}, {name:'Contest',data:[0,0]},
  ]},
  mix: {labels:['Statement','Solution','List','Contest'],series:[1,3,0,0]},
  heatmap: [{name:'Mon',data:[{x:'00:00',y:2},{x:'01:00',y:0}]}],
};

function dashboard({vendor = true, malformed = false, reduced = false, fail = false} = {}) {
  const rendered = [], destroyed = [];
  let onTheme;
  const elements = Object.fromEntries(['page-view-trend-chart','page-view-mix-chart','page-view-heatmap-chart']
    .map(id => [id, {id, querySelector: () => null}]));
  const colors = {'--ins-primary':'#508573','--ins-info':'#428da8','--ins-warning':'#b78c43',
    '--ins-success':'#3c916e','--ins-secondary-bg':'#ffffff','--ins-tertiary-bg':'#f5f6f7',
    '--ins-secondary-color':'#667077','--ins-border-color':'#e0e2e4'};
  function ApexCharts(element, options) {
    this.render = () => { rendered.push({element, options}); return fail ? Promise.reject(new Error('Unavailable')) : Promise.resolve(); };
    this.destroy = () => destroyed.push(element.id);
  }
  const root = {getAttribute: () => 'light'};
  vm.runInNewContext(source, {
    document: {documentElement: root, getElementById: id => id === 'page-view-charts-data'
      ? {textContent:malformed ? '{' : JSON.stringify(payload)} : elements[id]},
    window: {ApexCharts:vendor ? ApexCharts : undefined, matchMedia: () => ({matches:reduced})},
    getComputedStyle: () => ({getPropertyValue: name => colors[name] || ''}),
    MutationObserver: function (callback) { onTheme = callback; this.observe = () => {}; },
  });
  return {rendered, destroyed, theme: () => onTheme()};
}

test('charts retain exact counts, local date labels and a shared heat intensity scale', () => {
  const {rendered} = dashboard();
  assert.equal(rendered.length, 3);
  const [trend, mix, heatmap] = rendered.map(item => item.options);
  assert.equal(trend.series[1].data.reduce((a,b) => a+b), 3);
  assert.equal(trend.xaxis.labels.formatter('2026-10-05'), '5 Oct');
  assert.equal(mix.plotOptions.pie.donut.labels.total.formatter(), 4);
  assert.equal(heatmap.plotOptions.heatmap.distributed, false);
  assert.equal(heatmap.plotOptions.heatmap.colorScale.max, 2);
  assert.equal(heatmap.tooltip.y.formatter(2), '2 views');
});

test('theme changes replace old charts and reduced motion disables animation', () => {
  const app = dashboard({reduced:true});
  assert.ok(app.rendered.every(item => item.options.chart.animations.enabled === false));
  app.theme();
  assert.equal(app.destroyed.length, 3);
  assert.equal(app.rendered.length, 6);
});

test('unavailable vendors and malformed data leave HTML data fallbacks usable', () => {
  assert.equal(dashboard({vendor:false}).rendered.length, 0);
  assert.equal(dashboard({malformed:true}).rendered.length, 0);
});

test('a rendering rejection is contained instead of breaking the rest of the page', async () => {
  assert.equal(dashboard({fail:true}).rendered.length, 3);
  await new Promise(resolve => setImmediate(resolve));
});
