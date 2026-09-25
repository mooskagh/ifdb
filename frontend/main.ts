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

function initConfirmForms(): void {
  document.addEventListener('submit', event => {
    const form = event.target instanceof HTMLFormElement ? event.target : null;
    const message = form?.dataset.confirm;
    if (message && !window.confirm(message)) event.preventDefault();
  });
}

function getCookie(name: string): string {
  for (const cookie of document.cookie.split(';')) {
    const c = cookie.trim();
    if (c.startsWith(`${name}=`)) {
      return decodeURIComponent(c.substring(name.length + 1));
    }
  }
  return '';
}

function initDialogs(): void {
  document.querySelectorAll<HTMLElement>('[data-dialog]').forEach(trigger => {
    const dialogId = trigger.dataset.dialog;
    const dialog = dialogId ? document.getElementById(dialogId) : null;
    if (!(dialog instanceof HTMLDialogElement)) return;

    trigger.addEventListener('click', (e) => {
      e.preventDefault();
      dialog.showModal();
    });
    dialog.querySelectorAll<HTMLElement>('[data-dialog-cancel]').forEach(cancel => {
      cancel.addEventListener('click', () => dialog.close());
    });
  });
}

function initFeedbackDialog(): void {
  const form = document.getElementById('feedback-form') as HTMLFormElement | null;
  const dialog = document.getElementById('feedback-dialog') as HTMLDialogElement | null;
  if (!form || !dialog) return;

  const statusEl = document.getElementById('feedback-status');
  const submitBtn = document.getElementById('feedback-submit-btn') as HTMLButtonElement | null;
  const textarea = document.getElementById('feedback-text') as HTMLTextAreaElement | null;

  form.addEventListener('submit', async (e) => {
    e.preventDefault();
    const text = textarea?.value.trim() || '';
    if (!text) return;

    if (submitBtn) {
      submitBtn.disabled = true;
      submitBtn.textContent = 'Отправка...';
    }
    if (statusEl) {
      statusEl.style.display = 'none';
      statusEl.className = 'feedback-status';
    }

    try {
      const csrfToken = getCookie('csrftoken') || (form.querySelector('input[name="csrfmiddlewaretoken"]') as HTMLInputElement)?.value || '';
      const gameNameInput = form.querySelector('input[name="game_name"]') as HTMLInputElement | null;
      const gameUrlInput = form.querySelector('input[name="game_url"]') as HTMLInputElement | null;

      const payload: Record<string, string> = {
        text,
        url: window.location.href,
      };
      if (gameNameInput?.value) payload.game_name = gameNameInput.value;
      if (gameUrlInput?.value) payload.game_url = gameUrlInput.value;

      const res = await fetch(form.action || '/feedback/', {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          'X-CSRFToken': csrfToken,
        },
        body: JSON.stringify(payload),
      });

      if (res.ok) {
        if (statusEl) {
          statusEl.textContent = 'Спасибо! Ваше сообщение отправлено.';
          statusEl.className = 'feedback-status success';
          statusEl.style.display = 'block';
        }
        form.reset();
        setTimeout(() => {
          dialog.close();
          if (statusEl) statusEl.style.display = 'none';
          if (submitBtn) {
            submitBtn.disabled = false;
            submitBtn.textContent = 'Отправить';
          }
        }, 1800);
      } else {
        const errData = await res.json().catch(() => null);
        const errMsg = errData?.error || 'Не удалось отправить сообщение. Пожалуйста, попробуйте позже.';
        if (statusEl) {
          statusEl.textContent = errMsg;
          statusEl.className = 'feedback-status error';
          statusEl.style.display = 'block';
        }
        if (submitBtn) {
          submitBtn.disabled = false;
          submitBtn.textContent = 'Отправить';
        }
      }
    } catch {
      if (statusEl) {
        statusEl.textContent = 'Ошибка сети. Пожалуйста, попробуйте позже.';
        statusEl.className = 'feedback-status error';
        statusEl.style.display = 'block';
      }
      if (submitBtn) {
        submitBtn.disabled = false;
        submitBtn.textContent = 'Отправить';
      }
    }
  });
}

document.addEventListener('DOMContentLoaded', () => {
  initClickableRows();
  initConfirmForms();
  initDialogs();
  initFeedbackDialog();
});
