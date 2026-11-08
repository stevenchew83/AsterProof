const {test} = require('node:test');
const assert = require('node:assert/strict');
const {createRequests, filterURL, filterValues} = require('../../inspinia/static/js/student-detail.js');

function deferred() { let resolve, reject; const promise = new Promise((a,b) => {resolve=a; reject=b;}); return {promise, resolve, reject}; }
const flush = () => new Promise(resolve => setImmediate(resolve));
const ok = html => ({ok:true, status:200, redirected:false, text:async () => html});
function harness() {
    const calls=[], events=[], timers=new Map(); let timerID=0;
    const requests = createRequests({
        fetch: (url, options) => { const d=deferred(); calls.push({url, options, ...d}); return d.promise; },
        setTimeout: (callback, ms) => { timers.set(++timerID, {callback,ms}); return timerID; },
        clearTimeout: id => timers.delete(id),
        pending: () => events.push('pending'), settled: () => events.push('settled'),
        success: (html,url) => events.push({html,url}), failure: () => events.push('failed'),
        navigate: url => events.push({navigate:url})
    });
    return {requests,calls,events,timers,fire: () => { for (const [id,t] of timers) {timers.delete(id); t.callback();} }};
}

test('filters encode literal text, omit defaults and reset page/hash', () => {
    assert.equal(filterURL('https://local.test/rankings/students/3/?page=8#old',{q:'A [B].* & C',year:'2024',type:'scores'}),
        'https://local.test/rankings/students/3/?q=A+%5BB%5D.*+%26+C&year=2024&type=scores');
    assert.equal(filterURL('https://local.test/rankings/students/3/?page=8',{type:'achievements'}),'https://local.test/rankings/students/3/');
    assert.equal(filterURL('https://local.test/rankings/students/3/',{type:'all',discipline:'music',evidence:'pending'}),
        'https://local.test/rankings/students/3/?type=all&discipline=music&evidence=pending');
});
test('search debounces for 250ms and coalesces input', async () => {
    const h=harness(); h.requests.run('/a',true); h.requests.run('/ab',true);
    assert.equal(h.calls.length,0); assert.equal(h.timers.size,1); assert.equal([...h.timers.values()][0].ms,250);
    h.fire(); assert.equal(h.calls.length,1); assert.equal(h.calls[0].url,'/ab');
    assert.equal(h.calls[0].options.cache,'no-store'); assert.equal(h.calls[0].options.credentials,'same-origin');
    h.calls[0].resolve(ok('new')); await flush(); assert.deepEqual(h.events.at(-2),{html:'new',url:'/ab'});
});
test('chart links sync form filters and omit pagination or detail anchors', () => {
    assert.deepEqual(filterValues('https://local.test/students/3/?q=A+%26+B&year=2025&discipline=music&evidence=achievement_verified&page=4#student-record-1'),
        {q:'A & B',year:'2025',type:'achievements',discipline:'music',evidence:'achievement_verified'});
    assert.deepEqual(filterValues('https://local.test/students/3/'),
        {q:'',year:'',type:'achievements',discipline:'',evidence:''});
});
test('new request aborts earlier one; late success cannot overwrite', async () => {
    const h=harness(); h.requests.run('/old',false); h.requests.run('/new',false);
    assert.equal(h.calls[0].options.signal.aborted,true);
    h.calls[1].resolve(ok('new')); await flush(); h.calls[0].resolve(ok('old')); await flush();
    assert.deepEqual(h.events.filter(e => e.html),[{html:'new',url:'/new'}]);
});
test('changing input invalidates an old response during the debounce window', async () => {
    const h=harness(); h.requests.run('/old',false); h.requests.run('/typing',true);
    h.calls[0].resolve(ok('stale')); await flush();
    assert.equal(h.events.some(e => e.html),false); assert.equal(h.events.includes('settled'),false);
    h.fire(); h.calls[1].resolve(ok('current')); await flush(); assert.equal(h.events.at(-2).html,'current');
});
test('response body awaiting completion is also guarded', async () => {
    const h=harness(), body=deferred(); h.requests.run('/old',false);
    h.calls[0].resolve({...ok(''),text:()=>body.promise}); await flush();
    h.requests.run('/new',false); body.resolve('stale'); await flush();
    assert.equal(h.events.some(e => e.html),false);
});
test('network errors retain results and retry the failed URL', async () => {
    const h=harness(); h.requests.run('/page=2',false); h.calls[0].reject(new TypeError('offline')); await flush();
    assert.deepEqual(h.events.slice(-2),['failed','settled']);
    h.requests.retry(); assert.equal(h.calls[1].url,'/page=2'); h.calls[1].resolve(ok('retried')); await flush();
    assert.equal(h.events.at(-2).html,'retried');
});
test('HTTP failures and parser failures report refresh failure', async () => {
    const h=harness(); h.requests.run('/failure',false); h.calls[0].resolve({ok:false,status:500}); await flush();
    assert.ok(h.events.includes('failed'));
    const events=[]; const r=createRequests({fetch:async()=>ok('bad html'),pending(){},settled(){},success(){throw Error('bad HTML');},failure(){events.push('failed');}});
    r.run('/bad',false); await flush(); assert.deepEqual(events,['failed']);
});
test('expired sessions and access denials navigate normally', async () => {
    for (const response of [{ok:true,status:200,redirected:true,url:'/accounts/login/'},{ok:false,status:403,url:'/denied/'}]) {
        const h=harness(); h.requests.run('/detail',false); h.calls[0].resolve(response); await flush();
        assert.deepEqual(h.events.at(-2),{navigate:response.url}); assert.equal(h.events.includes('failed'),false);
    }
});
test('page exit cancels pending debounce and suppresses abort errors', async () => {
    const h=harness(); h.requests.run('/typing',true); h.requests.cancel(); assert.equal(h.timers.size,0);
    h.requests.run('/pending',false); h.requests.cancel(); assert.equal(h.calls[0].options.signal.aborted,true);
    h.calls[0].reject(Object.assign(new Error('cancelled'),{name:'AbortError'})); await flush();
    assert.equal(h.events.includes('failed'),false);
});
