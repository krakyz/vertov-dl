import { reconcileChildren, frameScheduler } from './rendering';
import { LibraryView } from './library-view';
import { confirmDelete } from './confirm-delete';
import { WORKSPACE_KEY, readWorkspace } from './workspace';
import { bindCookieDrop } from './cookie-drop';
import { cookieStatusView } from './cookie-status';
import { AutoDownload } from './auto-download';
import { api, ApiError } from './api';
import { element, node, query } from './dom';
import { MAX_LINKS, active, batchRows, bytes, normalizeLink, pasteRows } from './model';
import type { CookieStatus, Job, LibrarySnapshot, MediaEntry, Runtime } from './model';
import { MediaCard, QueueView } from './view';

let values = [''], savedBatch: string[] = [], batch = false, advanced = false, authenticated = false;
let jobs = new Map<string, Job>(), runtime: Runtime | null = null, events: EventSource | null = null;
let timer: ReturnType<typeof setTimeout>;
let cookieBusy = false;
let cookieStatusFresh = false;
let layoutMotion: Animation | undefined;
const entries = new Map<string, MediaEntry>(), cards = new Map<string, MediaCard>();
const autoDownload = new AutoDownload();
const dispatchedDownloads = new Set<string>();
const queueEntries = new Map<string, MediaEntry>();
const deleting = new Set<string>();
let clearing = false;
let currentView: 'home' | 'library' = 'home';
let libraryData: LibrarySnapshot | undefined;
let libraryLoading = false;
const libraryDeleting = new Set<string>();
const removedLibraryFiles = new Set<string>();
let restored: ReturnType<typeof readWorkspace>;
try { restored = readWorkspace(localStorage.getItem(WORKSPACE_KEY)); } catch {}
if (restored) {
  values = restored.batch ? batchRows(restored.values) : [restored.values[0] || ''];
  savedBatch = restored.savedBatch; batch = restored.batch; advanced = restored.advanced;
  for (const entry of restored.entries) entries.set(entry.url, {...entry, pending:false});
  for (const id of restored.dispatchedDownloads) dispatchedDownloads.add(id);
  for (const id of restored.pendingDownloads) autoDownload.watch(id);
}
function saveWorkspace() {
  try { localStorage.setItem(WORKSPACE_KEY, JSON.stringify({version:1, values, savedBatch, batch, advanced,
    quality: element<HTMLSelectElement>('quality').value,
    entries: [...entries.values()].map(({url,probeId,downloadId}) => ({url,probeId,downloadId})),
    pendingDownloads: autoDownload.snapshot(), dispatchedDownloads:[...dispatchedDownloads].slice(-1000)})); } catch {}
}
let preferred = 'video';
try { preferred = localStorage.getItem('vertovdl-format') === 'audio' ? 'audio' : 'video'; } catch {}
const auth = element<HTMLDialogElement>('auth-dialog'), settings = element<HTMLDialogElement>('settings-dialog');
const feedback = (message = '') => { const el=element('feedback');el.textContent=message;el.hidden=!message; };
let libraryToastTimer: ReturnType<typeof setTimeout> | undefined;
const closeLibraryToast = () => { clearTimeout(libraryToastTimer);element('library-feedback').hidden=true;element('library-toast-message').textContent=''; };
const scheduleLibraryToast = () => { clearTimeout(libraryToastTimer);libraryToastTimer=setTimeout(closeLibraryToast,7000); };
const libraryFeedback = (message = '') => {
  if(!message) {closeLibraryToast();return;}
  element('library-toast-message').textContent=message;
  element('library-feedback').hidden=false;
  scheduleLibraryToast();
};
element('library-toast-close').addEventListener('click',closeLibraryToast);
element('library-feedback').addEventListener('mouseenter',()=>clearTimeout(libraryToastTimer));
element('library-feedback').addEventListener('mouseleave',scheduleLibraryToast);
element('library-feedback').addEventListener('focusin',()=>clearTimeout(libraryToastTimer));
element('library-feedback').addEventListener('focusout',scheduleLibraryToast);
function serverStatus(text: string, tone: 'neutral' | 'warning' | 'error' | 'success') {
  element('server-uptime').textContent = text;
  const indicator = element('server-indicator');
  indicator.dataset.tone = tone;
  indicator.setAttribute('aria-label', text);
}
function sessionUI() {
  for (const id of ['logout', 'settings-session']) element(id).textContent = authenticated ? 'Выйти' : 'Войти';
  renderCookies(runtime?.cookies);
}
function renderCookies(cookies?: CookieStatus) {
  const configured = cookies && cookies.state !== 'not_configured';
  let summary = 'Не импортированы';
  if (!authenticated) summary = 'Для импорта требуется вход';
  else if (!cookies) summary = 'Нет данных';
  else if (cookies.state === 'error') summary = 'Не удалось расшифровать. Импортируй файл заново.';
  else if (cookies.state === 'expired') summary = `Все cookies истекли (${cookies.count || 0}). Обнови файл.`;
  else if (configured) {
    summary = `Действующих: ${cookies.valid_count || 0} из ${cookies.count || 0}`;
    if (cookies.session_count) summary += ` · ${cookies.session_count} сессионных без срока`;
    if (cookies.expires_at) summary += ` · ближайшее истечение: ${new Date(cookies.expires_at * 1000).toLocaleString('ru')}`;
    summary += '. Сайт может отозвать сессию раньше.';
  }
  element('cookies-summary').textContent = summary;
  const view = cookieStatusView(authenticated && cookieStatusFresh ? cookies : undefined);
  if (cookieBusy) { view.tone = 'warning'; view.text = 'Обновление cookies…'; }
  const lifetime = element('cookie-lifetime');
  lifetime.textContent = view.text;
  lifetime.title = authenticated && cookieStatusFresh ? summary : 'Состояние cookies неизвестно: нет актуальных данных сервера.';
  const indicator = element('cookie-indicator');
  indicator.dataset.tone = view.tone;
  indicator.setAttribute('aria-label', `${view.text}. ${lifetime.title}`);
  element<HTMLButtonElement>('cookies-delete').disabled = cookieBusy || !authenticated || !configured;
  element<HTMLInputElement>('cookies-file').disabled = cookieBusy || !authenticated;
}
function cookieFeedback(message: string, error = false) {
  const target = element('cookies-feedback'); target.textContent = message; target.hidden = !message;
  target.classList.toggle('failure', error);
  feedback(message);
}
async function importCookieFile(file: File) {
  if (cookieBusy) return;
  if (!authenticated) { cookieFeedback('Войди на сервер и повтори импорт.', true); needLogin(); return; }
  if (!/\.txt$/i.test(file.name) || file.size > 256 * 1024 || !file.size) {
    cookieFeedback('Нужен непустой cookies.txt размером до 256 КиБ.', true); return;
  }
  cookieBusy = true; renderCookies(runtime?.cookies); cookieFeedback('Импорт cookies…');
  try {
    const cookies = await api.importCookies(await file.text());
    if (runtime) runtime.cookies = cookies;
    cookieFeedback(cookies.state === 'expired' ? 'Файл импортирован, но все cookies уже истекли.' : 'Cookies импортированы. Обнови данные медиа или повтори загрузку, чтобы применить их.');
    await status();
  } catch (error) { cookieFeedback((error as Error).message, true); if (error instanceof ApiError && error.status === 401) needLogin(); }
  finally { cookieBusy = false; renderCookies(runtime?.cookies); element<HTMLInputElement>('cookies-file').value = ''; }
}
function needLogin() { serverStatus('Требуется вход', 'neutral'); authenticated = false; events?.close(); events = null; sessionUI(); if (!auth.open) auth.showModal(); }
function failure(error: unknown, report = feedback) {
  if (error instanceof ApiError && error.status === 0) { serverStatus('Нет подключения', 'error'); cookieStatusFresh = false; renderCookies(runtime?.cookies); }
  if (error instanceof ApiError && error.status === 401) needLogin();
  report(error instanceof Error ? error.message : 'Не удалось выполнить запрос.');
}
const cardEntries = new WeakMap<MediaCard, MediaEntry>();
const render = frameScheduler(renderNow);
function renderNow() {
  if (authenticated) autoDownload.update(jobs.values(), deliverFile);
  const panel = document.querySelector<HTMLElement>('.panel')!;
  const downloader = document.querySelector<HTMLElement>('.downloader')!;
  const compact = values.some(value => value.trim()) || jobs.size > 0;
  let previousTop: number | undefined;
  if (panel.classList.contains('has-input') !== compact) {
    previousTop = downloader.getBoundingClientRect().top;
    layoutMotion?.cancel();
    panel.classList.toggle('has-input', compact);
  }
  const visible: string[] = [];
  for (const value of values) {
    if (!value.trim()) continue;
    try { const url = normalizeLink(value); if (entries.has(url) && !visible.includes(url)) visible.push(url); } catch {}
  }
  const roots: HTMLElement[] = [];
  const makeCard = (key: string, entry: MediaEntry, probeJob?: Job, downloadJob?: Job, job?: Job) => {
    if (!cards.has(key)) {
      const currentEntry = () => cardEntries.get(card)!;
      const card = new MediaCard({download: (kind,id) => void download(currentEntry(),kind,id),
        refresh: () => { const entry = currentEntry(); if (entry.url) void probe(entry,true); else feedback('Для обновления данных введи ссылку заново.'); },
        cancel: id => cancel(id), retry: id => void retry(id)});
      {
        const remove = node('button','×','queue-remove'); remove.type='button';
        remove.addEventListener('click',() => { const id = card.root.dataset.jobId; if (id) void deleteJob(id); });
        card.root.querySelector('.media-heading')!.append(remove);
      }
      cards.set(key,card);
    }
    const card = cards.get(key)!;
    cardEntries.set(card, entry);
    card.root.querySelector<HTMLButtonElement>('.queue-remove')!.hidden = !job;
    card.update(entry,probeJob,downloadJob,{advanced,exact:Boolean(runtime?.capabilities.exact_formats),authenticated,preferred,quality:element<HTMLSelectElement>('quality').value,
      dispatched: Boolean(downloadJob && dispatchedDownloads.has(downloadJob.id)),
      canDownload: !job || Boolean(entry.probeId && probeJob?.state === 'completed')});
    if (job) {
      card.root.dataset.jobId = job.id;
      const remove = card.root.querySelector<HTMLButtonElement>('.queue-remove')!;
      remove.disabled = !authenticated || !runtime?.capabilities.queue_archive || active(job) || clearing || deleting.has(job.id);
      const failedDownload = job.kind==='download' && job.state==='failed';
      if (remove.dataset.mode !== (failedDownload ? 'delete' : 'hide')) {
      remove.dataset.mode = failedDownload ? 'delete' : 'hide';
      remove.replaceChildren();
      if (failedDownload) remove.textContent = 'Удалить';
      else {
        const icon = document.createElement('img');
        icon.src = 'assets/594c9.svg'; icon.width = 17; icon.height = 17; icon.alt = '';
        remove.append(icon);
      }
      }
      remove.classList.toggle('queue-remove-icon', !failedDownload);
      remove.setAttribute('aria-label', failedDownload ? 'Удалить загрузку и временные файлы' : 'Скрыть задачу');
      remove.title = active(job) ? 'Сначала отмените задачу' : job.kind==='download' && job.state==='failed' ? 'Удалить загрузку и временные файлы' : 'Убрать запись из списка; файл останется в библиотеке';
    }
    roots.push(card.root);
  };
  for (const job of [...jobs.values()].sort((a,b) => b.created-a.created)) {
    const linked = [...entries.values()].find(item => job.kind === 'probe' ? item.probeId === job.id : item.downloadId === job.id);
    if (!queueEntries.has(job.id)) queueEntries.set(job.id,{url:linked?.url || '',pending:false});
    const entry = queueEntries.get(job.id)!;
    if (linked?.url) entry.url=linked.url;
    entry.probeId=job.kind === 'probe' ? job.id : job.details?.source_probe_id;
    entry.downloadId=job.kind === 'download' ? job.id : undefined;
    const parent = jobs.get(entry.probeId || '');
    const displayProbe = job.kind === 'probe' ? job : parent || {...job,kind:'probe' as const,state:'completed'};
    makeCard(`job:${job.id}`,entry,displayProbe,job.kind === 'download' ? job : undefined,job);
  }
  for (const url of visible) {
    const entry=entries.get(url)!;
    if (!entry.probeId && (entry.pending || entry.error)) makeCard(`draft:${url}`,entry);
  }
  for (const [key,card] of cards) if (!roots.includes(card.root)) { card.dispose(); cards.delete(key); }
  for (const id of queueEntries.keys()) if (!jobs.has(id)) queueEntries.delete(id);
  element('queue-toolbar').hidden = !jobs.size;
  element('queue-count').textContent = `Задач: ${jobs.size}`;
  element<HTMLButtonElement>('clear-jobs').disabled = clearing || !authenticated || !runtime?.capabilities.queue_archive || ![...jobs.values()].some(job => !active(job));
  const results = element('results');
  reconcileChildren(results, roots);
  document.querySelector('.panel')!.classList.toggle('has-results', roots.length > 0);
  if (currentView === 'home' && previousTop !== undefined && !matchMedia('(prefers-reduced-motion: reduce)').matches) {
    const offset = previousTop - downloader.getBoundingClientRect().top;
    layoutMotion = downloader.animate([{ transform: `translateY(${offset}px)` }, { transform: 'translateY(0)' }],
      { duration: 240, easing: 'cubic-bezier(.2,.7,.2,1)' });
  }
  queue.update([...jobs.values()].sort((a, b) => b.created - a.created));
  saveWorkspace();
}
function deliverFile(job: Job) {
  const link=document.createElement('a');link.href=`/api/jobs/${encodeURIComponent(job.id)}/file`;
  link.download='';link.hidden=true;document.body.append(link);
  try {saveWorkspace();link.click();dispatchedDownloads.add(job.id);saveWorkspace();}
  finally {link.remove();}
}
function rememberJob(job: Job) {
  // A very small file may finish via SSE before its POST response reaches us.
  const latest = jobs.get(job.id);
  if (!latest || latest.updated <= job.updated) jobs.set(job.id, job);
}
async function probe(entry: MediaEntry, force = false) {
  if (entry.pending) return;
  if (!authenticated) { needLogin(); return; }
  entry.pending = true; entry.error = undefined; render();
  try { const previousKey = entry.probeId ? `job:${entry.probeId}` : `draft:${entry.url}`;
    const job = await api.probe(entry.url,force);
    const previousCard = cards.get(previousKey);
    if (previousCard && !cards.has(`job:${job.id}`)) { cards.delete(previousKey); cards.set(`job:${job.id}`, previousCard); }
    queueEntries.set(job.id,entry);
    entry.probeId = job.id; entry.downloadId = undefined;
    const linked=entries.get(entry.url); if (linked) { linked.probeId=job.id; linked.downloadId=undefined; } rememberJob(job); }
  catch (error) { entry.error = error instanceof Error ? error.message : 'Ошибка запроса'; failure(error); }
  finally { entry.pending = false; render(); }
}
function resolve() {
  feedback();
  const errors: string[] = [];
  values.forEach((value, index) => {
    const input = element('links-box').querySelectorAll('input')[index];
    input?.removeAttribute('aria-invalid');
    if (!value.trim()) return;
    try {
      const url = normalizeLink(value);
      const entry = entries.get(url) ?? { url, pending: false };
      entries.set(url, entry);
      if (entry.pending || entry.sending || entry.error) return;
      if (jobs.has(entry.probeId || '') || jobs.has(entry.downloadId || '')) return;
      entry.probeId = undefined;
      entry.downloadId = undefined;
      void probe(entry);
    } catch (error) { input?.setAttribute('aria-invalid', 'true'); errors.push(`${index + 1}: ${(error as Error).message}`); }
  });
  if (errors.length) feedback(errors.join(' '));
  render();
}
function schedule() { clearTimeout(timer); render(); timer = setTimeout(resolve, 500); }
function rows(focus?: number) {
  if (batch) values = batchRows(values);
  const box = element('links-box'); box.classList.toggle('batch-mode', batch);
  box.replaceChildren(...values.map((value, index) => {
    const row = element<HTMLTemplateElement>('link-row-template').content.firstElementChild!.cloneNode(true) as HTMLElement;
    const input = query<HTMLInputElement>(row, 'input'), clear = query<HTMLButtonElement>(row, '.clear'), paste = query<HTMLButtonElement>(row, '.paste');
    input.value = value; input.setAttribute('aria-label', batch ? `Ссылка ${index + 1}` : 'Ссылка на медиа');
    const emptyTail = batch && index === values.length - 1;
    row.classList.toggle('empty-row', emptyTail);
    if (emptyTail) {
      input.placeholder = values.length > MAX_LINKS ? 'Лимит: 20 ссылок' : 'Добавить ссылку…';
      input.readOnly = values.length > MAX_LINKS;
      paste.disabled = input.readOnly;
    }
    clear.setAttribute('aria-label', `Очистить ссылку ${index + 1}`);
    query<HTMLElement>(row, '.search').hidden = batch;
    const number = query<HTMLElement>(row, '.row-number'); number.hidden = !batch; number.textContent = String(index + 1);
    const sync = () => { clear.hidden = !input.value; paste.hidden = Boolean(input.value); };
    sync();
    const updateValue = (composing = false) => {
      values[index] = input.value; sync();
      if (batch && !composing) {
        const normalized = batchRows(values);
        if (normalized.length !== values.length || normalized.some((value, i) => value !== values[i])) {
          const nextFocus = input.value.trim() ? Math.min(index, normalized.length - 1) : normalized.length - 1;
          values = normalized; rows(nextFocus);
        }
      }
      schedule();
    };
    input.addEventListener('input', event => updateValue(event instanceof InputEvent && event.isComposing));
    input.addEventListener('compositionend', () => updateValue());
    const insert = (text: string) => {
      try { const result = pasteRows(values, index, text, batch); values = result.values; rows(result.focus); schedule(); } catch (error) { failure(error); }
    };
    input.addEventListener('paste', event => {
      const text = event.clipboardData?.getData('text');
      if (text && /\r|\n/.test(text)) { event.preventDefault(); insert(text); }
    });
    paste.addEventListener('click', async () => { try { insert(await navigator.clipboard.readText()); } catch { feedback('Вставь ссылку сочетанием Ctrl + V.'); input.focus(); } });
    clear.addEventListener('click', () => { values[index] = ''; rows(index); schedule(); });
    input.addEventListener('keydown', event => {
      if (event.key !== 'Enter') return;
      event.preventDefault();
      if (batch && event.shiftKey) { rows(values.length - 1); }
      else resolve();
    });
    return row;
  }));
  if (focus !== undefined) box.querySelectorAll('input')[Math.min(focus, values.length - 1)]?.focus();
}
async function afterCancellation<T>(action: () => Promise<T>): Promise<T> {
  const deadline = performance.now() + 5000;
  while (true) {
    try { return await action(); }
    catch (error) {
      if (!(error instanceof ApiError) || error.status !== 409 ||
          error.message !== 'Подождите завершения отмены' || performance.now() >= deadline) throw error;
      await new Promise(resolve => setTimeout(resolve, 250));
    }
  }
}

async function download(entry: MediaEntry, kind: 'video' | 'audio', id: string) {
  if (!entry.probeId || entry.sending) return;
  entry.sendingKind=kind==='audio' || (id && jobs.get(entry.probeId || '')?.details?.formats?.find(format=>format.id===id)?.vcodec==='none') ? 'audio' : 'video'; entry.sending = true; entry.error = undefined; render();
  const selection = kind === 'video' && advanced && runtime?.capabilities.exact_formats && id
    ? { format_id: id } : { preset: kind === 'audio' ? 'audio' : element<HTMLSelectElement>('quality').value };
  try { const stopped = entry.downloadId && jobs.get(entry.downloadId)?.state === 'cancelled' ? entry.downloadId : undefined;
    const job = await afterCancellation(() => api.download(entry.probeId!, selection, stopped)); entry.downloadId = job.id;
    const previousCard = cards.get(`job:${entry.probeId}`);
    if (previousCard && !cards.has(`job:${job.id}`)) {
      cards.delete(`job:${entry.probeId}`);
      cards.set(`job:${job.id}`, previousCard);
    }
    queueEntries.set(job.id, entry);
    jobs.delete(entry.probeId); const linked=entries.get(entry.url); if (linked) linked.downloadId=job.id; autoDownload.watch(job.id); rememberJob(job); }
  catch (error) { entry.error = (error as Error).message; failure(error); }
  finally { entry.sending = false; render(); }
}
async function refreshJobs() { jobs = new Map((await api.jobs()).map(job => [job.id, job])); render(); }
async function cancel(id: string) {
  const metadata = jobs.get(id)?.kind === 'probe';
  const card = cards.get(`job:${id}`);
  let motion: Animation | undefined;
  try {
    await api.cancel(id);
    if (metadata) {
      if (card && !matchMedia('(prefers-reduced-motion: reduce)').matches) {
        const height = card.root.getBoundingClientRect().height;
        motion = card.root.animate([
          {opacity:1,transform:'translateY(0)',height:`${height}px`,overflow:'hidden'},
          {opacity:0,transform:'translateY(-8px)',height:`${height}px`,overflow:'hidden',offset:.45},
          {opacity:0,transform:'translateY(-8px)',height:'0px',marginBottom:'-16px',overflow:'hidden'}
        ], {duration:260,easing:'cubic-bezier(.2,.7,.2,1)',fill:'forwards'});
      }
      card?.root.classList.add('removing');
      await Promise.all([afterCancellation(() => api.delete(id)), motion?.finished.catch(()=>{})]);
      forgetJob(id); rows(); render();
    }
    await refreshJobs();
  } catch (error) {
    motion?.cancel(); card?.root.classList.remove('removing'); failure(error); await refreshJobs().catch(()=>{});
  }
}
async function retry(id: string) {
  try {
    const job = await api.retry(id);
    if (job.kind === 'download') autoDownload.watch(job.id);
    rememberJob(job);
    for (const entry of entries.values()) {
      if (entry.probeId === id) entry.probeId = job.id;
      if (entry.downloadId === id) entry.downloadId = job.id;
      entry.error = undefined;
    }
    render();
  } catch (error) { failure(error); }
}
function forgetJob(id: string) {
  const hiddenUrls = new Set<string>();
  const queuedUrl = queueEntries.get(id)?.url;
  if (queuedUrl) hiddenUrls.add(queuedUrl);
  dispatchedDownloads.delete(id); jobs.delete(id); queueEntries.delete(id); autoDownload.forget(id);
  for (const [url, entry] of entries) {
    if (entry.probeId === id) {
      entries.delete(url);
      hiddenUrls.add(url);
    } else if (entry.downloadId === id) {
      entry.downloadId = undefined;
      hiddenUrls.add(url);
    }
  }
  const keepLink = (value: string) => {
    try { return !hiddenUrls.has(normalizeLink(value)); }
    catch { return true; }
  };
  values = values.filter(keepLink);
  savedBatch = savedBatch.filter(keepLink);
  if (!values.length) values=[''];
}
async function deleteJob(id: string) {
  if (!runtime?.capabilities.queue_archive) { feedback('Ожидается обновление сервера для безопасной очистки списка.'); return; }
  if (deleting.has(id) || clearing || !await confirmDelete(jobs.get(id)?.kind==='download' && jobs.get(id)?.state==='failed' ? 'Удалить загрузку и все её временные файлы? Продолжить её будет невозможно.' : 'Убрать запись из списка задач? Готовый файл останется в библиотеке.')) return;
  deleting.add(id); render();
  try { await afterCancellation(() => api.delete(id)); forgetJob(id); rows(); await refreshJobs(); }
  catch(error) { failure(error); }
  finally { deleting.delete(id); render(); }
}
element('clear-jobs').addEventListener('click',async () => {
  if (!runtime?.capabilities.queue_archive) return;
  const ids=[...jobs.values()].filter(job => !active(job)).map(job => job.id);
  if (clearing || !ids.length || !await confirmDelete(`Убрать завершённые записи (${ids.length}) из списка? Готовые файлы останутся в библиотеке. Временные файлы загрузок с ошибкой будут удалены; активные задачи останутся в очереди.`)) return;
  clearing=true; render(); let removed=0;
  try {
    for (const id of ids) {
      try { await afterCancellation(() => api.delete(id)); forgetJob(id); removed++; }
      catch(error) { if (error instanceof ApiError && error.status === 409) continue; throw error; }
    }
    rows(); await refreshJobs(); feedback(`Удалено: ${removed}.`);
  } catch(error) { failure(error); }
  finally { clearing=false; rows(); render(); }
});
const queue = new QueueView(element('settings-queue'), {cancel:id=>cancel(id),retry:id=>void retry(id),delete:id=>void deleteJob(id)});
const libraryView = new LibraryView(element('library-list'), id=>void removeLibraryFile(id), ids=>void removeLibraryFiles(ids), id=>void convertLibraryAudio(id));
function showView(view: 'home' | 'library') {
  currentView=view;
  element('home-view').hidden=view!=='home';element('library-view').hidden=view!=='library';
  document.querySelector('.panel')!.classList.toggle('library-open',view==='library');
  for (const id of ['home','library']) {
    element(id).classList.toggle('active',id===view);
    if (id===view) element(id).setAttribute('aria-current','page'); else element(id).removeAttribute('aria-current');
  }
  if (view==='library') void refreshLibrary();
}
async function refreshLibrary() {
  if (libraryLoading || !authenticated) return;
  libraryLoading=true; element('library-list').setAttribute('aria-busy','true');
  try {
    libraryData=await api.library();
    libraryData.items=libraryData.items.filter(item=>!removedLibraryFiles.has(item.id));
    libraryData.total_bytes=libraryData.items.reduce((sum,item)=>sum+item.size,0);
    autoDownload.update(libraryData.items,deliverFile);render();saveWorkspace();
    libraryView.update(libraryData,libraryDeleting);
  } catch(error) { failure(error, libraryFeedback); }
  finally { libraryLoading=false;element('library-list').setAttribute('aria-busy','false');if(currentView==='library' && libraryData?.items.some(item=>active(item))) setTimeout(()=>{if(currentView==='library') void refreshLibrary();},1500); }
}
async function convertLibraryAudio(id:string) {
  try {await api.convertAudio(id);await refreshLibrary();}
  catch(error) {failure(error,libraryFeedback);}
}
async function removeLibraryFiles(ids:string[]) {
  ids=ids.filter(id=>!libraryDeleting.has(id));
  if(!ids.length || !await confirmDelete(`Удалить выделенные файлы (${ids.length}) из библиотеки и с сервера без возможности восстановления?`)) return;
  for(const id of ids) libraryDeleting.add(id);
  if(libraryData) libraryView.update(libraryData,libraryDeleting);
  let removed=0,failed=0;
  try {
    for(const id of ids) {
      try {await api.deleteLibraryFile(id);removedLibraryFiles.add(id);removed++;}
      catch(error) {failed++;failure(error,libraryFeedback);}
    }
    await refreshLibrary();await refreshJobs();
    libraryFeedback(`Удалено файлов: ${removed}.${failed ? ` Не удалось удалить: ${failed}.` : ''}`);
  } finally {for(const id of ids) libraryDeleting.delete(id);if(libraryData) libraryView.update(libraryData,libraryDeleting);}
}
async function removeLibraryFile(id:string) {
  if (libraryDeleting.has(id) || !await confirmDelete('Удалить файл из библиотеки и с сервера без возможности восстановления?')) return;
  libraryDeleting.add(id);if(libraryData) libraryView.update(libraryData,libraryDeleting);
  try { await api.deleteLibraryFile(id);removedLibraryFiles.add(id);await refreshLibrary();await refreshJobs();libraryFeedback('Файл удалён из библиотеки.'); }
  catch(error) { failure(error, libraryFeedback); }
  finally {libraryDeleting.delete(id);if(libraryData)libraryView.update(libraryData,libraryDeleting);}
}
element('library').addEventListener('click',()=>{settings.close();showView('library');});
async function status() {
  if (!authenticated) return;
  try {
    runtime = await api.status(); cookieStatusFresh = true; element('version').textContent = runtime.version;
    serverStatus(`Uptime: ${Math.floor(runtime.uptime_seconds / 86400)}д ${Math.floor(runtime.uptime_seconds / 3600) % 24}ч ${Math.floor(runtime.uptime_seconds / 60) % 60}м`, 'success');
    renderCookies(runtime.cookies);
    render();
    if(runtime.capabilities.library && (currentView==='library' || autoDownload.snapshot().length)) void refreshLibrary();
  } catch (error) {
    cookieStatusFresh = false; renderCookies(runtime?.cookies);
    serverStatus(error instanceof ApiError && error.status === 404 ? 'Нет данных uptime' : 'Сервер недоступен', error instanceof ApiError && error.status === 404 ? 'warning' : 'error');
    if (error instanceof ApiError && error.status === 401) needLogin();
  }
}
function subscribe() {
  events?.close(); events = new EventSource('/api/events');
  events.addEventListener('jobs', event => { try { jobs = new Map((JSON.parse((event as MessageEvent).data) as Job[]).map(job => [job.id, job])); render(); } catch { feedback('Не удалось прочитать обновление задач.'); } });
  events.addEventListener('session-expired', needLogin);
  events.onerror = () => { serverStatus('Переподключение…', 'error'); cookieStatusFresh = false; renderCookies(runtime?.cookies); };
  events.onopen = () => { void status(); };
}
async function connect() { await refreshJobs(); authenticated = true; sessionUI(); subscribe(); void status(); resolve(); }
element('auth-form').addEventListener('submit', async event => {
  event.preventDefault(); const button = element<HTMLButtonElement>('auth-submit'); button.disabled = true;
  try { await api.login(element<HTMLInputElement>('auth-token').value); element<HTMLInputElement>('auth-token').value = ''; await connect(); auth.close(); element('auth-error').hidden = true; }
  catch (error) { element('auth-error').textContent = (error as Error).message; element('auth-error').hidden = false; }
  finally { button.disabled = false; }
});
element('auth-close').addEventListener('click', () => auth.close());
async function sessionAction() {
  settings.close();
  if (!authenticated) { needLogin(); return; }
  try {
    await api.logout(); events?.close(); events = null; authenticated = false; runtime = null;
    clearTimeout(timer); savedBatch = [];
    autoDownload.clear(); dispatchedDownloads.clear(); queueEntries.clear(); libraryData=undefined;element('library-list').replaceChildren();showView('home');
    jobs.clear(); entries.clear(); for (const card of cards.values()) card.dispose(); cards.clear(); values = ['']; rows(); render(); sessionUI();
    serverStatus('Требуется вход', 'neutral'); element('cookie-lifetime').textContent = 'Нет данных'; feedback(); libraryFeedback(); needLogin();
  } catch (error) { failure(error); }
}
for (const id of ['logout', 'settings-session']) element(id).addEventListener('click', () => void sessionAction());
element('settings').addEventListener('click', () => { render(); settings.showModal(); });
element('home').addEventListener('click', () => { settings.close(); showView('home'); element('links-box').querySelector('input')?.focus(); });
element('download-form').addEventListener('submit', event => { event.preventDefault(); resolve(); });
element('links-box').addEventListener('click', event => {
  const target = event.target;
  if (!(target instanceof Element) || target.closest('button, input')) return;
  const box = element('links-box');
  const clickedRow = target.closest<HTMLElement>('.link-row');
  const nearestRow = clickedRow || [...box.querySelectorAll<HTMLElement>('.link-row')]
    .reduce<HTMLElement | undefined>((nearest, row) => {
      const distance = (item: HTMLElement) => {
        const bounds = item.getBoundingClientRect();
        return Math.abs(event.clientY - (bounds.top + bounds.height / 2));
      };
      return !nearest || distance(row) < distance(nearest) ? row : nearest;
    }, undefined);
  nearestRow?.querySelector('input')?.focus();
});
element('batch').addEventListener('click', () => {
  if (batch) { savedBatch = [...values]; values = [values[0]]; } else { values = batchRows([values[0], ...savedBatch.slice(1)]); }
  batch = !batch; element('batch').setAttribute('aria-pressed', String(batch));
  element('batch-label').textContent = batch ? 'Одна ссылка' : 'Много ссылок сразу';
  element('title').textContent = batch ? 'Вставь ссылки – получи файлы' : 'Вставь ссылку – получи файл';
  document.querySelector('.panel')!.classList.toggle('batch-results', batch); rows(); schedule();
});
element('advanced').addEventListener('click', () => { advanced = !advanced; element('advanced').setAttribute('aria-expanded', String(advanced)); element('advanced-options').hidden = !advanced; render(); });
function setPreferred(value: string) {
  preferred = value; for (const id of ['format', 'default-format']) element<HTMLSelectElement>(id).value = preferred;
  try { localStorage.setItem('vertovdl-format', preferred); } catch {} render();
}
for (const id of ['format', 'default-format']) { element<HTMLSelectElement>(id).value = preferred; element(id).addEventListener('change', event => setPreferred((event.target as HTMLSelectElement).value)); }
element('cookies-file').addEventListener('change', event => {
  const file = (event.target as HTMLInputElement).files?.[0]; if (file) void importCookieFile(file);
});
element('cookies-delete').addEventListener('click', async () => {
  if (cookieBusy || !confirm('Удалить импортированные cookies с сервера? Активная задача может продолжить использовать свою копию в памяти.')) return;
  cookieBusy = true; renderCookies(runtime?.cookies);
  try { const cookies = await api.deleteCookies(); if (runtime) runtime.cookies = cookies; cookieFeedback('Cookies удалены. Новые задачи выполняются без них.'); }
  catch (error) { cookieFeedback((error as Error).message, true); if (error instanceof ApiError && error.status === 401) needLogin(); }
  finally { cookieBusy = false; renderCookies(runtime?.cookies); }
});
bindCookieDrop(document, window, {
  hint: visible => { element('cookie-drop-hint').hidden = !visible; },
  busy: () => cookieBusy,
  importFile: file => void importCookieFile(file),
  error: message => cookieFeedback(message, true),
});
if (restored) {
  element<HTMLSelectElement>('quality').value=restored.quality;
  element('batch').setAttribute('aria-pressed',String(batch));
  element('batch-label').textContent=batch ? 'Одна ссылка' : 'Много ссылок сразу';
  element('title').textContent=batch ? 'Вставь ссылки – получи файлы' : 'Вставь ссылку – получи файл';
  document.querySelector('.panel')!.classList.toggle('batch-results',batch);
  element('advanced').setAttribute('aria-expanded',String(advanced)); element('advanced-options').hidden=!advanced;
}
element('quality').addEventListener('change',()=>{saveWorkspace();render();});
rows(); sessionUI(); render();
void connect().catch(error => { serverStatus('Нет подключения', 'error'); failure(error); });
setInterval(() => void status(), 30000);
