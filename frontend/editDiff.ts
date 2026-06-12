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

document.addEventListener('DOMContentLoaded', initEditActionDialogs);
