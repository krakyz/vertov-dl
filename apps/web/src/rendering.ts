/** Keep unchanged children attached, preserving focus and CSS animation state. */
export function reconcileChildren(parent: HTMLElement, desired: HTMLElement[]) {
  const keep = new Set(desired);
  for (const child of [...parent.children]) if (!keep.has(child as HTMLElement)) child.remove();
  desired.forEach((child, index) => {
    const current = parent.children[index];
    if (current !== child) parent.insertBefore(child, current || null);
  });
}

export function frameScheduler(draw: () => void, request: (callback: () => void) => unknown = requestAnimationFrame) {
  let pending = false;
  return () => {
    if (pending) return;
    pending = true;
    request(() => { pending = false; draw(); });
  };
}
