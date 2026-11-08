const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const {test} = require('node:test');

function chartOptions(panels, download = null) {
  const captured = [];
  const root = {
    querySelector: selector => selector.startsWith('[data-chart-download=') ? download?.button : null,
    querySelectorAll: () => download ? [download.button] : [],
  };
  const target = {querySelector: () => null};
  const document = {
    querySelector: () => root,
    getElementById: id => id === 'ranking-analysis-charts' ? {textContent: JSON.stringify(panels)} : target,
    documentElement: {getAttribute: () => 'light'},
    body: download?.body,
    createElement: () => download?.anchor,
  };
  const window = {
    URL: {createObjectURL: () => 'blob:synthetic-ranking-chart', revokeObjectURL: () => {}},
    matchMedia: () => ({matches: true}),
    ApexCharts: function (_element, options) {
      captured.push(options);
      this.render = () => Promise.resolve();
      this.destroy = () => {};
      this.dataURI = () => Promise.resolve({imgURI:'data:image/png;base64,iVBORw0KGgo='});
    },
  };
  const code = fs.readFileSync(path.resolve(__dirname, '../../inspinia/static/js/ranking-analysis.js'), 'utf8');
  vm.runInNewContext(code, {
    document, window, Blob, atob, setTimeout: () => 1,
    getComputedStyle: () => ({getPropertyValue: () => '#123456'}),
    MutationObserver: class {observe() {}},
  });
  return captured;
}

test('untrusted ranking labels are escaped in Apex HTML tooltips and axes', () => {
  const attack = '<img src=x onerror=alert(1)>';
  const [bar, scatter] = chartOptions([
    {id:'outcome', type:'bar', labels:[attack], values:[4], unit:'records'},
    {id:'scatter', type:'scatter', points:[{x:10,y:20,name:attack}], x_label:attack,y_label:attack,unit:'percentile'},
  ]);
  assert.equal(bar.xaxis.categories[0], '&lt;img src=x onerror=alert(1)&gt;');
  assert.equal(bar.xaxis.tooltip.enabled, false);
  assert.ok(!bar.tooltip.custom({dataPointIndex:0}).includes('<img'));
  assert.ok(bar.tooltip.custom({dataPointIndex:0}).includes('&lt;img'));
  assert.ok(!scatter.tooltip.custom({dataPointIndex:0}).includes('<img'));
  assert.equal(scatter.xaxis.title.text, '&lt;img src=x onerror=alert(1)&gt;');
  assert.equal(scatter.yaxis.max, 100);
});

test('PNG export clicks an attached download anchor and removes it afterward', async () => {
  let attached = false;
  let clicked = false;
  const download = {
    button: {dataset:{chartDownload:'outcome'}, addEventListener: (_, callback) => {download.click = callback;}},
    anchor: {click: () => {assert.ok(attached); clicked = true;}},
    body: {appendChild: () => {attached = true;}, removeChild: () => {attached = false;}},
  };
  chartOptions([{id:'outcome',type:'bar',labels:['GOLD'],values:[1],unit:'records'}], download);
  await download.click();
  assert.ok(clicked);
  assert.ok(!attached);
  assert.equal(download.anchor.download, 'ranking-analysis-outcome.png');
  assert.equal(download.anchor.href, 'blob:synthetic-ranking-chart');
});

test('student history uses unconnected percentile observations and respects reduced motion', () => {
  const [chart] = chartOptions([{id:'history',type:'line',labels:['2025 · date not recorded','2026 · date not recorded'],values:[20,70],unit:'percentile'}]);
  assert.equal(chart.stroke.width, 0);
  assert.equal(chart.markers.size, 4);
  assert.equal(chart.chart.animations.enabled, false);
  assert.equal(chart.yaxis.max, 100);
  assert.deepEqual(Array.from(chart.series[0].data), [20,70]);
});
