// Chip editor for description attribution sources. Each source is a removable
// chip; a trailing text input adds new ones on Enter/comma/blur.

import {el} from './util';

export class Attributions {
  private items: string[] = [];
  private input: HTMLInputElement;

  constructor(private root: HTMLElement) {
    root.classList.add('chips');
    this.input = el('input', {
      class: 'chip-input',
      placeholder: 'Добавить источник',
    });
    root.append(this.input);

    const commit = () => {
      this.add(this.input.value);
      this.input.value = '';
    };
    this.input.addEventListener('keydown', e => {
      if (e.key === 'Enter' || e.key === ',') {
        e.preventDefault();
        commit();
      } else if (e.key === 'Backspace' && this.input.value === '') {
        this.remove(this.items[this.items.length - 1]);
      }
    });
    this.input.addEventListener('blur', commit);
  }

  private add(raw: string): void {
    const value = raw.trim();
    if (!value || this.items.includes(value)) return;
    this.items.push(value);
    const chip = el('span', {class: 'chip', text: value});
    const x = el('span', {class: 'chip-remove', text: '✖'});
    x.addEventListener('click', () => {
      chip.remove();
      this.items.splice(this.items.indexOf(value), 1);
    });
    chip.append(x);
    this.root.insertBefore(chip, this.input);
  }

  private remove(value: string): void {
    if (value === undefined) return;
    this.items = this.items.filter(v => v !== value);
    for (const chip of this.root.querySelectorAll('.chip')) {
      if (chip.firstChild?.textContent === value) chip.remove();
    }
  }

  merge(strings: string[] | undefined): void {
    strings?.forEach(s => this.add(s));
  }

  values(): string[] {
    return this.items.slice();
  }
}
