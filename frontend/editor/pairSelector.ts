// Multi-row category -> value combobox editor (authors & tags). The last row is
// always blank; typing in it appends another; clearing a row removes it.

import {Combobox} from './combobox';
import {el} from './util';
import type {Pair} from './types';

export interface PairSelectorOptions {
  idToCat: Record<number, string>;
  idToVal?: Record<number, string>;
  catToVals?: Record<number, Record<string, number>>; // tags dependency
  allowNewValCats?: number[];
  values: Pair[];
  allowNewCat?: boolean;
  showAllVals?: boolean;
  catPlaceholder?: string;
  valPlaceholder?: string;
}

interface Row {
  element: HTMLElement;
  cats: Combobox;
  vals: Combobox;
  delicon: HTMLElement;
}

export class PairSelector {
  private rows: Row[] = [];
  private catToId: Record<string, number>;
  private valToId: Record<string, number>;
  private idToVal: Record<number, string>;

  constructor(
    private root: HTMLElement,
    private o: PairSelectorOptions,
  ) {
    this.idToVal = {...(o.idToVal ?? {})};
    if (o.catToVals) {
      for (const vals of Object.values(o.catToVals))
        for (const [label, id] of Object.entries(vals)) this.idToVal[id] = label;
    }
    this.catToId = reverse(o.idToCat);
    this.valToId = reverse(this.idToVal);

    for (const [cat, val] of [...o.values, ['', '']] as Pair[])
      this.addRow(cat, val);
  }

  private addRow(catId?: number | string, valId?: number | string): void {
    if (this.rows.length) this.last().delicon.style.display = '';

    const element = el('div', {class: 'entry'});
    const catEl = el('span', {class: 'narrow-list'});
    const valEl = el('span', {class: 'wide-list'});
    const delicon = el('span', {class: 'ico', text: '✖'});
    delicon.style.display = 'none';
    element.append(catEl, valEl, delicon);
    this.root.append(element);

    const cats = new Combobox(catEl, {
      minLength: 0,
      optToId: this.catToId,
      id: typeof catId === 'number' ? catId : undefined,
      showAll: true,
      allowNew: this.o.allowNewCat ?? true,
      placeholder: this.o.catPlaceholder,
    });
    const vals = new Combobox(valEl, {
      minLength: this.o.catToVals ? 0 : 2,
      optToId: this.o.catToVals ? {} : this.valToId,
      id: typeof valId === 'number' ? valId : undefined,
      showAll: this.o.showAllVals,
      placeholder: this.o.valPlaceholder,
    });

    const row: Row = {element, cats, vals, delicon};
    const checkEmpty = () => {
      if (cats.empty() && vals.empty()) this.remove(row);
    };
    cats.onBlur = checkEmpty;
    vals.onBlur = checkEmpty;
    vals.onChange = () => this.onInput(row);
    cats.onChange = id => {
      if (this.o.catToVals) this.updateVals(row, id);
      this.onInput(row);
    };
    delicon.addEventListener('click', () => this.remove(row));

    this.rows.push(row);
    if (this.o.catToVals)
      this.updateVals(row, typeof catId === 'number' ? catId : undefined);
  }

  private updateVals(row: Row, catId: number | undefined): void {
    if (catId === undefined) {
      row.vals.setText('');
      row.vals.setOptToId({});
      row.vals.setAllowNew(false);
      return;
    }
    const valToId = this.o.catToVals![catId] ?? {};
    const allowNew = (this.o.allowNewValCats ?? []).includes(catId);
    if (!allowNew && !(row.vals.text() in valToId)) row.vals.setText('');
    row.vals.setMinLength(allowNew ? 2 : 0);
    row.vals.setAllowNew(allowNew);
    row.vals.setOptToId(valToId);
  }

  private onInput(row: Row): void {
    if (row === this.last()) this.addRow();
  }

  private remove(row: Row): void {
    if (row === this.last()) return;
    row.element.remove();
    this.rows.splice(this.rows.indexOf(row), 1);
  }

  private last(): Row {
    return this.rows[this.rows.length - 1];
  }

  isValid(): boolean {
    return this.rows
      .slice(0, -1)
      .every(r => [r.cats.isValid(), r.vals.isValid()].every(Boolean));
  }

  values(): Pair[] {
    return this.rows.slice(0, -1).map(r => [r.cats.value(), r.vals.value()]);
  }

  merge(d: Pair[]): void {
    for (let [cat, val] of d) {
      if (typeof cat === 'number') cat = this.o.idToCat[cat];
      if (typeof val === 'number') val = this.idToVal[val];
      const exists = this.rows
        .slice(0, -1)
        .some(r => r.cats.text() === cat && r.vals.text() === val);
      if (exists) continue;
      const blank = this.last();
      this.addRow();
      blank.cats.setText(cat as string);
      blank.cats.fireChange();
      blank.vals.setText(val as string);
    }
  }
}

function reverse(d: Record<number, string>): Record<string, number> {
  const r: Record<string, number> = {};
  for (const k in d) r[d[k]] = Number(k);
  return r;
}
