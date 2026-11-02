import test from 'node:test';
import assert from 'node:assert/strict';
import { cookieStatusView } from '../apps/web/src/cookie-status.ts';

test('cookie indicator distinguishes unknown, absent, expired and unreadable storage', () => {
  assert.equal(cookieStatusView().tone, 'neutral');
  assert.equal(cookieStatusView({state:'not_configured',expires_at:null}).tone, 'neutral');
  assert.equal(cookieStatusView({state:'expired',expires_at:null}).tone, 'error');
  assert.equal(cookieStatusView({state:'error',expires_at:null}).tone, 'error');
});
test('expiry warning starts at seven days; session cookies have unknown lifetime', () => {
  const now = Date.UTC(2026, 10, 2);
  const status = days => ({state:'configured',expires_at:(now + days * 86400000) / 1000});
  assert.equal(cookieStatusView(status(8), now).tone, 'success');
  assert.equal(cookieStatusView(status(7), now).tone, 'warning');
  assert.equal(cookieStatusView(status(-1), now).text, 'Обновление срока…');
  assert.equal(cookieStatusView({state:'configured',expires_at:null}, now).text, 'Срок не указан');
  assert.equal(cookieStatusView(status(8), now).text, 'Lifetime left: 8д 0ч 0м');
  assert.equal(cookieStatusView({state:'configured',expires_at:(now + (2 * 1440 + 3 * 60 + 4) * 60000 + 59000) / 1000}, now).text, 'Lifetime left: 2д 3ч 4м');
  assert.equal(cookieStatusView(status(365), now).text, 'Lifetime left: 365д 0ч 0м');
});
