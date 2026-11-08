"use strict";

const IDLE_DELAY = 2000;
const MAX_WAIT = 15000;

function createDraftAutosave({canSave, save, settled, now = () => performance.now()}) {
  let timer, firstEdit = null, lastEdit, pending = null;

  function reset() {
    clearTimeout(timer);
    firstEdit = null;
  }

  function schedule() {
    clearTimeout(timer);
    if (firstEdit === null || pending || !canSave()) return;
    const deadline = Math.min(lastEdit + IDLE_DELAY, firstEdit + MAX_WAIT);
    timer = setTimeout(() => {
      if (!canSave()) return;
      reset();
      pending = Promise.resolve().then(save).finally(() => {
        pending = null;
        schedule();
        settled();
      });
    }, Math.max(0, deadline - now()));
  }

  return {
    changed() {
      lastEdit = now();
      firstEdit ??= lastEdit;
      schedule();
    },
    reset,
    schedule,
    get pending() { return pending; },
  };
}

module.exports = {createDraftAutosave};
