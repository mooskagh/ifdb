// Vanilla replacement for the old jQuery-UI `suggest` widget: an input with a
// filtering dropdown, backed by a label -> id map.

import {el} from './util';

export interface ComboboxOptions {
  optToId?: Record<string, number>;
  minLength?: number; // 0 = show everything on focus
  id?: number; // initially selected id
  showAll?: boolean; // render the ▼ dropdown button
  allowNew?: boolean; // false => readonly, value must come from the list
  placeholder?: string;
  onChange?: (id: number | undefined) => void; // resolved id, or undefined
  onBlur?: () => void;
}

export class Combobox {
  private input: HTMLInputElement;
  private popup: HTMLUListElement;
  private optToId: Record<string, number>;
  private items: string[] = [];
  private active = -1; // highlighted item in `items`
  private minLength: number;
  private allowNew: boolean;
  onChange?: (id: number | undefined) => void;
  onBlur?: () => void;

  constructor(
    readonly el: HTMLElement,
    opts: ComboboxOptions,
  ) {
    this.optToId = opts.optToId ?? {};
    this.minLength = opts.minLength ?? 2;
    this.allowNew = opts.allowNew ?? true;
    this.onChange = opts.onChange;
    this.onBlur = opts.onBlur;

    el.style.position = 'relative';
    this.input = document.createElement('input');
    this.input.className = opts.showAll ? 'suggestinput-icon' : 'suggestinput';
    if (opts.placeholder) this.input.placeholder = opts.placeholder;
    if (!this.allowNew) this.input.readOnly = true;
    el.append(this.input);

    if (opts.showAll) {
      const button = el2('span', 'ico', '▼');
      el.append(button);
      button.addEventListener('mousedown', e => {
        e.preventDefault();
        if (this.isOpen()) this.close();
        else this.open('', true);
      });
    }

    this.popup = document.createElement('ul');
    this.popup.className = 'combobox-popup';
    this.popup.style.display = 'none';
    el.append(this.popup);

    if (opts.id !== undefined) this.setValueById(opts.id);

    this.input.addEventListener('input', () => {
      this.input.classList.remove('invalidinput');
      this.emit();
      this.open(this.input.value);
    });
    this.input.addEventListener('mousedown', () => {
      if (this.input.readOnly) {
        if (this.isOpen()) this.close();
        else this.open('', true);
      }
    });
    this.input.addEventListener('focus', () => {
      if (this.minLength === 0) this.open(this.input.value);
    });
    this.input.addEventListener('keydown', e => this.onKeyDown(e));
    this.input.addEventListener('blur', () => {
      // Defer so a click on a popup item registers first.
      setTimeout(() => {
        this.close();
        this.onBlur?.();
      }, 150);
    });
  }

  private emit(): void {
    this.onChange?.(this.optToId[this.input.value]);
  }

  private isOpen(): boolean {
    return this.popup.style.display !== 'none';
  }

  private open(query: string, force = false): void {
    if (!force && query.length < this.minLength) return this.close();
    const q = query.toLowerCase();
    this.items = Object.keys(this.optToId).filter(k =>
      k.toLowerCase().includes(q),
    );
    if (!this.items.length) return this.close();
    this.active = -1;
    this.popup.replaceChildren(
      ...this.items.map((label, i) => {
        const li = el2('li', 'combobox-item', label);
        li.addEventListener('mousedown', e => {
          e.preventDefault();
          this.pick(i);
        });
        li.addEventListener('mouseenter', () => this.highlight(i));
        return li;
      }),
    );
    this.popup.style.display = '';
  }

  private close(): void {
    this.popup.style.display = 'none';
  }

  private highlight(i: number): void {
    const lis = this.popup.children;
    if (this.active >= 0) lis[this.active]?.classList.remove('selected');
    this.active = i;
    if (i >= 0) {
      lis[i]?.classList.add('selected');
      lis[i]?.scrollIntoView({block: 'nearest'});
    }
  }

  private pick(i: number): void {
    this.input.value = this.items[i];
    this.input.classList.remove('invalidinput');
    this.close();
    this.emit();
  }

  private onKeyDown(e: KeyboardEvent): void {
    if (!this.isOpen()) {
      if (e.key === 'ArrowDown') this.open(this.input.value);
      return;
    }
    if (e.key === 'ArrowDown') {
      e.preventDefault();
      this.highlight(Math.min(this.active + 1, this.items.length - 1));
    } else if (e.key === 'ArrowUp') {
      e.preventDefault();
      this.highlight(Math.max(this.active - 1, 0));
    } else if (e.key === 'Enter' && this.active >= 0) {
      e.preventDefault();
      this.pick(this.active);
    } else if (e.key === 'Escape') {
      this.close();
    }
  }

  empty(): boolean {
    return this.input.value === '';
  }

  // Resolved id if the text matches a known label, otherwise the raw text.
  value(): number | string {
    const v = this.input.value;
    return v in this.optToId ? this.optToId[v] : v;
  }

  setValueById(id: number): void {
    const label = Object.keys(this.optToId).find(k => this.optToId[k] === id);
    this.input.value = label ?? '';
  }

  text(): string {
    return this.input.value;
  }

  setText(t: string): void {
    this.input.value = t;
  }

  // Re-fire onChange for the current text (used after a programmatic setText).
  fireChange(): void {
    this.emit();
  }

  setOptToId(map: Record<string, number>): void {
    this.optToId = map;
  }

  setAllowNew(allow: boolean): void {
    this.allowNew = allow;
    this.input.readOnly = !allow;
  }

  setMinLength(n: number): void {
    this.minLength = n;
  }

  isValid(): boolean {
    const ok = this.input.value !== '';
    this.input.classList.toggle('invalidinput', !ok);
    return ok;
  }
}

function el2(tag: 'span' | 'li', cls: string, text: string): HTMLElement {
  return el(tag, {class: cls, text});
}
