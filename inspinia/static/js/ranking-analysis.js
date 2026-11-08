/* Ranking analytics: progressive charts, server ordering and visible-page copy. */
(function () {
  'use strict';
  var root = document.querySelector('.ranking-analysis');
  if (!root) return;
  var form = root.querySelector('#ranking-analysis-filters');
  if (form) {
    ['season', 'assessment', 'compare_assessment'].forEach(function (name) {
      var field = form.elements.namedItem(name);
      if (field) field.addEventListener('change', function () {
        if (name === 'season') form.elements.namedItem('assessment').value = '';
        var category = form.elements.namedItem(name === 'compare_assessment' ? 'compare_band' : 'band');
        if (category) category.value = '';
        var missing = form.elements.namedItem(name === 'compare_assessment' ? 'compare_band_missing' : 'band_missing');
        if (missing) missing.checked = false;
      });
    });
    ['band', 'compare_band'].forEach(function (name) {
      var category = form.elements.namedItem(name);
      var missing = form.elements.namedItem(name === 'band' ? 'band_missing' : 'compare_band_missing');
      if (category && missing) {
        category.addEventListener('change', function () { if (category.value) missing.checked = false; });
        missing.addEventListener('change', function () { if (missing.checked) category.value = ''; });
      }
    });
  }
  var copy = root.querySelector('[data-analysis-copy]');
  var status = root.querySelector('[data-analysis-copy-status]');
  if (copy && window.RankingTableTools) {
    copy.hidden = false;
    copy.addEventListener('click', async function () {
      var table = root.querySelector('#ranking-analysis-table');
      var headings = Array.from(table.tHead.rows[0].cells).map(function (cell) { return cell.textContent.trim(); });
      var keep = headings.map(function (label, index) { return label === 'Correction' || label === 'Review' ? -1 : index; }).filter(function (index) { return index >= 0; });
      var rows = Array.from(table.tBodies[0].rows).filter(function (row) { return row.hasAttribute('data-analysis-row') && !row.hidden; });
      if (!rows.length) return;
      var values = rows.map(function (row) { return keep.map(function (index) { return row.cells[index].textContent.replace(/\s+/g, ' ').trim(); }); });
      copy.disabled = true;
      try {
        await window.RankingTableTools.copyText(window.RankingTableTools.toTSV(keep.map(function (index) { return headings[index]; }), values));
        status.textContent = 'Copied ' + rows.length + ' visible row' + (rows.length === 1 ? '' : 's') + ' with headers. Full filtered data is available through Export.';
        status.className = 'text-success fs-xs mb-2';
      } catch (_) {
        status.textContent = 'Copy unavailable. Select the table manually or use Export.';
        status.className = 'text-danger fs-xs mb-2';
      } finally { copy.disabled = false; }
    });
  }
  var payload = document.getElementById('ranking-analysis-charts');
  if (!payload || typeof window.ApexCharts !== 'function') return;
  var panels;
  try { panels = JSON.parse(payload.textContent); } catch (_) { return; }
  var charts = new Map();
  var reducedMotion = window.matchMedia('(prefers-reduced-motion: reduce)').matches;
  function escape(value) { return String(value).replace(/[&<>"']/g, function (character) { return {'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[character]; }); }
  function draw() {
    charts.forEach(function (chart) { try { chart.destroy(); } catch (_) { /* Keep exact values. */ } });
    charts.clear();
    var style = getComputedStyle(document.documentElement);
    function color(name) { return style.getPropertyValue('--ins-' + name).trim(); }
    var dark = document.documentElement.getAttribute('data-bs-theme') === 'dark';
    panels.forEach(function (panel) {
      var target = document.getElementById('analysis-chart-' + panel.id);
      var download = root.querySelector('[data-chart-download="' + panel.id + '"]');
      if (!target) return;
      if (download) download.hidden = true;
      var fallback = target.querySelector('.analysis-chart-fallback');
      var options = {
        chart: {type:panel.type, height:250, fontFamily:'inherit', background:color('secondary-bg'), foreColor:color('secondary-color'), toolbar:{show:false}, zoom:{enabled:false}, animations:{enabled:!reducedMotion,speed:200}, parentHeightOffset:0},
        colors:[color('primary')], theme:{mode:dark?'dark':'light'},
        dataLabels:{enabled:false}, grid:{borderColor:color('border-color')}, legend:{show:false},
        tooltip:{theme:dark?'dark':'light'},
        xaxis:{categories:(panel.labels || []).map(escape), tooltip:{enabled:false}, labels:{rotate:0,hideOverlappingLabels:true,trim:true}, axisBorder:{show:false}, axisTicks:{show:false}},
        yaxis:{min:0, labels:{formatter:function (value) { return Number.isInteger(value)?String(value):Number(value).toFixed(1); }}},
        noData:{text:'No recorded values in this selection'}
      };
      if (panel.type === 'scatter') {
        options.series = [{name:'Matched student',data:panel.points.map(function (point) { return {x:point.x,y:point.y}; })}];
        options.xaxis = {type:'numeric',title:{text:escape(panel.x_label)},min:0,tickAmount:5,labels:{formatter:function (value) {return Number(value).toFixed(1);}}};
        options.yaxis.title = {text:escape(panel.y_label)};
        if (panel.unit === 'percentile') { options.xaxis.max = 100; options.yaxis.max = 100; }
        options.markers = {size:4};
        options.tooltip.custom = function (event) {
          var point = panel.points[event.dataPointIndex];
          return point ? '<div class="p-2 fs-xs">' + escape(point.name) + '<br>' + escape(panel.x_label) + ': ' + point.x.toFixed(1) + '<br>' + escape(panel.y_label) + ': ' + point.y.toFixed(1) + '</div>' : '';
        };
      } else {
        options.series = [{name:panel.unit,data:panel.values.map(Number)}];
        if (panel.type === 'bar') options.plotOptions = {bar:{columnWidth:'65%',borderRadius:3}};
        if (panel.type === 'line') {
          // Unconnected observations do not invent continuous chronology for
          // undated assessments or imply comparable raw scoring scales.
          options.stroke = {width:0}; options.markers = {size:4}; options.yaxis.max = 100;
        }
        options.tooltip.custom = function (event) {
          var index = event.dataPointIndex;
          return '<div class="p-2 fs-xs">' + escape(panel.labels[index] || '') + '<br>' +
            Number(panel.values[index]).toLocaleString(undefined,{maximumFractionDigits:2}) + ' ' + escape(panel.unit) + '</div>';
        };
        if (panel.links) options.chart.events = {dataPointSelection:function (_, __, event) { var url = panel.links[event.dataPointIndex]; if (url) window.location.assign(url); }};
      }
      try {
        var chart = new window.ApexCharts(target, options);
        charts.set(panel.id, chart);
        Promise.resolve(chart.render()).then(function () {
          if (charts.get(panel.id) !== chart) return;
          if (fallback) fallback.remove();
          if (download) download.hidden = false;
        }).catch(function () { /* Exact values remain available. */ });
      } catch (_) { /* Exact values remain available. */ }
    });
  }
  root.querySelectorAll('[data-chart-download]').forEach(function (button) {
    button.addEventListener('click', async function () {
      var chart = charts.get(button.dataset.chartDownload);
      if (!chart) return;
      button.disabled = true;
      var feedback = root.querySelector('#analysis-chart-status');
      try {
        var data = await chart.dataURI({scale:2});
        var image = data.blob;
        if (!image) {
          var binary = atob(data.imgURI.split(',')[1]);
          image = new Blob([Uint8Array.from(binary, function (character) { return character.charCodeAt(0); })], {type:'image/png'});
        }
        var imageUrl = window.URL.createObjectURL(image);
        var anchor = document.createElement('a');
        anchor.href = imageUrl; anchor.download = 'ranking-analysis-' + button.dataset.chartDownload + '.png';
        document.body.appendChild(anchor);
        anchor.click();
        document.body.removeChild(anchor);
        setTimeout(function () { window.URL.revokeObjectURL(imageUrl); }, 30000);
        if (feedback) feedback.textContent = 'Chart image download started.';
      } catch (_) { if (feedback) feedback.textContent = 'The chart image could not be downloaded. Exact values remain available below the chart.'; }
      finally { button.disabled = false; }
    });
  });
  draw();
  new MutationObserver(draw).observe(document.documentElement, {attributes:true,attributeFilter:['data-bs-theme','data-skin']});
})();
