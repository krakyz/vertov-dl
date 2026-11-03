import { node } from './dom';
import { bytes, duration, codec, active, mediaName } from './model';
import type { LibrarySnapshot } from './model';
import { showThumbnail } from './thumbnail-preview';

export class LibraryView {
  private rows = new Map<string, {root: HTMLElement; remove: HTMLButtonElement; checkbox: HTMLInputElement; lifetime: HTMLElement; typeBadge: HTMLElement; typeIcon: HTMLImageElement; durationBadge: HTMLElement; file: HTMLAnchorElement; convert: HTMLButtonElement; state: HTMLElement; image: HTMLImageElement}>();
  private selected = new Set<string>();
  private selecting = false;
  private selectAll = document.querySelector<HTMLInputElement>('#library-select-all')!;
  private typeFilter = document.querySelector<HTMLDetailsElement>('#library-filter-type')!;
  private dateFilter = document.querySelector<HTMLDetailsElement>('#library-filter-date')!;
  private snapshot?: LibrarySnapshot;
  private deleting = new Set<string>();
  constructor(private root: HTMLElement, private remove: (id: string) => void, private removeMany: (ids: string[]) => void, private convertAudio: (id: string) => void) {
    document.querySelector('#library-download-selected')!.addEventListener('click',()=>{
      for(const id of this.selected) {const link=node('a');link.href=`/api/jobs/${encodeURIComponent(id)}/file`;link.download='';document.body.append(link);link.click();link.remove();}
    });
    document.querySelector('#library-delete-selected')!.addEventListener('click',()=>this.removeMany([...this.selected]));
    const filters=[this.typeFilter,this.dateFilter];
    for(const filter of filters) {
      const caption=filter.querySelector('summary span')!;
      const title=caption.textContent!;
      filter.addEventListener('change',()=>{
        const chosen=filter.querySelector<HTMLInputElement>('input:checked')!;
        caption.textContent=chosen.value==='all' ? title : chosen.nextElementSibling!.textContent;
        filter.classList.toggle('filtered',chosen.value!=='all');
        filter.open=false;
        filter.querySelector('summary')!.focus();
        if(this.snapshot) this.update(this.snapshot,this.deleting);
      });
      filter.addEventListener('toggle',()=>{if(filter.open) for(const other of filters) if(other!==filter) other.open=false;});
      filter.addEventListener('keydown',event=>{if(event.key==='Escape'){filter.open=false;filter.querySelector('summary')!.focus();}});
    }
    document.addEventListener('click',event=>{for(const filter of filters) if(!filter.contains(event.target as Node)) filter.open=false;});
    this.selectAll.addEventListener('change',()=>{
      this.selecting=this.selectAll.checked;
      this.selected=new Set(this.selecting ? [...this.rows.keys()].filter(id=>this.snapshot?.items.find(item=>item.id===id)?.state==='completed') : []);
      this.renderSelection();
    });
  }
  private renderSelection() {
    const count=this.selected.size,total=[...this.rows.keys()].filter(id=>this.snapshot?.items.find(item=>item.id===id)?.state==='completed').length;
    if (!count) this.selecting=false;
    const summary=document.querySelector<HTMLElement>('#library-selected-summary')!;
    const size=this.snapshot?.items.filter(item=>this.selected.has(item.id)).reduce((sum,item)=>sum+item.size,0) || 0;
    summary.textContent=`Выбрано ${count} · ${bytes(size)}`;summary.hidden=!this.selecting;
    document.querySelector<HTMLElement>('#library-selection-count')!.hidden=this.selecting;
    document.querySelector<HTMLElement>('#library-selection-actions')!.hidden=!this.selecting;
    for(const id of ['library-download-selected','library-delete-selected']) document.querySelector<HTMLButtonElement>(`#${id}`)!.disabled=!count || [...this.selected].some(id=>this.deleting.has(id));
    if(this.selecting) {this.typeFilter.open=false;this.dateFilter.open=false;}
    this.selectAll.checked=total>0 && count===total;
    this.selectAll.indeterminate=count>0 && count<total;
    this.selectAll.disabled=total===0;
    this.selectAll.setAttribute('aria-label',`Выделить все файлы. Выбрано: ${count} из ${total}`);
    this.root.classList.toggle('selecting',this.selecting);
    for(const [id,row] of this.rows) {
      row.checkbox.hidden=!this.selecting;
      row.checkbox.disabled=this.snapshot?.items.find(item=>item.id===id)?.state!=='completed';
      row.checkbox.checked=this.selected.has(id);
      row.root.classList.toggle('selected',row.checkbox.checked);
    }
  }
  update(data: LibrarySnapshot, deleting: Set<string>) {
    this.snapshot=data;this.deleting=deleting;
    const type=this.typeFilter.querySelector<HTMLInputElement>('input:checked')!.value;
    const date=this.dateFilter.querySelector<HTMLInputElement>('input:checked')!.value;
    const now=new Date();
    const since=date==='today' ? new Date(now.getFullYear(),now.getMonth(),now.getDate()).getTime()/1000
      : date==='all' ? 0 : now.getTime()/1000-Number(date)*86400;
    data={...data,items:data.items.filter(item=>(type==='all' || (mediaName(item)==='Аудио' ? 'audio' : 'video')===type) && item.completed_at>=since)};
    const ids=new Set(data.items.map(item=>item.id));
    for (const [id,row] of this.rows) if (!ids.has(id)) { row.root.remove(); this.rows.delete(id); }
    for (const id of this.selected) if (!ids.has(id)) this.selected.delete(id);
    if (!data.items.length) { this.selecting=false;this.renderSelection(); this.root.replaceChildren(node('p',this.snapshot.items.length ? 'Нет файлов по выбранным фильтрам.' : 'В библиотеке пока нет готовых файлов.','muted')); return; }
    for (const item of data.items) {
      let row=this.rows.get(item.id);
      if (!row) {
        const root=node('article',undefined,'library-card');
        const thumbnail=node('div',undefined,'library-thumbnail');
        const fallback=node('span','↓','library-thumbnail-fallback');thumbnail.append(fallback);
        const overlay=node('div',undefined,'library-thumbnail-overlay');
        const icon = (name:string) => { const image=node('img');image.src=`assets/library-${name}.svg`;image.alt='';return image; };
        const file=node('a',undefined,'library-overlay-action');file.href=`/api/jobs/${encodeURIComponent(item.id)}/file`;file.download='';
        file.setAttribute('aria-label',`Скачать: ${item.title}`);file.title='Скачать';file.append(icon('download'));
        const zoom=node('button',undefined,'library-overlay-action');zoom.type='button';zoom.disabled=true;
        zoom.setAttribute('aria-label',`Увеличить превью: ${item.title}`);zoom.title='Увеличить превью';zoom.append(icon('zoom'));
        const remove=node('button',undefined,'library-overlay-action library-overlay-remove');remove.type='button';
        remove.setAttribute('aria-label',`Удалить файл: ${item.title}`);remove.title='Удалить файл';remove.append(icon('trash'));
        remove.addEventListener('click',()=>this.remove(item.id));
        const convert=node('button',undefined,'library-overlay-action');convert.type='button';convert.title='Конвертировать в MP3';convert.setAttribute('aria-label','Конвертировать в MP3');convert.append(icon('convert'));
        convert.addEventListener('click',()=>this.convertAudio(item.id));
        const cornerActions=node('div',undefined,'library-corner-actions');cornerActions.append(remove);
        overlay.append(zoom,convert,file,cornerActions);
        const image=node('img',undefined,'library-preview-image');image.alt=item.title;image.hidden=true;
        image.addEventListener('load',()=>{zoom.disabled=false;fallback.hidden=true;image.hidden=false;});
        image.addEventListener('error',()=>{image.hidden=true;fallback.hidden=false;zoom.disabled=true;});
        thumbnail.append(image);zoom.addEventListener('click',()=>showThumbnail(image));
        thumbnail.append(overlay);
        const lifetime=node('span',undefined,'library-duration library-lifetime');overlay.append(lifetime);
        const checkbox=node('input',undefined,'library-checkbox library-card-select');checkbox.type='checkbox';checkbox.hidden=true;
        checkbox.setAttribute('aria-label',`Выделить: ${item.title}`);
        checkbox.addEventListener('change',()=>{if(checkbox.checked) this.selected.add(item.id);else this.selected.delete(item.id);this.renderSelection();});
        root.addEventListener('click',event=>{
          if (!this.selecting || event.target===checkbox) return;
          if(checkbox.disabled) {event.preventDefault();event.stopPropagation();return;}
          event.preventDefault();event.stopPropagation();
          if(this.selected.has(item.id)) this.selected.delete(item.id);else this.selected.add(item.id);
          this.renderSelection();
        },true);
        const badges=node('div',undefined,'library-card-badges');
        badges.append(checkbox);
        thumbnail.append(badges);
        const durationBadge=node('span',undefined,'library-duration');thumbnail.append(durationBadge);
        const typeBadge=node('span',undefined,'library-media-type');
        const typeIcon=node('img',undefined,'library-media-type-icon');typeIcon.alt='';
        typeBadge.append(typeIcon);badges.append(typeBadge);
        const body=node('div',undefined,'library-card-body');
        const heading=node('div',undefined,'library-card-heading');
        const title=node('h2',item.title);title.title=item.title;heading.append(title);
        body.append(heading);
        if (item.details?.uploader) body.append(node('p',item.details.uploader,'library-uploader'));
        const state=node('p',undefined,'library-conversion-status');thumbnail.append(state);
        root.append(thumbnail,body);
        row={root,remove,checkbox,lifetime,typeBadge,typeIcon,durationBadge,file,convert,state,image};this.rows.set(item.id,row);
      }
      if(item.details?.has_thumbnail && !row.image.getAttribute('src')) row.image.src=`/api/jobs/${encodeURIComponent(item.id)}/thumbnail`;
      const pending=active(item), failed=item.state==='failed';
      row.root.classList.toggle('converting',pending);
      row.state.hidden=!pending && !failed;row.state.textContent=failed ? item.message : 'Конвертация в MP3…';
      row.file.hidden=item.state!=='completed';row.convert.hidden=item.state!=='completed' || mediaName(item)==='Аудио';
      row.remove.disabled=pending || deleting.has(item.id);
      row.lifetime.hidden=item.state!=='completed';
      row.durationBadge.textContent=duration(item.details?.duration);
      row.durationBadge.hidden=item.details?.duration==null;
      const media=item.details?.artifact_media;
      const audio=mediaName(item)==='Аудио';
      const mediaCodec=media ? codec(audio ? media.audio_codec : media.video_codec) : null;
      const resolution=!audio && media?.width && media?.height ? `${media.width}×${media.height}` : null;
      const fps=!audio && media?.fps ? `${media.fps} fps` : null;
      row.typeBadge.replaceChildren(row.typeIcon,document.createTextNode([audio?'Аудио':'Видео',mediaCodec && mediaCodec!=='—' ? mediaCodec : null,resolution,fps].filter(Boolean).join(' · ')));
      const iconPath=`assets/media-type-${audio?'audio':'video'}.svg`;
      if(row.typeIcon.getAttribute('src')!==iconPath) row.typeIcon.src=iconPath;
      const minutes=Math.max(0,Math.floor((item.expires_at-Date.now()/1000)/60));
      row.lifetime.textContent=minutes ? `${Math.floor(minutes/1440)}д ${Math.floor(minutes/60)%24}ч ${minutes%60}м` : 'Менее минуты';
      row.lifetime.setAttribute('aria-label',`Срок хранения: ${row.lifetime.textContent}`);
      row.remove.disabled=pending || deleting.has(item.id);
    }
    for (let i=0;i<data.items.length;i++) {
      const root=this.rows.get(data.items[i].id)!.root;
      if (this.root.children[i]!==root) this.root.insertBefore(root,this.root.children[i] || null);
    }
    for (const child of [...this.root.children]) if (!child.classList.contains('library-card')) child.remove();
    this.renderSelection();
  }
}
