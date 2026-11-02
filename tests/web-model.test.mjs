import test from 'node:test';
import assert from 'node:assert/strict';
import { batchRows, normalizeLink, pasteRows, quality } from '../apps/web/src/model.ts';

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
