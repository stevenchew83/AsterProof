const assert = require('node:assert/strict');
const {readFileSync} = require('node:fs');
const {test} = require('node:test');
const vm = require('node:vm');

const template = readFileSync(require.resolve('../../inspinia/templates/pages/contest-analytics.html'),'utf8');
const source = [...template.matchAll(/<script>([\s\S]*?)<\/script>/g)].at(-1)[1]
  .replace(/{% url 'pages:contest_dashboard_listing' %}/g,'/dashboard/contests/listing/')
  .replaceAll('{{ contest_analytics_chart_limit }}','12')
  .replaceAll('{{ contest_analytics_low_sample_threshold }}','10');

function row(index, overrides = {}) {
  return {contest:`Demo ${index}`,problem_count:30-index,active_years:2,year_span_label:'2020-2026',
    avg_mohs:10+index,mohs_statement_count:20,has_mohs:true,complete_metadata_percent:75,
    mohs_coverage_percent:80,topic_coverage_percent:90,technique_coverage_percent:75,
    techniques_per_problem:2,quality_issue_count:1,missing_mohs_count:1,missing_topic_count:0,
    has_techniques:true,is_low_sample:false,quality_badges:[],detail_url:`/details/?contest=Demo+${index}`,...overrides};
}

function dashboard({rows = [row(1),row(2)], clipboard = true, rejectCopy = false, malformed = '',
  tableAvailable = true, chartsAvailable = true, fallbackCopy = true} = {}) {
  function element(attrs = {}) {
    const classes = new Set(['d-none']);
    return {value:'',textContent:'',innerHTML:'Copy filtered rows',handlers:{},style:{},open:false,hidden:false,
      getAttribute:key => attrs[key], setAttribute:(key,value) => { attrs[key]=value; },
      addEventListener(event,handler) { this.handlers[event]=handler; },focus(){this.focused=true;},
      scrollIntoView(){this.scrolled=true;},select(){},
      classList:{add:(...xs)=>xs.forEach(x=>classes.add(x)),remove:(...xs)=>xs.forEach(x=>classes.delete(x)),
        toggle:(x,on)=>on?classes.add(x):classes.delete(x)},hasClass:x=>classes.has(x)};
  }
  const elements=Object.fromEntries(['contest-analytics-dashboard','contest-directory-alert','contest-chart-alert',
    'contest-ranked-metric','contest-ranked-min-statements','contest-ranked-chart','contest-ranked-summary',
    'contest-topic-composition-chart','contest-insights-panel','contest-directory-search','contest-directory-quality-filter',
    'contest-directory-reset','contest-directory-copy','contest-directory-copy-status','contest-directory-columns',
    'contest-directory-page-size','contest-directory-review','contest-directory-filter-summary','contest-directory-title'].map(id=>[id,element()]));
  elements['contest-ranked-metric'].value='problem_count';
  elements['contest-ranked-min-statements'].value='10';
  elements['contest-directory-quality-filter'].value='all';
  elements['contest-dashboard-charts-data']={textContent:malformed==='charts'?'bad':JSON.stringify({topicComposition:{labels:['Demo'],series:[{name:'Algebra',data:[12]}]}})};
  elements['contest-dashboard-table-data']={textContent:malformed==='rows'?'bad':JSON.stringify(rows)};
  const copied=[]; const charts=[]; const timers=[]; const changes=[]; let removed=0; let api;
  function Charts(el,config) { this.el=el;this.config=config;this.render=()=>{};this.updateOptions=config=>{this.config=config;};charts.push(this); }
  function Table(_selector,options) {
    const callbacks={}; let search='';
    function indexes() {
      return options.data.map((_,i)=>i).filter(i=>{
        const item=options.data[i];
        return (item.contest+' '+item.year_span_label).toLowerCase().includes(search.toLowerCase()) &&
          Table.ext.search.every(predicate=>predicate({nTable:{id:'contest-analytics-table'}},[],i,item));
      });
    }
    api=this; this.options=options;this.pageSize=25;
    this.rows=()=>({count:()=>indexes().length,indexes:()=>({toArray:()=>indexes()})});
    this.row=i=>({data:()=>options.data[i]});
    this.search=value=>{search=value;return this;};
    this.draw=()=>{if(callbacks.draw)callbacks.draw();return this;};
    this.on=(event,fn)=>{callbacks[event]=fn;};
    this.page={len:value=>{this.pageSize=value;return this;}};
    this.columns=indices=>({visible:visible=>changes.push({indices:[...indices],visible})});
    this.columns.adjust=()=>this;
  }
  Table.ext={search:[]};Table.render={number:()=>value=>String(value)};
  const location={href:''};
  vm.runInNewContext(source,{
    document:{getElementById:id=>elements[id],documentElement:{getAttribute:()=> 'light'},
      createElement:()=>element(),body:{appendChild(){},removeChild(){removed++;}},execCommand:()=>fallbackCopy},
    navigator:clipboard?{clipboard:{writeText:text=>{copied.push(text);return rejectCopy?Promise.reject(new Error('Denied')):Promise.resolve();}}}:{},
    window:{getThemeColor:key => ({secondary:'#1c84c6',warning:'#f8ac59',purple:'#6b5eae','secondary-color':'#6c757d'})[key],matchMedia:()=>({matches:false}),isSecureContext:true,location,setTimeout:fn=>{timers.push(fn);return timers.length;}},
    clearTimeout(){},getComputedStyle:()=>({getPropertyValue:()=>''}),
    DataTable:tableAvailable?Table:undefined,ApexCharts:chartsAvailable?Charts:undefined,
  });
  return {elements,copied,charts,changes,api,location,timers,removed:()=>removed,predicate:Table.ext.search[0]};
}

test('copy includes every filtered row across pages and announces its actual count',async()=>{
  const rows=Array.from({length:27},(_,i)=>row(i));
  const app=dashboard({rows});
  app.elements['contest-directory-page-size'].value='10';app.elements['contest-directory-page-size'].handlers.change();
  const action=app.elements['contest-directory-copy'].handlers.click();
  assert.equal(app.elements['contest-directory-copy'].disabled,true);
  await action;
  assert.equal(app.api.pageSize,10);
  assert.equal(app.copied[0].split('\n').length,28);
  assert.ok(app.copied[0].includes('Demo 26\t'));
  assert.ok(app.elements['contest-directory-copy-status'].textContent.includes('27 matching contests'));
  assert.equal(app.elements['contest-directory-copy'].disabled,false);
});

test('search and quality filters intersect, reset completely, and stay scoped to this table',()=>{
  const app=dashboard({rows:[row(1),row(2,{contest:'No Concepts',has_techniques:false}),row(3,{complete_metadata_percent:100,missing_mohs_count:0})]});
  const quality=app.elements['contest-directory-quality-filter'];const search=app.elements['contest-directory-search'];
  quality.value='no_techniques';quality.handlers.change();
  assert.equal(app.elements['contest-directory-filter-summary'].textContent,'1 of 3 contests');
  search.value='Demo';search.handlers.input();
  assert.equal(app.api.rows().count(),0);
  assert.equal(app.predicate({nTable:{id:'unrelated'}},[],0,row(1)),true);
  app.elements['contest-directory-reset'].handlers.click();
  assert.equal(app.api.rows().count(),3);assert.equal(quality.value,'all');assert.equal(search.value,'');
  search.value='No Concepts';search.handlers.input();
  app.elements['contest-directory-review'].handlers.click();
  assert.equal(quality.value,'incomplete');assert.equal(search.value,'');assert.equal(app.api.rows().count(),2);
});

test('supplemental columns preserve the table and row details retain escaped context',()=>{
  const app=dashboard();const button=app.elements['contest-directory-columns'];
  button.handlers.click();button.handlers.click();
  assert.equal(app.api.options.columns.length,14);
  assert.deepEqual(app.changes.map(x=>x.visible),[true,false]);
  assert.equal(button.getAttribute('aria-pressed'),'false');
  const value='<Demo "Contest">';const html=app.api.options.columns[0].render(value,'display',row(1,{contest:value}));
  assert.ok(html.includes('&lt;Demo &quot;Contest&quot;&gt;'));assert.ok(html.includes('2020-2026'));
  assert.ok(html.includes('<details'));assert.ok(!html.includes('<Demo'));
  assert.equal(app.api.options.columns[2].render(0,'sort',row(1,{has_mohs:false})),-1);
  assert.equal(app.api.options.columns[2].render(0,'display',row(1,{has_mohs:false})),'—');
});

test('charts initialize on native expansion and MOHS rankings use MOHS sample size',()=>{
  const app=dashboard({rows:[row(1,{contest:'Large incomplete',problem_count:100,mohs_statement_count:2,avg_mohs:90}),row(2,{contest:'Reliable',avg_mohs:20})]});
  assert.equal(app.charts.length,0);
  const panel=app.elements['contest-insights-panel'];panel.open=true;panel.handlers.toggle();
  assert.equal(app.charts.length,2);
  assert.equal(app.charts.find(chart => chart.el === app.elements['contest-topic-composition-chart']).config.colors[1], '#1c84c6');
  app.elements['contest-ranked-metric'].value='avg_mohs';app.elements['contest-ranked-metric'].handlers.change();
  assert.deepEqual([...app.charts[0].config.xaxis.categories],['Reliable']);
  app.charts[0].config.chart.events.dataPointSelection(null,null,{dataPointIndex:0});
  assert.equal(app.location.href,'/details/?contest=Demo+2');
  panel.open=false;panel.handlers.toggle();panel.open=true;panel.handlers.toggle();assert.equal(app.charts.length,2);
});

test('clipboard denial and zero results give honest feedback and restore the action',async()=>{
  const app=dashboard({rejectCopy:true});await app.elements['contest-directory-copy'].handlers.click();
  assert.ok(app.elements['contest-directory-copy-status'].textContent.includes('Copy failed'));
  assert.equal(app.elements['contest-directory-copy'].disabled,false);
  const empty=dashboard({rows:[]});await empty.elements['contest-directory-copy'].handlers.click();
  assert.equal(empty.copied.length,0);assert.equal(empty.elements['contest-directory-copy-status'].textContent,'No matching contests to copy.');
});

test('legacy copying cleans up on both success and failure',async()=>{
  for(const available of [true,false]) {
    const app=dashboard({clipboard:false,fallbackCopy:available});await app.elements['contest-directory-copy'].handlers.click();
    assert.equal(app.removed(),1);
    assert.equal(app.elements['contest-directory-copy-status'].textContent.includes('Copied'),available);
  }
});

test('bad data or a missing library leaves the server fallback and independent features available',()=>{
  const noTable=dashboard({tableAvailable:false});assert.equal(noTable.elements['contest-directory-alert'].hasClass('d-none'),false);
  assert.equal(noTable.elements['contest-analytics-dashboard'].hasClass('has-contest-directory'),false);
  const badRows=dashboard({malformed:'rows'});assert.equal(badRows.api,undefined);
  const badCharts=dashboard({malformed:'charts'});assert.ok(badCharts.api);assert.equal(badCharts.elements['contest-chart-alert'].hasClass('d-none'),false);
  const noCharts=dashboard({chartsAvailable:false});noCharts.elements['contest-insights-panel'].open=true;noCharts.elements['contest-insights-panel'].handlers.toggle();
  assert.ok(noCharts.api);assert.equal(noCharts.elements['contest-chart-alert'].hasClass('d-none'),false);
});
