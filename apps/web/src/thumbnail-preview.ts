import { node } from './dom';

let dialog: HTMLDialogElement | undefined;
let picture: HTMLImageElement;
let title: HTMLHeadingElement;

export function showThumbnail(source: HTMLImageElement) {
  if (source.hidden || !source.complete || !source.naturalWidth) return;
  if (!dialog) {
    dialog = node('dialog', undefined, 'thumbnail-dialog');
    dialog.setAttribute('aria-labelledby', 'thumbnail-preview-title');
    const header = node('div', undefined, 'thumbnail-dialog-header');
    title = node('h2'); title.id = 'thumbnail-preview-title';
    const close = node('button', 'Закрыть', 'inline-action'); close.type = 'button';
    close.addEventListener('click', () => dialog!.close());
    picture = node('img');
    header.append(title, close); dialog.append(header, picture);
    dialog.addEventListener('click', event => {
      if (event.target !== dialog) return;
      const bounds = dialog!.getBoundingClientRect();
      if (event.clientX < bounds.left || event.clientX > bounds.right || event.clientY < bounds.top || event.clientY > bounds.bottom) dialog!.close();
    });
    dialog.addEventListener('close', () => picture.removeAttribute('src'));
    document.body.append(dialog);
  }
  title.textContent = source.alt || 'Превью'; picture.alt = source.alt || 'Превью';
  picture.src = source.currentSrc || source.src;
  if (!dialog.open) dialog.showModal();
}
