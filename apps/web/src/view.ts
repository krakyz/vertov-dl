import { element, node, query } from './dom';
import { active, bytes, duration, formatLabel, jobError, labels, quality } from './model';
import type { Job, MediaEntry } from './model';
import { CardProgress } from './card-progress';
import { CancelButton } from './cancel-button';
import { showThumbnail } from './thumbnail-preview';

export type CardActions = {
  download: (kind: 'video' | 'audio', formatId: string) => void;
  refresh: () => void; cancel: (id: string) => void | Promise<void>; retry: (id: string) => void;
};

export class MediaCard {
  readonly root: HTMLElement;
  private image: HTMLImageElement;
  private thumbnailKey = '';
  private formatsKey = '';
  private outputKey = '';
  private exactEnabled = false;
  private choice: HTMLSelectElement;
  private current?: Job;
  private progress = new CardProgress();
  private cancellation: CancelButton;

  constructor(private readonly actions: CardActions) {
    this.root = element<HTMLTemplateElement>('card-template').content.firstElementChild!.cloneNode(true) as HTMLElement;
    this.image = query<HTMLImageElement>(this.root, '.thumbnail-image');
    this.choice = query<HTMLSelectElement>(this.root, '.format-choice');
    this.image.addEventListener('load', () => {
      query(this.root, '.thumbnail').classList.toggle('portrait', this.image.naturalWidth / this.image.naturalHeight < 1.45);
      query<HTMLButtonElement>(this.root, '.thumbnail').disabled = false;
    });
    query(this.root, '.thumbnail').addEventListener('click', () => showThumbnail(this.image));
    this.image.addEventListener('error', () => {
      this.image.hidden = true;
      query<HTMLElement>(this.root, '.thumbnail-fallback').hidden = false;
      query<HTMLButtonElement>(this.root, '.thumbnail').disabled = true;
    });
    const mainButton = query<HTMLButtonElement>(this.root, '.download-video');
    this.cancellation = new CancelButton(mainButton, actions.cancel);
    mainButton.addEventListener('click', () => { if (!this.current || !active(this.current)) { if(this.current?.kind==='download' && this.current.state==='failed') actions.retry(this.current.id);else actions.download('video', this.choice.value); } });
    query(this.root, '.download-audio').addEventListener('click', () => {if(this.current?.kind==='download' && this.current.state==='failed') actions.retry(this.current.id);else actions.download('audio', '');});
    query(this.root, '.refresh-data').addEventListener('click', actions.refresh);
    this.choice.addEventListener('change', () => {
      if (!this.current || !active(this.current)) query(this.root, '.download-video').textContent = this.exactEnabled && this.choice.value ? 'Скачать формат' : 'Скачать видео';
    });
  }

  update(entry: MediaEntry, probe: Job | undefined, download: Job | undefined,
         options: { advanced: boolean; exact: boolean; authenticated: boolean; preferred: string; canDownload?: boolean }) {
    const ready = probe?.state === 'completed' && Array.isArray(probe.details?.formats);
    this.current = download || probe;
    const details = probe?.details || null;
    const title = details?.title || (probe?.state === 'failed' || entry.error ? 'Не удалось получить медиа' : 'Получение данных…');
    this.root.setAttribute('aria-label', title);
    query(this.root, '.thumbnail').setAttribute('aria-label', `Открыть превью: ${title}`);
    query(this.root, '.media-name').textContent = title;
    query(this.root, '.media-author').textContent = details?.uploader ? ` — ${details.uploader}` : '';
    const durationBadge = query<HTMLElement>(this.root, '.duration');
    durationBadge.textContent = details ? duration(details.duration) : '';
    durationBadge.hidden = details?.duration == null;
    query(this.root, '.quality').textContent = quality(details);
    this.root.classList.toggle('pending', entry.pending || Boolean(probe && active(probe)));
    const thumbKey = details?.has_thumbnail && probe ? probe.id : '';
    if (thumbKey !== this.thumbnailKey) {
      query<HTMLButtonElement>(this.root, '.thumbnail').disabled = true;
      this.thumbnailKey = thumbKey;
      this.image.hidden = !thumbKey;
      query<HTMLElement>(this.root, '.thumbnail-fallback').hidden = Boolean(thumbKey);
      if (thumbKey) {
        this.image.alt = title;
        this.image.src = `/api/jobs/${encodeURIComponent(thumbKey)}/thumbnail`;
      } else this.image.removeAttribute('src');
    }
    const occupied = entry.pending || entry.sending || Boolean(probe && active(probe)) || Boolean(download && active(download));
    for (const button of this.root.querySelectorAll<HTMLButtonElement>('.download-actions button')) {
      button.disabled = !ready || Boolean(occupied) || !options.authenticated || options.canDownload === false;
    }
    query(this.root, '.download-audio').classList.toggle('preferred', options.preferred === 'audio');
    query(this.root, '.download-video').classList.toggle('secondary', options.preferred === 'audio');
    query<HTMLElement>(this.root, '.card-options').hidden = !options.advanced || !ready;
    query<HTMLButtonElement>(this.root, '.refresh-data').disabled = Boolean(occupied);
    this.choice.disabled = !options.exact;
    this.exactEnabled = options.advanced && options.exact;
    query<HTMLElement>(this.root, '.exact-note').hidden = options.exact;
    const formats = details?.formats || [];
    const key = JSON.stringify(formats);
    if (this.formatsKey !== key) {
      this.formatsKey = key;
      const selected = this.choice.value;
      this.choice.replaceChildren(new Option('По пресету качества', ''));
      for (const [label, matches] of [
        ['Видео', (f: typeof formats[number]) => Boolean(f.vcodec && f.vcodec !== 'none') && f.acodec === 'none'],
        ['Аудио', (f: typeof formats[number]) => f.vcodec === 'none'],
        ['Видео + аудио', (f: typeof formats[number]) => Boolean(f.vcodec && f.vcodec !== 'none' && f.acodec && f.acodec !== 'none')],
        ['Другие', (f: typeof formats[number]) => !f.vcodec],
      ] as const) {
        const group = node('optgroup'); group.label = label;
        formats.filter(matches).forEach(format => group.append(new Option(formatLabel(format), format.id)));
        if (group.children.length) this.choice.append(group);
      }
      if (formats.some(format => format.id === selected)) this.choice.value = selected;
    }
    query(this.root, '.download-video').textContent = this.exactEnabled && this.choice.value ? 'Скачать формат' : 'Скачать видео';
    const working = Boolean(this.current && active(this.current));
    this.root.classList.toggle('working', working);
    this.cancellation.update(working ? this.current!.id : undefined, options.authenticated);
    const resumable=download?.state==='failed';
    query(this.root, '.download-audio').textContent=resumable && download.preset==='audio' ? 'Продолжить MP3' : 'Скачать MP3';
    if(resumable) {
      const audio=download.preset==='audio';
      query<HTMLButtonElement>(this.root,'.download-audio').disabled=!audio || !options.authenticated || Boolean(entry.sending);
      query<HTMLButtonElement>(this.root,'.download-video').disabled=audio || !options.authenticated || Boolean(entry.sending);
      if(!audio) query(this.root,'.download-video').textContent='Продолжить скачивание видео';
      query<HTMLElement>(this.root,'.card-options').hidden=true;
    }
    const fill = this.progress.update(download || (probe?.state !== 'completed' ? probe : undefined), Boolean(entry.error));
    this.root.style.setProperty('--job-percent', `${fill.percent}%`);
    this.root.dataset.progressTone = fill.tone;
    const meter = query<HTMLElement>(this.root, '.card-progress');
    meter.setAttribute('aria-valuenow', String(Math.round(fill.percent)));
    meter.setAttribute('aria-valuetext', `${labels[this.current?.state || ''] || 'Нет загрузки'} · ${Math.round(fill.percent)}%`);

    const status = query<HTMLElement>(this.root, '.download-status');
    status.classList.toggle('complete', !entry.error && !entry.sending && download?.state === 'completed');
    status.classList.toggle('queued', !entry.error && !entry.sending && (download || probe)?.state === 'queued');
    const statusJob = download || probe;
    const animating = !entry.error && (entry.sending || (statusJob ? ['probing', 'downloading', 'processing'].includes(statusJob.state) : entry.pending));
    status.classList.toggle('active-status', Boolean(animating));
    status.hidden = false;
    status.classList.remove('failure');
    if (entry.error) { status.textContent = entry.error; status.classList.add('failure'); }
    else if (entry.sending) status.textContent = 'Постановка в очередь…';
    else if (download) {
      status.textContent = download.state === 'failed' ? jobError(download) : download.state === 'expired' ? download.message : labels[download.state] || download.state;
      status.classList.toggle('failure', download.state === 'failed');
    } else if (probe && probe.state !== 'completed') {
      status.textContent = probe.state === 'failed' ? jobError(probe) : probe.state === 'expired' ? probe.message : labels[probe.state] || probe.state;
      status.classList.toggle('failure', probe.state === 'failed');
    } else if (entry.pending) status.textContent = 'Получение данных…';
    else { status.hidden = true; status.textContent = ''; }

    const output = query<HTMLElement>(this.root, '.job-output');
    const outputKey = `${download?.id}:${download?.state}|${probe?.id}:${probe?.state}|${entry.error || ''}`;
    if (outputKey !== this.outputKey) {
      this.outputKey = outputKey;
      output.replaceChildren();
      const current = download || probe;
      if (current && ['failed', 'cancelled', 'expired'].includes(current.state) && !(current.kind==='download' && current.state==='failed')) {
        const retry = node('button', 'Повторить', 'inline-action'); retry.type = 'button';
        retry.addEventListener('click', () => this.actions.retry(current.id)); output.append(retry);
      } else if (entry.error && !entry.pending) {
        const retry = node('button', 'Повторить', 'inline-action'); retry.type = 'button';
        retry.addEventListener('click', this.actions.refresh); output.append(retry);
      }

    }
    if (download && active(download) && download.progress) {
      const data = download.progress;
      status.textContent += ` · ${bytes(data.downloaded)} / ${bytes(data.total)} · ${bytes(data.speed)}/с`;
      meter.title = 'Прогресс текущего потока; видео и аудио могут загружаться отдельно.';
    }
    // The animated suffix supplies punctuation without restarting on SSE updates.
    status.textContent = status.textContent?.replace(/[.…]+$/u, '') || '';
  }
}

export class QueueView {
  private rows = new Map<string, { root: HTMLElement; title: HTMLElement; status: HTMLElement; actions: HTMLElement; key: string }>();
  constructor(private root: HTMLElement, private actions: { cancel: (id: string) => void | Promise<void>; retry: (id: string) => void; delete: (id: string) => void }) {}
  update(jobs: Job[]) {
    const ids = new Set(jobs.map(job => job.id));
    for (const [id, row] of this.rows) if (!ids.has(id)) { row.root.remove(); this.rows.delete(id); }
    if (!jobs.length) {
      this.root.replaceChildren(node('p', 'Очередь пуста.', 'muted')); this.rows.clear(); return;
    }
    const ordered: HTMLElement[] = [];
    for (const job of jobs) {
      let row = this.rows.get(job.id);
      if (!row) {
        const root = node('article', undefined, 'queue-row');
        const title = node('h3'); const status = node('p', undefined, 'muted'); const actions = node('div', undefined, 'queue-actions');
        root.append(title, status, actions); row = { root, title, status, actions, key: '' }; this.rows.set(job.id, row);
      }
      row.title.textContent = job.title;
      row.status.textContent = `${job.kind === 'probe' ? 'Метаданные' : 'Загрузка'} · ${labels[job.state] || job.state}${job.state === 'failed' ? ` · ${jobError(job)}` : ''}`;
      if (active(job) && job.progress) row.status.textContent += ` · ${bytes(job.progress.downloaded)} / ${bytes(job.progress.total)}`;
      if (row.key !== job.state) {
        row.key = job.state; row.actions.replaceChildren();
        const button = (label: string, action: () => void) => { const result = node('button', label, 'inline-action'); result.type = 'button'; result.addEventListener('click', action); return result; };
        if (active(job)) {
          const cancel = node('button', 'Отменить…', 'inline-action'); cancel.type = 'button';
          new CancelButton(cancel, this.actions.cancel).update(job.id);
          row.actions.append(cancel);
        }
        else {
          if (job.kind === 'download' && job.state === 'completed') {
            const file = node('a', 'Сохранить файл', 'inline-action'); file.href = `/api/jobs/${encodeURIComponent(job.id)}/file`; file.setAttribute('download', ''); row.actions.append(file);
          }
          if (['failed', 'cancelled', 'expired'].includes(job.state)) row.actions.append(button('Повторить', () => this.actions.retry(job.id)));
          row.actions.append(button('Удалить', () => this.actions.delete(job.id)));
        }
      }
      ordered.push(row.root);
    }
    // Existing rows retain their DOM nodes and handlers during SSE updates.
    for (const root of ordered) this.root.append(root);
    for (const child of [...this.root.children]) if (!child.classList.contains('queue-row')) child.remove();
  }
}
