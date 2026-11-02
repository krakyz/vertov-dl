import type { CookieStatus } from './model';

export function cookieStatusView(cookies?: CookieStatus, now = Date.now()) {
  if (!cookies) return { tone: 'neutral', text: 'Нет данных' };
  if (cookies.state === 'not_configured') return { tone: 'neutral', text: 'Не импортированы' };
  if (cookies.state === 'error') return { tone: 'error', text: 'Ошибка хранения' };
  if (cookies.state === 'expired') return { tone: 'error', text: 'Истекли' };
  if (cookies.state !== 'configured') return { tone: 'neutral', text: 'Нет данных' };
  if (!cookies.expires_at) return { tone: 'warning', text: 'Срок не указан' };
  const remaining = cookies.expires_at * 1000 - now;
  if (remaining <= 0) return { tone: 'warning', text: 'Обновление срока…' };
  const minutes = Math.floor(remaining / 60000);
  const lifetime = `${Math.floor(minutes / 1440)}д ${Math.floor(minutes / 60) % 24}ч ${minutes % 60}м`;
  return {
    tone: remaining <= 7 * 86400000 ? 'warning' : 'success',
    text: `Lifetime left: ${lifetime}`,
  };
}
