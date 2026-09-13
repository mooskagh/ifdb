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

function updateRowState(row: HTMLElement): void {
  const leftCell = row.querySelector('.diff-cell--left');
  const rightCell = row.querySelector('.diff-cell--right');
  const cbLeft = row.querySelector<HTMLInputElement>('.diff-check--left');
  const cbRight = row.querySelector<HTMLInputElement>('.diff-check--right');
  const cbEqual = row.querySelector<HTMLInputElement>('.diff-check--equal');

  if (cbEqual) {
    if (cbEqual.checked) {
      leftCell?.classList.remove('diff-cell--excluded');
      rightCell?.classList.remove('diff-cell--excluded');
      row.classList.remove('diff-row--excluded');
      row.classList.add('diff-row--included');
    } else {
      leftCell?.classList.add('diff-cell--excluded');
      rightCell?.classList.add('diff-cell--excluded');
      row.classList.remove('diff-row--included');
      row.classList.add('diff-row--excluded');
    }
    return;
  }

  if (cbLeft) {
    if (cbLeft.checked) {
      leftCell?.classList.remove('diff-cell--excluded');
    } else {
      leftCell?.classList.add('diff-cell--excluded');
    }
  } else {
    leftCell?.classList.add('diff-cell--excluded');
  }

  if (cbRight) {
    if (cbRight.checked) {
      rightCell?.classList.remove('diff-cell--excluded');
    } else {
      rightCell?.classList.add('diff-cell--excluded');
    }
  } else {
    rightCell?.classList.add('diff-cell--excluded');
  }

  const anyChecked = (cbLeft?.checked ?? false) || (cbRight?.checked ?? false);
  if (anyChecked) {
    row.classList.remove('diff-row--excluded');
    row.classList.add('diff-row--included');
  } else {
    row.classList.remove('diff-row--included');
    row.classList.add('diff-row--excluded');
  }
}

function initDiffCheckboxes(): void {
  const interactiveRows = document.querySelectorAll<HTMLElement>('.diff--interactive .diff-row');
  if (!interactiveRows.length) return;

  interactiveRows.forEach(row => {
    const cbLeft = row.querySelector<HTMLInputElement>('.diff-check--left');
    const cbRight = row.querySelector<HTMLInputElement>('.diff-check--right');
    const cbEqual = row.querySelector<HTMLInputElement>('.diff-check--equal');

    if (cbLeft && cbRight) {
      // Replace row: mutually exclusive like a radio button that can be off
      cbLeft.addEventListener('change', () => {
        if (cbLeft.checked) {
          cbRight.checked = false;
        }
        updateRowState(row);
      });
      cbRight.addEventListener('change', () => {
        if (cbRight.checked) {
          cbLeft.checked = false;
        }
        updateRowState(row);
      });
    } else if (cbLeft) {
      cbLeft.addEventListener('change', () => updateRowState(row));
    } else if (cbRight) {
      cbRight.addEventListener('change', () => updateRowState(row));
    } else if (cbEqual) {
      cbEqual.addEventListener('change', () => updateRowState(row));
    }

    const allCbs = row.querySelectorAll<HTMLInputElement>('.diff-cell--action input[type="checkbox"]');
    if (allCbs.length === 1) {
      const singleCb = allCbs[0];
      const cell = row.querySelector<HTMLElement>('.diff-cell--action');
      cell?.addEventListener('click', (e) => {
        if (e.target !== singleCb) {
          singleCb.checked = !singleCb.checked;
          singleCb.dispatchEvent(new Event('change'));
        }
      });
    }

    updateRowState(row);
  });
}

document.addEventListener('DOMContentLoaded', () => {
  initEditActionDialogs();
  initDiffCheckboxes();
});
