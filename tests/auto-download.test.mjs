import test from 'node:test';
import assert from 'node:assert/strict';
import { AutoDownload } from '../apps/web/src/auto-download.ts';

test('video and MP3 use the same automatic transfer after server processing', () => {
  const auto = new AutoDownload(), calls = [];
  const jobs = ['best', 'audio'].map(preset => ({id:preset,kind:'download',state:'processing',preset}));
  jobs.forEach(job => auto.watch(job.id));
  auto.update(jobs,job => calls.push(job.preset));
  assert.deepEqual(calls,[]);
  const completed = jobs.map(job => ({...job,state:'completed'}));
  auto.update(completed,job => calls.push(job.preset));
  auto.update(completed,job => calls.push(job.preset));
  assert.deepEqual(calls,['best','audio']);
});

test('only requested completed downloads start, once despite repeated snapshots', () => {
  const auto = new AutoDownload(), calls = [];
  const start = job => calls.push(job.id);
  auto.watch('new');
  auto.update([{id:'old',kind:'download',state:'completed'}, {id:'new',kind:'download',state:'processing'}], start);
  assert.deepEqual(calls,[]);
  const snapshot = [{id:'new',kind:'download',state:'completed'}];
  auto.update(snapshot,start); auto.update(snapshot,start);
  assert.deepEqual(calls,['new']);
});
test('failure, cancellation, logout and metadata never start a file transfer', () => {
  const auto = new AutoDownload(), calls = [], start = job => calls.push(job.id);
  for (const state of ['failed','cancelled','expired']) {
    auto.watch(state); auto.update([{id:state,kind:'download',state}],start);
    auto.update([{id:state,kind:'download',state:'completed'}],start);
  }
  auto.watch('probe'); auto.update([{id:'probe',kind:'probe',state:'completed'}],start);
  auto.watch('logout'); auto.clear(); auto.update([{id:'logout',kind:'download',state:'completed'}],start);
  assert.deepEqual(calls,[]);
});
