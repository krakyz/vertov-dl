import test from 'node:test';
import assert from 'node:assert/strict';
import { readWorkspace } from '../apps/web/src/workspace.ts';
import { AutoDownload } from '../apps/web/src/auto-download.ts';

test('working drafts, modes, links to jobs and pending transfers survive serialization', () => {
  const id='a'.repeat(32);
  const data={version:1,values:['unfinished draft',''],savedBatch:['unfinished draft',''],batch:true,advanced:true,
    quality:'720',entries:[{url:'https://example.org/video',probeId:id}],pendingDownloads:[id],token:'must-not-restore'};
  const result=readWorkspace(JSON.stringify(data));
  assert.deepEqual(result.values,data.values); assert.equal(result.batch,true); assert.equal(result.quality,'720');
  assert.equal(result.entries[0].probeId,id); assert.equal(result.token,undefined);
  const restored=new AutoDownload(); result.pendingDownloads.forEach(id=>restored.watch(id));
  const calls=[]; restored.update([{id,kind:'download',state:'completed'}],job=>calls.push(job.id));
  assert.deepEqual(calls,[id]); assert.deepEqual(restored.snapshot(),[]);
  restored.update([{id,kind:'download',state:'completed'}],job=>calls.push(job.id));
  assert.equal(calls.length,1);
});
test('invalid or oversized browser storage cannot restore arbitrary state', () => {
  assert.equal(readWorkspace('{bad'),undefined);
  assert.equal(readWorkspace('x'.repeat(256001)),undefined);
  assert.equal(readWorkspace(JSON.stringify({version:99})),undefined);
  const restored=readWorkspace(JSON.stringify({version:1,values:[''],entries:[{url:'https://example.org',probeId:'bad'}],pendingDownloads:['bad']}));
  assert.equal(restored.entries[0].probeId,undefined); assert.deepEqual(restored.pendingDownloads,[]);
});


test('browser dispatch history survives reload without restoring invalid IDs', () => {
  const id='a'.repeat(32);
  const result=readWorkspace(JSON.stringify({version:1,values:[''],entries:[],dispatchedDownloads:[id,'invalid']}));
  assert.deepEqual(result.dispatchedDownloads,[id]);
  assert.deepEqual(result.pendingDownloads,[]);
  assert.deepEqual(readWorkspace(JSON.stringify({version:1,values:[''],entries:[]})).dispatchedDownloads,[]);
});
