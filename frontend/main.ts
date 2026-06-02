function isInteractiveClick(target: EventTarget | null): boolean {
  if (!(target instanceof Element)) return false;

  return Boolean(
    target.closest('a, button, input, select, textarea, label, [role="button"]'),
  );
}

function initClickableRows(): void {
  document.addEventListener('click', event => {
    if (event.defaultPrevented || isInteractiveClick(event.target)) return;

    const row = event.target instanceof Element
      ? event.target.closest<HTMLElement>('tr[data-href]')
      : null;
    const href = row?.dataset.href;
    if (href) window.location.href = href;
  });
}

document.addEventListener('DOMContentLoaded', initClickableRows);
