export function bindCookieDrop(target: EventTarget, windowTarget: EventTarget, actions: {
  hint: (visible: boolean) => void; busy: () => boolean;
  importFile: (file: File) => void; error: (message: string) => void;
}) {
  let depth = 0;
  const isFile = (event: DragEvent) => Array.from(event.dataTransfer?.types || []).includes('Files');
  const isTxt = (event: DragEvent) => {
    const files = Array.from(event.dataTransfer?.files || []);
    if (files.length) return files.length === 1 && /\.txt$/i.test(files[0].name);
    // During drag browsers hide filenames; only the advertised MIME type is available.
    const items = Array.from(event.dataTransfer?.items || []).filter(item => item.kind === 'file');
    return items.length === 1 && items[0].type.toLowerCase() === 'text/plain';
  };
  target.addEventListener('dragenter', raw => {
    const event = raw as DragEvent;
    if (isFile(event)) { event.preventDefault(); depth++; actions.hint(isTxt(event) && !actions.busy()); }
  });
  target.addEventListener('dragover', raw => {
    const event = raw as DragEvent;
    if (isFile(event)) { event.preventDefault(); if (event.dataTransfer) event.dataTransfer.dropEffect = !isTxt(event) || actions.busy() ? 'none' : 'copy'; }
  });
  target.addEventListener('dragleave', raw => {
    if (isFile(raw as DragEvent) && --depth <= 0) { depth = 0; actions.hint(false); }
  });
  target.addEventListener('drop', raw => {
    const event = raw as DragEvent;
    if (!isFile(event)) return;
    event.preventDefault(); depth = 0; actions.hint(false);
    if (actions.busy()) return;
    const files = event.dataTransfer?.files;
    if (files?.length !== 1) { actions.error('Перетащи один cookies.txt.'); return; }
    if (!/\.txt$/i.test(files[0].name)) return;
    actions.importFile(files[0]);
  });
  windowTarget.addEventListener('blur', () => { depth = 0; actions.hint(false); });
}
