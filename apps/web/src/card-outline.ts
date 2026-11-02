let outlineSequence = 0;
const ns = 'http://www.w3.org/2000/svg';
const redraw = new WeakMap<Element, () => void>();
const observer = new ResizeObserver(entries => {
  const callbacks = new Set(entries.map(entry => redraw.get(entry.target)));
  callbacks.forEach(draw => draw?.());
});

/** One outline for the information block and its expanding action drawer. */
export function attachCardOutline(root: HTMLElement) {
  const info = root.querySelector<HTMLElement>('.media-info')!;
  const actions = root.querySelector<HTMLElement>('.download-actions')!;
  const svg = document.createElementNS(ns, 'svg');
  svg.classList.add('media-card-outline');
  svg.setAttribute('aria-hidden', 'true');
  const contour = document.createElementNS(ns, 'path');
  contour.classList.add('media-card-contour');
  const hover = document.createElementNS(ns, 'path');
  hover.classList.add('media-card-audio-fill');
  const divider = document.createElementNS(ns, 'path');
  divider.classList.add('media-card-divider');
  const clip = document.createElementNS(ns, 'clipPath');
  clip.id = `media-card-clip-${++outlineSequence}`;
  const clipPath = document.createElementNS(ns, 'path');
  clip.append(clipPath);
  const defs = document.createElementNS(ns, 'defs');
  defs.append(clip);
  hover.setAttribute('clip-path', `url(#${clip.id})`);
  const stroke = document.createElementNS(ns, 'path');
  stroke.classList.add('media-card-stroke');
  svg.append(defs, contour, hover, stroke, divider);
  root.prepend(svg);
  const draw = () => {
    const w = root.clientWidth;
    const h = info.offsetHeight;
    const a = actions.getBoundingClientRect().height;
    if (!w || !h) return;
    const buttonWidth = `${Math.min(180, w / 2)}px`;
    if(root.style.getPropertyValue('--action-button-width')!==buttonWidth) root.style.setProperty('--action-button-width',buttonWidth);
    const drawerWidth = actions.getBoundingClientRect().width;
    const x = w - drawerWidth;
    const cornerScale = Math.min(1, a / 28);
    const r = Math.min(12 * cornerScale, x);
    const bottom = h + a;
    const br = 16 * cornerScale;
    const d = a <= 0
      ? `M16 .5 H${w-16} Q${w-.5} .5 ${w-.5} 16 V${h-16} Q${w-.5} ${h-.5} ${w-16} ${h-.5} H16 Q.5 ${h-.5} .5 ${h-16} V16 Q.5 .5 16 .5 Z`
      : `M16 .5 H${w-16} Q${w-.5} .5 ${w-.5} 16 V${bottom-16} Q${w-.5} ${bottom-.5} ${w-16} ${bottom-.5} H${x+br} Q${x+.5} ${bottom-.5} ${x+.5} ${bottom-br} V${h+r} Q${x+.5} ${h-.5} ${x-r} ${h-.5} H16 Q.5 ${h-.5} .5 ${h-16} V16 Q.5 .5 16 .5 Z`;
    svg.setAttribute('width', String(w));
    svg.setAttribute('height', String(bottom));
    contour.setAttribute('d', d);
    clipPath.setAttribute('d', d);
    stroke.setAttribute('d', d);
    divider.setAttribute('d', `M${x-r} ${h-.5} H${w-.5}`);
    divider.style.opacity = String(Math.min(1, a / 12));
    const mid = root.dataset.singleAction || root.classList.contains('metadata-pending') ? w - 1 : x + drawerWidth / 2;
    hover.setAttribute('d', `M${x-r} ${h} H${mid} V${bottom-1} H${x+br} Q${x+1} ${bottom-1} ${x+1} ${bottom-br} V${h+r} Q${x+1} ${h} ${x-r} ${h} Z`);
  };
  const targets = [root, info, actions];
  for (const target of targets) {
    redraw.set(target, draw);
    observer.observe(target);
  }
  return () => { for (const target of targets) { observer.unobserve(target); redraw.delete(target); } };
}
