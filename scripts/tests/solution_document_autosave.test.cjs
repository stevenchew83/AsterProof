const assert = require('node:assert/strict');
const {test} = require('node:test');
const {createDraftAutosave} = require('../../inspinia/static/js/solution-document-autosave.js');

function setup(t, save) {
  t.mock.timers.enable({apis: ['setTimeout', 'Date']});
  const state = {canSave: true, calls: []};
  const autosave = createDraftAutosave({
    canSave: () => state.canSave,
    save: () => { state.calls.push(Date.now()); return save?.(); },
    settled: () => {},
    now: Date.now,
  });
  return {state, autosave, tick: ms => t.mock.timers.tick(ms)};
}

test('draft autosave waits for two seconds without edits', async t => {
  const {state, autosave, tick} = setup(t);
  autosave.changed();
  tick(1500);
  autosave.changed();
  tick(1999);
  assert.deepEqual(state.calls, []);
  tick(1);
  await autosave.pending;
  assert.deepEqual(state.calls, [3500]);
  tick(30000);
  assert.equal(autosave.pending, null);
});

test('continuous edits force a save at 15 seconds', async t => {
  const {state, autosave, tick} = setup(t);
  autosave.changed();
  for (let edit = 0; edit < 14; edit++) {
    tick(1000);
    autosave.changed();
  }
  tick(999);
  assert.deepEqual(state.calls, []);
  tick(1);
  await autosave.pending;
  assert.deepEqual(state.calls, [15000]);
});

test('edits during an in-flight save wait for its acknowledgement and keep their own deadline', async t => {
  let release;
  const {state, autosave, tick} = setup(t, () => new Promise(resolve => { release = resolve; }));
  autosave.changed();
  tick(2000);
  await Promise.resolve();
  const firstSave = autosave.pending;
  autosave.changed();
  tick(4000);
  assert.deepEqual(state.calls, [2000]);
  release();
  await firstSave;
  tick(0);
  await Promise.resolve();
  assert.deepEqual(state.calls, [2000, 6000]);
  release();
  await autosave.pending;
});

test('a revert or explicit save cancels a scheduled autosave', t => {
  const {state, autosave, tick} = setup(t);
  autosave.changed();
  autosave.reset();
  tick(15000);
  assert.deepEqual(state.calls, []);
  assert.equal(autosave.pending, null);
});
