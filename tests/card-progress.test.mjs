import test from 'node:test';
import assert from 'node:assert/strict';
import { CardProgress } from '../apps/web/src/card-progress.ts';
import { CancelButton } from '../apps/web/src/cancel-button.ts';

test('failure freezes last progress; retry starts from zero; completion fills card', () => {
  const meter = new CardProgress();
  const job = { id:'first', state:'downloading', progress:{downloaded:50,total:100} };
  assert.deepEqual(meter.update(job), {percent:50,tone:'success'});
  assert.deepEqual(meter.update({...job,state:'failed',progress:{downloaded:0,total:100}}), {percent:50,tone:'error'});
  assert.deepEqual(meter.update({id:'retry',state:'queued',progress:null}), {percent:0,tone:'success'});
  assert.equal(meter.update({id:'retry',state:'completed'}).percent, 100);
  assert.equal(new CardProgress().update({...job,state:'failed'}).percent, 50);
});
test('unknown size retains measured progress without inventing a percentage', () => {
  const meter = new CardProgress();
  assert.equal(meter.update({id:'one',state:'downloading',progress:null}).percent,0);
  meter.update({id:'one',state:'downloading',progress:{downloaded:30,total:100}});
  assert.equal(meter.update({id:'one',state:'processing',progress:null}).percent,30);
});
class Button extends EventTarget { textContent='';disabled=false;dataset={};title=''; }
test('cancel needs two clicks, survives progress updates and submits only once', async () => {
  const button = new Button(); const calls=[]; let resolve;
  const control = new CancelButton(button, id => { calls.push(id);return new Promise(done => {resolve=done;}); });
  control.update('one'); button.dispatchEvent(new Event('click'));
  assert.equal(button.textContent,'Подтвердить отмену'); assert.deepEqual(calls,[]);
  control.update('one'); assert.equal(button.textContent,'Подтвердить отмену');
  button.dispatchEvent(new Event('click')); button.dispatchEvent(new Event('click'));
  await Promise.resolve(); assert.deepEqual(calls,['one']); assert.equal(button.disabled,true);
  resolve(); await new Promise(setImmediate); control.update(undefined);
});
test('changing job discards cancellation confirmation', () => {
  const button=new Button(); const calls=[]; const control=new CancelButton(button,id=>calls.push(id));
  control.update('one'); button.dispatchEvent(new Event('click'));
  control.update('two'); button.dispatchEvent(new Event('click'));
  assert.deepEqual(calls,[]); assert.equal(button.textContent,'Подтвердить отмену');
  control.update(undefined);
});
