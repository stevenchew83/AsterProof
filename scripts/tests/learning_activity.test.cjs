const assert = require('node:assert/strict');
const {readFileSync} = require('node:fs');
const {test} = require('node:test');
const vm = require('node:vm');
const source=readFileSync(require.resolve('../../inspinia/static/js/learning-activity.js'),'utf8');

function tracker({endpoint='/activity/collect/',status=204}={}) {
  let now=0;
  const calls=[], events={}, windowEvents={}, intervals=[], timeouts=[];
  const rules=[
    {key:'save_solution',selector:'#solution-save',texts:['save changes']},
    {key:'submit_form',selector:'button[type=submit]',texts:[]},
    {key:'other_button',selector:'button',texts:[]},
  ];
  const doc={visibilityState:'visible',getElementById:()=>({textContent:JSON.stringify({token:'signed-page-token',csrf:'csrf',endpoint,rules})}),
    addEventListener:(name,fn)=>events[name]=fn};
  const win={fetch:(url,opts)=>{calls.push({url,opts,payload:JSON.parse(opts.body)});return Promise.resolve({status});},
    addEventListener:(name,fn)=>windowEvents[name]=fn,setInterval:(fn,ms)=>intervals.push({fn,ms}),
    setTimeout:fn=>{timeouts.push(fn);return timeouts.length;},clearTimeout:()=>{}};
  win.top=win;win.self=win;
  vm.runInNewContext(source,{window:win,document:doc,performance:{now:()=>now},
    location:{href:'https://example.com/dashboard/',origin:'https://example.com'},URL});
  function control({key='save',text='Save changes',inPage=true}={}) {
    const item={textContent:text,getAttribute:()=>null,disabled:false,
      matches:selector=>selector===(key==='save'?'#solution-save':'button'),
      closest:selector=>selector.includes('.content-page')?(inPage?{}:null):item};
    Object.defineProperty(item,'value',{get(){throw Error('Input values must not be read');}});
    return item;
  }
  return {calls,events,windowEvents,doc,control,timeouts,
    advance:ms=>{now+=ms;intervals.find(item=>item.ms===5000)?.fn();},
    flush:()=>intervals.find(item=>item.ms===30000)?.fn(),
    hide:()=>{doc.visibilityState='hidden';events.visibilitychange();},
    show:()=>{doc.visibilityState='visible';events.visibilitychange();}};
}

test('visible time pauses in hidden tabs and on back-forward-cache suspension',()=>{
  const app=tracker();
  app.advance(15000);app.hide();
  assert.equal(app.calls.at(-1).payload.visible_ms,15000);
  app.advance(60000);app.show();app.advance(5000);app.flush();
  assert.equal(app.calls.at(-1).payload.visible_ms,20000);
  app.windowEvents.pagehide();app.advance(60000);app.windowEvents.pageshow();app.advance(5000);app.flush();
  assert.equal(app.calls.at(-1).payload.visible_ms,25000);
});

test('long device-sleep gaps are bounded instead of inflating viewing time',()=>{
  const app=tracker();app.advance(3600000);app.flush();
  assert.equal(app.calls.at(-1).payload.visible_ms,15000);
});

test('click and submit for one button count once and keep cumulative snapshots',()=>{
  const app=tracker(),button=app.control();
  app.events.click({target:button,isTrusted:true});
  app.events.submit({submitter:button,isTrusted:true});
  const call=app.calls.at(-1);
  assert.equal(call.payload.clicks.save_solution,1);
  assert.equal(call.opts.keepalive,true);
  assert.equal(call.opts.headers['X-CSRFToken'],'csrf');
  app.events.click({target:button,isTrusted:true});app.flush();
  assert.equal(app.calls.at(-1).payload.clicks.save_solution,2);
  assert.ok(app.calls.at(-1).payload.sequence>call.payload.sequence);
});

test('unclassified buttons never transmit their labels, values, or IDs',()=>{
  const app=tracker(),button=app.control({key:'unknown',text:'Private name or proof content'});
  app.events.click({target:button,isTrusted:true});app.flush();
  assert.equal(app.calls.at(-1).payload.clicks.other_button,1);
  assert.equal(JSON.stringify(app.calls).includes('Private name'),false);
});

test('chrome, disabled controls and synthetic clicks are excluded',()=>{
  const app=tracker();
  app.events.click({target:app.control({inPage:false}),isTrusted:true});
  const disabled=app.control();disabled.disabled=true;
  app.events.click({target:disabled,isTrusted:true});
  app.events.click({target:app.control(),isTrusted:false});app.flush();
  assert.deepEqual(app.calls.at(-1).payload.clicks,{});
});

test('a foreign telemetry destination cannot receive any data',()=>{
  assert.equal(tracker({endpoint:'https://elsewhere.example/collect/'}).calls.length,0);
});

test('a rejected token stops further reporting',async()=>{
  const app=tracker({status:403});await new Promise(resolve=>setImmediate(resolve));
  app.advance(5000);app.flush();assert.equal(app.calls.length,1);
});
