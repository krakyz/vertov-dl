export type Format = {
  id: string; ext: string; height: number | null; vcodec: string | null; acodec: string | null;
  abr?: number | null; tbr?: number | null; asr?: number | null; audio_channels?: number | null;
  filesize?: number | null; filesize_approx?: number | null; protocol?: string;
};
export type Details = { artifact_media?: {media_type: 'video' | 'audio'; video_codec: string | null; audio_codec: string | null; width?: number | null; height?: number | null; fps?: number | null}; title?: string; duration?: number | null; formats?: Format[];
  uploader?: string | null; has_thumbnail?: boolean; source_probe_id?: string };
export type Job = {
  id: string; kind: 'probe' | 'download'; state: string; title: string; message: string;
  created: number; updated: number; preset: string; error_code: string | null; sha256: string | null;
  details: Details | null;
  progress: { downloaded: number; total: number | null; speed: number | null; eta: number | null } | null;
};
export type CookieStatus = { state: string; expires_at: number | null; count?: number; valid_count?: number; session_count?: number };
export type Runtime = { version: string; uptime_seconds: number;
  capabilities: { exact_formats: boolean; cookie_import?: boolean; queue_archive?: boolean; library?: boolean }; cookies: CookieStatus };
export type MediaEntry = { url: string; probeId?: string; downloadId?: string; pending: boolean; sending?: boolean; error?: string };
export type LibraryItem = Job & { size: number; completed_at: number; expires_at: number };
export type LibrarySnapshot = {items: LibraryItem[]; total_bytes: number; max_bytes: number; retention_hours: number};

export const MAX_LINKS = 20;
export const active = (job: Job) => ['queued', 'probing', 'downloading', 'processing'].includes(job.state);
export const labels: Record<string, string> = { queued: 'В очереди', probing: 'Получение данных',
  downloading: 'Загрузка', processing: 'Обработка', completed: 'Готово', failed: 'Ошибка', cancelled: 'Отменено', expired: 'Срок хранения истёк' };

export function normalizeLink(value: string): string {
  const text = value.trim();
  let url: URL;
  try { url = new URL(text); } catch { throw new Error('Укажи полный адрес с https:// или http://.'); }
  if (!['http:', 'https:'].includes(url.protocol) || url.username || url.password) {
    throw new Error('Нужна HTTP(S)-ссылка без встроенного логина и пароля.');
  }
  const youtube = ['youtube.com', 'www.youtube.com', 'm.youtube.com', 'music.youtube.com', 'youtube-nocookie.com', 'www.youtube-nocookie.com'];
  if (url.hostname === 'youtu.be' || youtube.includes(url.hostname)) {
    const id = url.hostname === 'youtu.be' ? url.pathname.split('/')[1]
      : url.searchParams.get('v') || (/^\/(shorts|embed|live)\//.test(url.pathname) ? url.pathname.split('/')[2] : null);
    if (!id || !/^[A-Za-z0-9_-]{11}$/.test(id)) throw new Error('В ссылке YouTube не найден ID отдельного видео.');
    return `https://www.youtube.com/watch?v=${id}`;
  }
  return url.href;
}

export function batchRows(current: string[]) {
  const filled = current.filter(value => value.trim());
  if (filled.length > MAX_LINKS) throw new Error(`Можно добавить до ${MAX_LINKS} ссылок за раз.`);
  return [...filled, ''];
}

export function pasteRows(current: string[], index: number, text: string, batch: boolean) {
  const incoming = text.split(/\r?\n/).map(value => value.trim()).filter(Boolean);
  if (!incoming.length) return { values: [...current], focus: index };
  if (!batch) return { values: [incoming[0]], focus: 0 };
  const filled = current.filter(value => value.trim());
  const start = current[index]?.trim() ? filled.length : current.slice(0, index).filter(value => value.trim()).length;
  filled.splice(start, 0, ...incoming);
  return { values: batchRows(filled), focus: start + incoming.length - 1 };
}

export function duration(value?: number | null) {
  if (value == null) return 'Длительность не указана';
  const seconds = Math.max(0, Math.floor(value));
  return [Math.floor(seconds / 3600), Math.floor(seconds / 60) % 60, seconds % 60]
    .map(part => String(part).padStart(2, '0')).join(':');
}
export function bytes(value?: number | null) {
  if (value == null) return '—';
  const unit = value >= 1024 ** 3 ? 3 : value >= 1024 ** 2 ? 2 : value >= 1024 ? 1 : 0;
  return `${(value / 1024 ** unit).toFixed(unit ? 1 : 0)} ${['Б', 'КиБ', 'МиБ', 'ГиБ'][unit]}`;
}
export function codec(value?: string | null) {
  if (!value || value === 'none') return '—';
  if (/^(hevc|h265|hev1|hvc1)/i.test(value)) return 'H.265';
  if (/^mp3$/i.test(value)) return 'MP3';
  if (/^(avc|h264)/i.test(value)) return 'H.264';
  if (/^vp0?9/i.test(value)) return 'VP9';
  if (/^(av01|av1)/i.test(value)) return 'AV1';
  if (/^(mp4a|aac)/i.test(value)) return 'AAC';
  return /opus/i.test(value) ? 'Opus' : value.split('.')[0];
}
export function formatLabel(format: Format) {
  const rate = format.abr ?? (format.vcodec === 'none' ? format.tbr : null);
  const size = format.height ? `${format.height}p` : rate ? `${Math.round(rate)} кбит/с` : format.vcodec === 'none' ? 'Битрейт не указан' : 'Без разрешения';
  return `ID ${format.id} · ${size} · ${format.ext} · ${codec(format.vcodec)} / ${codec(format.acodec)}`;
}
export function quality(details: Details | null) {
  if (!Array.isArray(details?.formats)) return '';
  const heights = details.formats.map(format => format.height || 0);
  const highest = Math.max(0, ...heights);
  return highest ? `До ${highest}p` : details ? 'Разрешение не указано' : '';
}

export function jobError(job: Pick<Job, 'error_code' | 'message'>) {
  return ['authentication', 'challenge'].includes(job.error_code || '')
    ? 'Обновите файл cookies.txt в настройках и повторите загрузку.' : job.message;
}
