export class CancelButton {
  private jobId?: string;
  private armed = false;
  private pending = false;
  private enabled = true;
  private timer?: ReturnType<typeof setTimeout>;
  private button: HTMLButtonElement;
  private cancel: (id: string) => void | Promise<void>;
  constructor(button: HTMLButtonElement, cancel: (id: string) => void | Promise<void>) {
    this.button = button; this.cancel = cancel;
    button.addEventListener('click', event => {
      if (!this.jobId) return;
      event?.stopImmediatePropagation?.();
      if (!this.enabled || this.pending) return;
      if (!this.armed) {
        this.armed = true;
        this.timer = setTimeout(() => { this.armed = false; this.paint(); }, 10000);
        this.paint(); return;
      }
      clearTimeout(this.timer);
      this.pending = true; this.paint();
      const id = this.jobId;
      void Promise.resolve().then(() => this.cancel(id)).catch(() => {}).finally(() => {
        if (this.jobId !== id) return;
        this.pending = false; this.armed = false; this.paint();
      });
    });
  }
  update(id: string | undefined, enabled = true) {
    if (this.jobId !== id) {
      clearTimeout(this.timer); this.armed = false; this.pending = false;
    }
    this.jobId = id; this.enabled = enabled;
    this.button.classList.toggle('cancel-action', Boolean(id));
    if (id) this.paint();
    else { this.button.title = ''; delete this.button.dataset.confirming; }
  }
  private paint() {
    if (!this.jobId) return;
    this.button.textContent = this.pending ? 'Отмена…' : this.armed ? 'Подтвердить отмену' : 'Отменить';
    this.button.disabled = this.pending || !this.enabled;
    this.button.dataset.confirming = String(this.armed);
    this.button.title = this.armed ? 'Нажми ещё раз в течение 10 секунд, чтобы отменить задачу.' : 'Для отмены потребуется подтверждение.';
  }
}
