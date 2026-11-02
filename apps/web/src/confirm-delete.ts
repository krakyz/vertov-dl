import { node } from './dom';

let dialog: HTMLDialogElement | undefined;
let message: HTMLParagraphElement;
let pending: ((value: boolean) => void) | undefined;

export function confirmDelete(text: string): Promise<boolean> {
  if (pending) return Promise.resolve(false);
  if (!dialog) {
    dialog = node('dialog', undefined, 'delete-dialog');
    dialog.setAttribute('aria-labelledby', 'delete-dialog-title');
    const title = node('h2', 'Подтвердить удаление'); title.id = 'delete-dialog-title';
    message = node('p', undefined, 'muted');
    const actions = node('div', undefined, 'delete-dialog-actions');
    const cancel = node('button', 'Отмена', 'inline-action'); cancel.type = 'button';
    cancel.autofocus = true; cancel.addEventListener('click', () => dialog!.close('cancel'));
    const remove = node('button', 'Удалить', 'inline-action destructive'); remove.type = 'button';
    remove.addEventListener('click', () => dialog!.close('delete'));
    actions.append(cancel, remove); dialog.append(title, message, actions);
    dialog.addEventListener('close', () => {
      const resolve = pending; pending = undefined; resolve?.(dialog!.returnValue === 'delete');
    });
    document.body.append(dialog);
  }
  message.textContent = text; dialog.returnValue = '';
  const result = new Promise<boolean>(resolve => { pending = resolve; });
  dialog.showModal(); return result;
}
