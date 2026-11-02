import test from 'node:test';
import assert from 'node:assert/strict';
import { batchRows, normalizeLink, pasteRows, quality, downloadStatus, thumbnailBadge } from '../apps/web/src/model.ts';

test('YouTube variants keep one video and remove playlist or mix context', () => {
  const id = 'jNQXAC9IVRw';
  for (const url of [`https://youtu.be/${id}?list=RD${id}`, `https://www.youtube.com/watch?v=${id}&list=PLtest`, `https://m.youtube.com/shorts/${id}`, `https://www.youtube.com/embed/${id}`]) {
    assert.equal(normalizeLink(url), `https://www.youtube.com/watch?v=${id}`);
  }
  assert.throws(() => normalizeLink('https://www.youtube.com/playlist?list=PLtest'));
  assert.throws(() => normalizeLink('javascript:alert(1)'));
  assert.throws(() => normalizeLink('https://user:password@example.com/video'));
});
test('batch paste preserves filled rows and inserts after the last filled row', () => {
  const current = ['first', '', 'third', ''];
  assert.deepEqual(pasteRows(current, 0, 'fourth\r\nfifth', true).values, ['first', 'third', 'fourth', 'fifth', '']);
  assert.deepEqual(current, ['first', '', 'third', '']);
  assert.deepEqual(pasteRows(['first', '', 'third'], 1, 'second\nextra', true).values, ['first', 'second', 'extra', 'third', '']);
});
test('batch limit rejects overflow without modifying existing values', () => {
  const current = Array.from({ length: 20 }, (_, i) => String(i));
  assert.throws(() => pasteRows(current, 0, 'overflow', true));
  assert.equal(current.length, 20);
  assert.deepEqual(pasteRows([''], 0, 'first\nsecond', false).values, ['first']);
});

test('batch always keeps exactly one empty tail, including at the limit', () => {
  assert.deepEqual(batchRows(['', '  ', '']), ['']);
  assert.deepEqual(batchRows(['first', '', 'second', '', '']), ['first', 'second', '']);
  const full = batchRows(Array.from({length:20}, (_,i) => String(i)));
  assert.equal(full.length,21); assert.equal(full.at(-1),'');
  assert.throws(() => pasteRows(full,20,'overflow',true));
  assert.deepEqual(pasteRows([''],0,'one\ntwo',true).values,['one','two','']);
});


test('restoring pending metadata tolerates partial details without formats', () => {
  for (const details of [null, {}, {queue_seconds: 1.2}, {title: 'Pending'}]) {
    assert.equal(quality(details), '');
  }
  assert.equal(quality({formats: []}), 'Разрешение не указано');
  assert.equal(quality({formats: [{height: 360}, {height: 1080}]}), 'До 1080p');
});


test('status includes media type and only claims browser dispatch when requested', () => {
  const job={kind:'download',preset:'best',details:null,state:'queued'};
  assert.equal(downloadStatus(job),'Видео в очереди');
  assert.equal(downloadStatus({...job,preset:'audio'}),'Аудио в очереди');
  assert.equal(downloadStatus({...job,state:'completed'},true),'Готово! Видео отправлено в браузер');
  assert.equal(downloadStatus({...job,state:'completed',preset:'audio'},true),'Готово! Аудио отправлено в браузер');
  assert.equal(downloadStatus({...job,state:'completed'}),'Готово! Видео доступно для скачивания');
  assert.equal(downloadStatus({...job,preset:'format:140',details:{formats:[{id:'140',vcodec:'none'}]},state:'processing'}),'Обработка аудио');
});


test('home thumbnail badge uses selection before download and actual resolution after processing', () => {
  const details={formats:[{id:'v',height:1080,vcodec:'avc1',ext:'mp4'},{id:'a',height:null,vcodec:'none',ext:'m4a'}]};
  assert.deepEqual(thumbnailBadge(undefined,details,{kind:'video',quality:'best'}),{kind:'video',label:'Видео · до 1080p'});
  assert.equal(thumbnailBadge(undefined,details,{kind:'video',formatId:'a'}).label,'Аудио · M4A');
  assert.equal(thumbnailBadge({preset:'audio',details},details,{kind:'video'}).label,'Аудио · MP3');
  assert.equal(thumbnailBadge({preset:'best',details:{artifact_media:{width:1920,height:1080}}},details,{kind:'video'}).label,'Видео · 1920×1080');
  assert.equal(thumbnailBadge(undefined,{}, {kind:'video'}).label,'Видео');
});
