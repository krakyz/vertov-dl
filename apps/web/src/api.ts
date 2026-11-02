import type { CookieStatus, Job, LibrarySnapshot, Runtime } from './model';

export class ApiError extends Error {
  constructor(message: string, readonly status: number) { super(message); }
}

export async function request<T>(path: string, method = 'GET', body?: unknown): Promise<T> {
  let response: Response;
  try {
    response = await fetch(`/api${path}`, {
      method, credentials: 'same-origin',
      headers: body === undefined ? {} : { 'Content-Type': 'application/json' },
      body: body === undefined ? undefined : JSON.stringify(body),
    });
  } catch { throw new ApiError('Сервер недоступен. Проверь подключение и повтори запрос.', 0); }
  if (!response.ok) {
    const error = await response.json().catch(() => ({}));
    throw new ApiError(response.status === 401 ? 'Требуется вход' : typeof error.detail === 'string'
      ? error.detail : `Ошибка запроса (${response.status})`, response.status);
  }
  return response.json();
}

export const api = {
  jobs: () => request<Job[]>('/jobs'),
  status: () => request<Runtime>('/status'),
  library: () => request<LibrarySnapshot>('/library'),
  convertAudio: (id: string) => request<Job>(`/library/${id}/audio`, 'POST'),
  deleteLibraryFile: (id: string) => request(`/library/${id}`, 'DELETE'),
  importCookies: (content: string) => request<CookieStatus>('/cookies', 'PUT', { content }),
  deleteCookies: () => request<CookieStatus>('/cookies', 'DELETE'),
  login: (token: string) => request('/login', 'POST', { token }),
  logout: () => request('/logout', 'POST'),
  probe: (url: string, force = false) => request<Job>('/probes', 'POST', { url, force }),
  download: (probe_id: string, selection: { preset: string } | { format_id: string }) =>
    request<Job>('/downloads', 'POST', { probe_id, ...selection }),
  retry: (id: string) => request<Job>(`/jobs/${id}/retry`, 'POST'),
  cancel: (id: string) => request(`/jobs/${id}/cancel`, 'POST'),
  delete: (id: string) => request(`/jobs/${id}`, 'DELETE'),
};
