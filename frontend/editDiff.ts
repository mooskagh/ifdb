function initEditActionDialogs(): void {
  document.querySelectorAll<HTMLButtonElement>('[data-edit-action-dialog]').forEach(button => {
    const dialogId = button.dataset.editActionDialog;
    const dialog = dialogId ? document.getElementById(dialogId) : null;
    if (!(dialog instanceof HTMLDialogElement)) return;

    button.addEventListener('click', () => dialog.showModal());
    dialog.querySelectorAll<HTMLButtonElement>('[data-edit-action-cancel]').forEach(cancel => {
      cancel.addEventListener('click', () => dialog.close());
    });
  });
}

function initDiffCheckboxes(): void {
  const checkboxes = document.querySelectorAll<HTMLInputElement>('input[name="diff_row"]');
  if (!checkboxes.length) return;

  function updateRow(cb: HTMLInputElement): void {
    const row = cb.closest('.diff-row');
    if (!row) return;
    if (cb.checked) {
      row.classList.remove('diff-row--excluded');
      row.classList.add('diff-row--included');
    } else {
      row.classList.remove('diff-row--included');
      row.classList.add('diff-row--excluded');
    }
  }

  checkboxes.forEach(cb => {
    updateRow(cb);
    cb.addEventListener('change', () => updateRow(cb));
    const cell = cb.closest('.diff-cell--action');
    if (cell) {
      cell.addEventListener('click', (e) => {
        if (e.target !== cb) {
          cb.checked = !cb.checked;
          updateRow(cb);
        }
      });
    }
  });
}

document.addEventListener('DOMContentLoaded', () => {
  initEditActionDialogs();
  initDiffCheckboxes();
});
