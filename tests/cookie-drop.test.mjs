import test from 'node:test';
import assert from 'node:assert/strict';
import { bindCookieDrop } from '../apps/web/src/cookie-drop.ts';

function setup() {
  const target = new EventTarget(), windowTarget = new EventTarget();
  const state = { hints: [], imports: [], errors: [], busy: false };
  bindCookieDrop(target, windowTarget, {
    hint: value => state.hints.push(value), busy: () => state.busy,
    importFile: file => state.imports.push(file), error: message => state.errors.push(message),
  });
  const dispatch = (type, files = [], types = ['Files'], items = [{kind:'file',type:'text/plain'}]) => {
    const event = new Event(type, { cancelable: true });
    event.dataTransfer = { types, files, items, dropEffect: '' };
    target.dispatchEvent(event);
    return event;
  };
  return { state, dispatch, windowTarget };
}
test('file drop imports exactly one file and prevents browser navigation', () => {
  const { state, dispatch } = setup(); const file = { name: 'cookies.txt' };
  dispatch('dragenter'); dispatch('dragenter'); dispatch('dragleave');
  assert.deepEqual(state.hints, [true, true]);
  const over = dispatch('dragover'); assert.equal(over.dataTransfer.dropEffect, 'copy');
  const drop = dispatch('drop', [file]); assert.equal(drop.defaultPrevented, true);
  assert.deepEqual(state.imports, [file]); assert.equal(state.hints.at(-1), false);
});
test('text drag is ignored; multiple files are rejected; busy imports are not duplicated', () => {
  const { state, dispatch, windowTarget } = setup();
  assert.equal(dispatch('drop', [], ['text/plain']).defaultPrevented, false);
  dispatch('drop', [{}, {}]); assert.equal(state.errors.length, 1);
  state.busy = true; dispatch('drop', [{}]); assert.equal(state.imports.length, 0);
  assert.equal(dispatch('dragover').dataTransfer.dropEffect, 'none');
  state.busy = false; dispatch('dragenter'); windowTarget.dispatchEvent(new Event('blur'));
  assert.equal(state.hints.at(-1), false);
});

test('non-TXT files never activate the hint or import; uppercase TXT is accepted', () => {
  const {state,dispatch} = setup();
  for (const name of ['video.mp4','image.png','cookies.json','text.log']) {
    dispatch('dragenter',[{name}]);
    assert.equal(state.hints.at(-1),false);
    assert.equal(dispatch('dragover',[{name}]).dataTransfer.dropEffect,'none');
    dispatch('drop',[{name}]);
  }
  assert.deepEqual(state.imports,[]);
  dispatch('dragenter',[],['Files'],[{kind:'file',type:'image/png'}]);
  assert.equal(state.hints.at(-1),false);
  dispatch('drop',[{name:'COOKIES.TXT'}]);
  assert.equal(state.imports.length,1);
});
