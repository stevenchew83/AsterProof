const assert = require('node:assert/strict');
const {test} = require('node:test');
const {create, decode, KEY, TTL} = require('../../inspinia/static/js/solution-draft-recovery.js');

function document(title = 'My proof') {
  return {title, author_name:'Student', problem_statement:'Prove $x^2\\geq0$.',
    pdf_show_author:false, pdf_show_date:true, pdf_show_footer:false,
    blocks:[{block_type:'3', title:'Idea', body_format:'plain_text', body_source:'<script> stays literal'},
      {block_type:'4', title:'Proof', body_format:'latex', body_source:'\\[x^2\\geq0.\\]'}]};
}

function envelope(doc) {
  const savedAt = Date.now();
  return JSON.stringify({version:1, savedAt, expiresAt:savedAt+TTL, document:doc});
}

function controls(current, storage = new Map()) {
  function control() {
    const events = {};
    return {hidden:false, checked:false, textContent:'', addEventListener:(name, fn)=>{events[name]=fn;},
      fire:name=>events[name]?.({})};
  }
  const elements = Object.fromEntries(['enable','status','offer','offer-text','clear','restore']
    .map(name=>['[data-draft-'+name+']', control()]));
  globalThis.localStorage = {
    getItem:key=>storage.get(key)??null, setItem:(key,value)=>storage.set(key,value), removeItem:key=>storage.delete(key),
  };
  globalThis.addEventListener = ()=>{};
  const root = {hidden:true, querySelector:selector=>elements[selector]};
  const state = {document:structuredClone(current)};
  const recovery = create({root:{querySelector:()=>root}, snapshot:()=>state.document,
    restore:value=>{state.document=structuredClone(value);}});
  return {elements, state, storage, recovery};
}

test('device recovery is opt-in and restores all writing and choices without auto-replacing the current editor', ()=>{
  const original = document();
  original.blocks.reverse();
  const first = controls(original);
  assert.equal(first.elements['[data-draft-enable]'].disabled, false);
  first.recovery.changed(); first.recovery.flush();
  assert.equal(first.storage.has(KEY), false);
  first.elements['[data-draft-enable]'].checked = true;
  first.elements['[data-draft-enable]'].fire('change');
  assert.deepEqual(decode(first.storage.get(KEY),Date.now()).document, original);
  const second = controls(document('New writing'), first.storage);
  assert.equal(second.state.document.title, 'New writing');
  assert.equal(second.elements['[data-draft-offer]'].hidden, false);
  second.elements['[data-draft-restore]'].fire('click');
  assert.deepEqual(second.state.document, original);
  second.storage.set('unrelated-key','keep');
  second.elements['[data-draft-clear]'].fire('click');
  assert.equal(second.storage.has(KEY),false);
  assert.equal(second.storage.get('unrelated-key'),'keep');
  assert.deepEqual(second.state.document,original);
});

test('a stale tab cannot silently overwrite a different tab device draft', ()=>{
  const tab = controls(document('Older tab'));
  tab.elements['[data-draft-enable]'].checked = true;
  tab.elements['[data-draft-enable]'].fire('change');
  const newer = envelope(document('Newer tab'));
  tab.storage.set(KEY,newer);
  tab.state.document.title = 'Unsaved local edits';
  tab.recovery.flush();
  assert.equal(tab.storage.get(KEY),newer);
  assert.equal(tab.state.document.title,'Unsaved local edits');
  assert.equal(tab.elements['[data-draft-offer]'].hidden,false);
});

test('storage restrictions and quota errors retain the current writing', ()=>{
  const tab = controls(document());
  globalThis.localStorage.getItem = ()=>{throw new Error('blocked');};
  tab.elements['[data-draft-enable]'].checked = true;
  assert.doesNotThrow(()=>tab.recovery.flush());
  assert.match(tab.elements['[data-draft-status]'].textContent,/unavailable/);
  assert.deepEqual(tab.state.document,document());
  globalThis.localStorage.getItem = ()=>null;
  globalThis.localStorage.setItem = ()=>{throw new Error('quota');};
  tab.elements['[data-draft-enable]'].checked = true;
  assert.doesNotThrow(()=>tab.recovery.flush());
  assert.deepEqual(tab.state.document,document());
});

test('expired, malformed, unsupported and excessive drafts are rejected', ()=>{
  const now = Date.now();
  const valid = JSON.parse(envelope(document()));
  for (const value of [null, {}, {...valid,version:2}, {...valid,expiresAt:now-1},
    {...valid,savedAt:now+120000}, {...valid,document:{...document(),blocks:new Array(33).fill(document().blocks[0])}},
    {...valid,document:{...document(),blocks:[{...document().blocks[0],body_format:'html'}]}}]) {
    assert.equal(decode(JSON.stringify(value),now),null);
  }
  assert.equal(decode('{broken',now),null);
  assert.equal(decode('x'.repeat(400001),now),null);
});
