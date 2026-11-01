/* Page-view charts use the same range and audience as the dashboard totals. */
(function () {
  "use strict";
  var dataElement = document.getElementById("page-view-charts-data");
  if (!dataElement || typeof window.ApexCharts !== "function") return;
  var data;
  try { data = JSON.parse(dataElement.textContent); } catch (_) { return; }
  var charts = [];
  var reducedMotion = window.matchMedia("(prefers-reduced-motion: reduce)").matches;

  function themeColor(style, name) { return style.getPropertyValue("--ins-" + name).trim(); }
  function dateLabel(value) {
    var date = new Date(value + "T00:00:00");
    if (Number.isNaN(date.getTime())) return value;
    var options = data.timeline.granularity === "year" ? {year: "numeric"}
      : data.timeline.granularity === "month" ? {month: "short", year: "numeric"}
        : {day: "numeric", month: "short"};
    return date.toLocaleDateString("en-GB", options);
  }
  function render(id, options) {
    var element = document.getElementById(id);
    if (!element) return;
    try {
      var chart = new window.ApexCharts(element, options);
      charts.push(chart);
      Promise.resolve(chart.render()).then(function () {
        var fallback = element.querySelector(".page-view-chart-fallback");
        if (fallback) fallback.remove();
      }).catch(function () { /* The data disclosures remain available. */ });
    } catch (_) { /* Keep exact values available when chart rendering fails. */ }
  }
  function draw() {
    charts.forEach(function (chart) { chart.destroy(); });
    charts = [];
    var style = getComputedStyle(document.documentElement);
    var colors = ["primary", "info", "warning", "success"].map(function (name) {
      return themeColor(style, name);
    });
    var foreground = themeColor(style, "secondary-color");
    var border = themeColor(style, "border-color");
    var background = themeColor(style, "secondary-bg");
    var quiet = themeColor(style, "tertiary-bg");
    var dark = document.documentElement.getAttribute("data-bs-theme") === "dark";
    function base(type, height) {
      return {
        chart: {type: type, height: height, fontFamily: "inherit", foreColor: foreground,
          background: "transparent", toolbar: {show: false}, zoom: {enabled: false},
          animations: {enabled: !reducedMotion, speed: 350}, parentHeightOffset: 0},
        colors: colors,
        theme: {mode: dark ? "dark" : "light"},
        dataLabels: {enabled: false},
        grid: {borderColor: border, strokeDashArray: 4},
        tooltip: {theme: dark ? "dark" : "light"},
        noData: {text: "No views in this range"},
      };
    }
    var trend = base("area", 255);
    trend.chart.stacked = true;
    trend.series = data.timeline.series;
    trend.stroke = {width: 2, curve: "straight"};
    trend.fill = {type: "gradient", gradient: {opacityFrom: 0.28, opacityTo: 0.03, stops: [0, 95]}};
    trend.markers = {size: data.timeline.labels.length === 1 ? 4 : 0, hover: {size: 4}};
    trend.xaxis = {categories: data.timeline.labels, tickAmount: Math.min(6, data.timeline.labels.length - 1),
      axisBorder: {show: false}, axisTicks: {show: false},
      labels: {rotate: 0, hideOverlappingLabels: true, style: {fontSize: "10px"}, formatter: dateLabel},
      tooltip: {enabled: false}};
    trend.yaxis = {min: 0, forceNiceScale: true, decimalsInFloat: 0,
      labels: {style: {fontSize: "10px"}, formatter: function (value) { return Math.round(value); }}};
    trend.legend = {position: "top", horizontalAlign: "left", fontSize: "11px", markers: {size: 4},
      itemMargin: {horizontal: 10, vertical: 4}};
    trend.tooltip = {theme: dark ? "dark" : "light", shared: true, intersect: false,
      x: {formatter: dateLabel}, y: {formatter: function (value) { return value + " views"; }}};
    render("page-view-trend-chart", trend);

    var mix = base("donut", 177);
    mix.series = data.mix.series;
    mix.labels = data.mix.labels;
    mix.stroke = {width: 3, colors: [background]};
    mix.legend = {show: false};
    mix.plotOptions = {pie: {expandOnClick: false, donut: {size: "78%", labels: {show: true,
      name: {fontSize: "11px", offsetY: 18}, value: {fontSize: "25px", fontWeight: 600, offsetY: -16},
      total: {show: true, showAlways: true, label: "Total views", color: foreground,
        formatter: function () { return data.mix.series.reduce(function (sum, value) { return sum + value; }, 0); }}}}}};
    mix.tooltip.y = {formatter: function (value) { return value + " views"; }};
    render("page-view-mix-chart", mix);

    var heatmap = base("heatmap", 215);
    heatmap.series = data.heatmap.slice().reverse();
    var maximum = Math.max.apply(null, data.heatmap.flatMap(function (row) {
      return row.data.map(function (point) { return point.y; });
    }));
    heatmap.colors = [colors[0]];
    heatmap.stroke = {width: 3, colors: [background]};
    heatmap.legend = {show: false};
    heatmap.grid = {show: false, padding: {top: -10, bottom: -10, left: 0, right: 0}};
    heatmap.plotOptions = {heatmap: {radius: 3, shadeIntensity: 0.6, distributed: false,
      colorScale: {min: 0, max: Math.max(maximum, 1), ranges: [{from: 0, to: 0, color: quiet, name: "No views"}]}}};
    heatmap.xaxis = {type: "category", axisTicks: {show: false}, axisBorder: {show: false},
      labels: {rotate: 0, style: {fontSize: "10px"}, formatter: function (value) {
        return Number(String(value).slice(0, 2)) % 4 === 0 ? value : "";
      }}, tooltip: {enabled: false}};
    heatmap.yaxis = {labels: {style: {fontSize: "10px"}}};
    heatmap.tooltip = {theme: dark ? "dark" : "light", x: {show: true},
      y: {formatter: function (value) { return value + " views"; }}};
    render("page-view-heatmap-chart", heatmap);
  }
  draw();
  new MutationObserver(draw).observe(document.documentElement, {
    attributes: true, attributeFilter: ["data-bs-theme", "data-skin"],
  });
})();
