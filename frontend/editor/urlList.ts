// Multi-row link/upload editor (replaces the old `urlUpload` widget). Each row
// is a type combobox + URL + description, with file upload and blur autofill.

import {Combobox} from './combobox';
import {getCookie, getJSON, el} from './util';
import type {LinkCategory, Link} from './types';

interface Row {
  element: HTMLElement;
  cats: Combobox;
  url: HTMLInputElement;
  desc: HTMLInputElement;
  button: HTMLButtonElement;
  delicon: HTMLElement;
}

function label(text: string): HTMLLabelElement {
  return el('label', {}, el('span', {class: 'inputlabel', text}));
}

export class UrlList {
  private rows: Row[] = [];
  private catToId: Record<string, number> = {};
  private idToCat: Record<number, string> = {};
  private enabled = new Set<number>();

  constructor(
    private root: HTMLElement,
    private categories: LinkCategory[],
    values: Link[] = [],
  ) {
    for (const c of categories) {
      this.catToId[c.title] = c.id;
      this.idToCat[c.id] = c.title;
      if (c.uploadable) this.enabled.add(c.id);
    }
    for (const [cat, desc, url] of [...values, ['', '', '']] as Link[])
      this.addRow(cat, url, desc);
  }

  private addRow(catId?: number | string, url = '', desc = ''): void {
    if (this.rows.length) this.last().delicon.style.display = '';

    const element = el('div', {class: 'entry-url'});
    const urlEl = el('input', {class: 'urlinput'});
    const descEl = el('input', {class: 'descinput'});
    const button = el('button', {class: 'upload_button', type: 'button'});
    button.textContent = 'Закачать';
    const file = el('input', {type: 'file'});
    file.style.display = 'none';
    const progress = el('progress');
    progress.style.display = 'none';
    const delicon = el('span', {class: 'ico', text: '✖ '});
    delicon.style.display = 'none';
    const catEl = el('span', {class: 'typeinput'});

    const urlLab = label('URL: ');
    urlLab.append(urlEl);
    const descLab = label('Описание: ');
    descLab.append(descEl);
    const catLab = label('Тип ссылки: ');
    catLab.append(catEl);
    element.append(
      urlLab,
      el('span', {text: 'или'}),
      button,
      delicon,
      file,
      progress,
      descLab,
      catLab,
    );
    this.root.append(element);

    const cats = new Combobox(catEl, {
      minLength: 0,
      optToId: this.catToId,
      id: typeof catId === 'number' ? catId : undefined,
      showAll: true,
      allowNew: false,
    });
    urlEl.value = url;
    descEl.value = desc;

    const row: Row = {element, cats, url: urlEl, desc: descEl, button, delicon};
    this.rows.push(row);

    const checkEmpty = () => {
      if (cats.empty() && urlEl.value === '' && descEl.value === '')
        this.remove(row);
    };
    const onInput = () => {
      if (row === this.last()) this.addRow();
    };
    const updateButton = (id?: number) => {
      button.disabled = id !== undefined && !this.enabled.has(id);
    };
    const categorize = async () => {
      const v = urlEl.value;
      const cat = cats.value();
      if (!v || (descEl.value && cat)) return;
      const data = await getJSON<{desc: string; cat: number}>(
        '/json/categorizeurl/',
        {url: v, desc: descEl.value, cat: String(cat || '')},
      );
      if (!descEl.value) descEl.value = data.desc;
      if (!cats.value()) cats.setValueById(data.cat);
    };

    cats.onChange = id => {
      updateButton(id);
      onInput();
    };
    cats.onBlur = checkEmpty;
    updateButton(typeof catId === 'number' ? catId : undefined);

    urlEl.addEventListener('input', () =>
      urlEl.classList.remove('invalidinput'),
    );
    urlEl.addEventListener('keydown', onInput);
    urlEl.addEventListener('blur', () => {
      categorize();
      checkEmpty();
    });
    descEl.addEventListener('input', () =>
      descEl.classList.remove('invalidinput'),
    );
    descEl.addEventListener('keydown', onInput);
    descEl.addEventListener('blur', checkEmpty);

    button.addEventListener('click', () => file.click());
    file.addEventListener('change', () => {
      if (!file.files?.length) return;
      this.upload(file.files[0], progress, urlEl, onInput, categorize);
    });
    delicon.addEventListener('click', () => this.remove(row));
  }

  private upload(
    file: File,
    progress: HTMLProgressElement,
    urlEl: HTMLInputElement,
    onInput: () => void,
    categorize: () => void,
  ): void {
    progress.style.display = '';
    const xhr = new XMLHttpRequest();
    xhr.open('POST', '/json/upload/');
    xhr.upload.addEventListener('progress', e => {
      if (e.lengthComputable) {
        progress.value = e.loaded;
        progress.max = e.total;
      }
    });
    xhr.onload = () => {
      if (xhr.status >= 200 && xhr.status < 300) {
        urlEl.value = JSON.parse(xhr.responseText).url;
        onInput();
        categorize();
      } else {
        progress.style.display = 'none';
        window.alert('Что-то не закачалось: ' + xhr.statusText);
      }
    };
    xhr.onerror = () => {
      progress.style.display = 'none';
      window.alert('Что-то не закачалось.');
    };
    const fd = new FormData();
    fd.append('csrfmiddlewaretoken', getCookie('csrftoken'));
    fd.append('file', file);
    xhr.send(fd);
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
    return this.rows.slice(0, -1).every(r => {
      const ok = r.cats.isValid();
      r.desc.classList.toggle('invalidinput', r.desc.value === '');
      r.url.classList.toggle('invalidinput', r.url.value === '');
      return ok && r.desc.value !== '' && r.url.value !== '';
    });
  }

  values(): Link[] {
    return this.rows
      .slice(0, -1)
      .map(r => [r.cats.value(), r.desc.value, r.url.value]);
  }

  merge(d: Link[]): void {
    for (let [cat, desc, url] of d) {
      let cloneEnabled = false;
      if (typeof cat === 'number') {
        cloneEnabled = this.enabled.has(cat);
        cat = this.idToCat[cat];
      }
      const exists = this.rows
        .slice(0, -1)
        .some(r => r.url.value === url && r.cats.text() === cat);
      if (exists) continue;
      const blank = this.last();
      this.addRow();
      blank.cats.setText(cat as string);
      blank.url.value = url;
      blank.desc.value = desc;
      blank.button.disabled = !cloneEnabled;
    }
  }
}
