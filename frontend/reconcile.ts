import {el, getCookie} from './editor/util';

type Ref = number | string;
type Pair = [Ref, Ref];
type Link = [Ref, string, string];
type ListField =
  | 'tags'
  | 'authors'
  | 'links'
  | 'description_attributions'
  | 'sources';

interface SourceData {
  id: number;
  type: string;
  url: string;
  detail_url: string;
}

interface ColumnData {
  client_id: string;
  history_id: number | null;
  game_id: number | null;
  title: string;
  release_date: string;
  tags: Pair[];
  authors: Pair[];
  links: Link[];
  description_attributions: string[];
  description: string;
  delete: boolean;
  sources: SourceData[];
}

interface Choices {
  authors: {
    roles: {id: number; title: string}[];
    authors: {id: number; name: string}[];
  };
  tags: {
    categories: {
      id: number;
      name: string;
      allow_new_tags: boolean;
      tags: {id: number; name: string}[];
    }[];
  };
  links: {categories: {id: number; title: string}[]};
}

interface Payload {
  base_history_id: number;
  choices: Choices;
  columns: ColumnData[];
}

const app = document.querySelector<HTMLElement>('#reconcile-app')!;
const csrfInput = document.querySelector<HTMLInputElement>('#reconcile-csrf')!;
const payload = JSON.parse(
  document.querySelector<HTMLElement>('#reconcile-data')!.textContent || '{}',
) as Payload;

let columns = payload.columns;
let nextNewColumn = 1;
const orphanSourceIds = new Set<number>();
const keepOrphanSourceIds = new Set<number>();

const roleById = new Map(payload.choices.authors.roles.map(r => [r.id, r.title]));
const roleIdByName = new Map(payload.choices.authors.roles.map(r => [r.title, r.id]));
const authorById = new Map(payload.choices.authors.authors.map(a => [a.id, a.name]));
const authorIdByName = new Map(payload.choices.authors.authors.map(a => [a.name, a.id]));
const tagCatById = new Map(payload.choices.tags.categories.map(c => [c.id, c]));
const tagById = new Map(
  payload.choices.tags.categories.flatMap(c => c.tags.map(t => [t.id, t.name] as const)),
);
const linkCatById = new Map(payload.choices.links.categories.map(c => [c.id, c.title]));

function clone<T>(value: T): T {
  return JSON.parse(JSON.stringify(value)) as T;
}

function asList(col: ColumnData, field: ListField): unknown[] {
  return col[field] as unknown[];
}

function render(): void {
  const grid = el('div', {class: 'reconcile-grid'});
  grid.style.setProperty('--reconcile-columns', String(columns.length));

  addGridRow(grid, '', (col, i) => columnHeader(col, i), 'reconcile-cell--top');
  addGridRow(grid, 'GameHistory id', historyCell);
  addGridRow(grid, 'Game id', gameCell);
  addGridRow(grid, 'Удалить', deleteCell);
  addGridRow(grid, 'GameSources', sourceCell);
  addGridRow(grid, 'Название', titleCell);
  addGridRow(grid, 'Дата релиза', releaseDateCell);
  addGridRow(grid, 'Свойства', tagCell);
  addGridRow(grid, 'Авторы', authorCell);
  addGridRow(grid, 'URL', linkCell);
  addGridRow(grid, 'Источники описания', attributionCell);
  addGridRow(grid, 'Описание', descriptionCell);

  app.replaceChildren(toolbar(), grid, datalists());
}

function toolbar(): HTMLElement {
  const gameId = el('input', {
    type: 'number',
    min: '1',
    placeholder: 'id игры',
    class: 'reconcile-add-game-id',
  });
  const addGame = button('Добавить игру', () => addGameColumn(gameId.value));
  const addNew = button('Новая колонка', () => {
    columns.push(blankColumn());
    render();
  });
  const save = button('Сохранить сверку', saveReconcile, 'reconcile-save-button');
  return el(
    'div',
    {class: 'reconcile-toolbar'},
    el('label', {}, el('span', {text: 'Добавить по game id'}), gameId),
    addGame,
    addNew,
    save,
  );
}

function addGridRow(
  grid: HTMLElement,
  label: string,
  renderCell: (col: ColumnData, index: number) => HTMLElement,
  extraClass = '',
): void {
  grid.append(el('div', {class: `reconcile-row-label ${extraClass}`, text: label}));
  columns.forEach((col, i) => {
    const cell = renderCell(col, i);
    if (extraClass) cell.classList.add(extraClass);
    if (col.delete) cell.classList.add('reconcile-cell--deleted');
    grid.append(cell);
  });
}

function cell(...children: Node[]): HTMLElement {
  return el('div', {class: 'reconcile-cell'}, ...children);
}

function columnHeader(col: ColumnData, index: number): HTMLElement {
  return cell(
    el('div', {class: 'reconcile-column-title', text: col.title || '(без названия)'}),
    el('div', {class: 'curation-meta', text: columnSubtitle(col)}),
    button('Убрать колонку', () => removeColumn(index), 'reconcile-secondary-button'),
  );
}

function columnSubtitle(col: ColumnData): string {
  const history = col.history_id ? `history #${col.history_id}` : 'new history';
  const game = col.game_id ? `game #${col.game_id}` : 'new game';
  return `${history}, ${game}`;
}

function historyCell(col: ColumnData): HTMLElement {
  if (!col.history_id) return cell(el('span', {class: 'curation-meta', text: 'после сохранения'}));
  return cell(link(`/curation/${col.history_id}/`, `#${col.history_id}`));
}

function gameCell(col: ColumnData): HTMLElement {
  if (!col.game_id) return cell(el('span', {class: 'curation-meta', text: 'после сохранения'}));
  return cell(link(`/game/${col.game_id}/`, `#${col.game_id}`));
}

function deleteCell(col: ColumnData): HTMLElement {
  const input = el('input', {type: 'checkbox'}) as HTMLInputElement;
  input.checked = col.delete;
  input.disabled = !col.game_id && !col.history_id;
  input.addEventListener('change', () => {
    col.delete = input.checked;
    render();
  });
  return cell(
    el(
      'label',
      {class: 'reconcile-check-label'},
      input,
      el('span', {text: 'удалить игру/историю'}),
    ),
    el('div', {
      class: 'curation-meta',
      text: 'Игру с источниками удалить нельзя: сначала перенесите или открепите источники.',
    }),
  );
}

function sourceCell(col: ColumnData, index: number): HTMLElement {
  const root = cell();
  if (!col.sources.length) {
    root.append(el('div', {class: 'curation-meta', text: 'Источников нет.'}));
    return root;
  }
  col.sources.forEach((source, itemIndex) => {
    root.append(
      el(
        'div',
        {class: 'reconcile-source-row'},
        sourceActions(index, itemIndex),
        el(
          'div',
          {class: 'reconcile-source-body'},
          link(source.detail_url, `#${source.id}`),
          el('span', {text: ` ${source.type}`}),
          source.url
            ? el('div', {class: 'curation-meta reconcile-break'}, link(source.url, source.url))
            : el('div', {class: 'curation-meta', text: '(no url)'}),
        ),
      ),
    );
  });
  return root;
}

function titleCell(col: ColumnData): HTMLElement {
  const input = el('input', {type: 'text', value: col.title}) as HTMLInputElement;
  input.addEventListener('input', () => (col.title = input.value));
  return cell(input);
}

function releaseDateCell(col: ColumnData): HTMLElement {
  const input = el('input', {type: 'date', value: col.release_date}) as HTMLInputElement;
  input.addEventListener('input', () => (col.release_date = input.value));
  return cell(input);
}

function tagCell(col: ColumnData, index: number): HTMLElement {
  const root = editableList();
  col.tags.forEach((pair, itemIndex) => {
    const cat = select(
      payload.choices.tags.categories.map(c => [c.id, c.name]),
      pair[0],
      value => {
        pair[0] = Number(value);
        pair[1] = '';
        render();
      },
    );
    const value = textInput(tagText(pair), input => {
      pair[1] = tagValue(Number(pair[0]), input.value);
    });
    value.setAttribute('list', `reconcile-tags-${pair[0]}`);
    root.append(itemRow(cat, value, itemActions('tags', index, itemIndex, true)));
  });
  root.append(addItemButton('Добавить свойство', () => {
    col.tags.push([payload.choices.tags.categories[0]?.id || '', '']);
    render();
  }));
  return cell(root);
}

function authorCell(col: ColumnData, index: number): HTMLElement {
  const root = editableList();
  col.authors.forEach((pair, itemIndex) => {
    const role = select(
      payload.choices.authors.roles.map(r => [r.id, r.title]),
      pair[0],
      value => (pair[0] = value ? Number(value) : ''),
    );
    const author = textInput(authorText(pair), input => {
      pair[1] = authorIdByName.get(input.value) ?? input.value.trim();
    });
    author.setAttribute('list', 'reconcile-authors');
    root.append(itemRow(role, author, itemActions('authors', index, itemIndex, true)));
  });
  root.append(addItemButton('Добавить автора', () => {
    col.authors.push([payload.choices.authors.roles[0]?.id || '', '']);
    render();
  }));
  return cell(root);
}

function linkCell(col: ColumnData, index: number): HTMLElement {
  const root = editableList();
  col.links.forEach((row, itemIndex) => {
    const cat = select(
      payload.choices.links.categories.map(c => [c.id, c.title]),
      row[0],
      value => (row[0] = Number(value)),
    );
    const desc = textInput(row[1], input => (row[1] = input.value));
    desc.placeholder = 'Описание';
    const url = textInput(row[2], input => (row[2] = input.value));
    url.placeholder = 'URL';
    root.append(
      itemRow(cat, desc, url, itemActions('links', index, itemIndex, true)),
    );
  });
  root.append(addItemButton('Добавить URL', () => {
    col.links.push([payload.choices.links.categories[0]?.id || '', '', '']);
    render();
  }));
  return cell(root);
}

function attributionCell(col: ColumnData, index: number): HTMLElement {
  const root = editableList();
  col.description_attributions.forEach((value, itemIndex) => {
    const input = textInput(value, input => {
      col.description_attributions[itemIndex] = input.value;
    });
    root.append(
      itemRow(input, itemActions('description_attributions', index, itemIndex, true)),
    );
  });
  root.append(addItemButton('Добавить источник', () => {
    col.description_attributions.push('');
    render();
  }));
  return cell(root);
}

function descriptionCell(col: ColumnData): HTMLElement {
  const textarea = el('textarea', {class: 'reconcile-description'}) as HTMLTextAreaElement;
  textarea.value = col.description;
  textarea.addEventListener('input', () => (col.description = textarea.value));
  return cell(textarea);
}

function itemActions(
  field: ListField,
  colIndex: number,
  itemIndex: number,
  allowCopy: boolean,
): HTMLElement {
  const root = el('div', {class: 'reconcile-item-actions'});
  root.append(moveButton('←', field, colIndex, itemIndex, -1));
  if (allowCopy) root.append(copyButton('copy ←', field, colIndex, itemIndex, -1));
  if (allowCopy) root.append(copyButton('copy →', field, colIndex, itemIndex, 1));
  root.append(moveButton('→', field, colIndex, itemIndex, 1));
  if (field !== 'sources') {
    root.append(button('×', () => removeItem(field, colIndex, itemIndex), 'reconcile-danger-button'));
  }
  return root;
}

function sourceActions(colIndex: number, itemIndex: number): HTMLElement {
  const root = itemActions('sources', colIndex, itemIndex, false);
  root.append(
    button(
      'открепить',
      () => void orphanSource(colIndex, itemIndex),
      'reconcile-danger-button',
    ),
  );
  return root;
}

async function orphanSource(colIndex: number, itemIndex: number): Promise<void> {
  const source = columns[colIndex].sources[itemIndex];
  const keepOrphan = await confirmOrphanSource(source);
  if (keepOrphan === null) return;
  columns[colIndex].sources.splice(itemIndex, 1);
  orphanSourceIds.add(source.id);
  if (keepOrphan) keepOrphanSourceIds.add(source.id);
  else keepOrphanSourceIds.delete(source.id);
  render();
}

function confirmOrphanSource(source: SourceData): Promise<boolean | null> {
  return new Promise(resolve => {
    const keepOrphan = el('input', {type: 'checkbox'}) as HTMLInputElement;
    const dialog = el(
      'dialog',
      {class: 'reconcile-source-dialog'},
      el('p', {text: `Открепить источник #${source.id} от истории?`}),
      el(
        'label',
        {class: 'reconcile-check-label'},
        keepOrphan,
        el('span', {text: 'оставить сиротой'}),
      ),
      el(
        'div',
        {class: 'reconcile-dialog-actions'},
        button('Отмена', () => dialog.close('cancel'), 'reconcile-secondary-button'),
        button('Открепить', () => dialog.close('detach'), 'reconcile-danger-button'),
      ),
    ) as HTMLDialogElement;

    dialog.addEventListener(
      'close',
      () => {
        const result = dialog.returnValue === 'detach' ? keepOrphan.checked : null;
        dialog.remove();
        resolve(result);
      },
      {once: true},
    );
    document.body.append(dialog);
    dialog.showModal();
  });
}

function moveButton(
  label: string,
  field: ListField,
  colIndex: number,
  itemIndex: number,
  direction: -1 | 1,
): HTMLButtonElement {
  const target = colIndex + direction;
  const result = button(label, () => moveItem(field, colIndex, itemIndex, target), 'reconcile-secondary-button');
  result.disabled = target < 0 || target >= columns.length;
  return result;
}

function copyButton(
  label: string,
  field: ListField,
  colIndex: number,
  itemIndex: number,
  direction: -1 | 1,
): HTMLButtonElement {
  const target = colIndex + direction;
  const result = button(label, () => copyItem(field, colIndex, itemIndex, target), 'reconcile-secondary-button');
  result.disabled = target < 0 || target >= columns.length;
  return result;
}

function moveItem(field: ListField, from: number, itemIndex: number, to: number): void {
  if (to < 0 || to >= columns.length) return;
  const fromList = asList(columns[from], field);
  const [item] = fromList.splice(itemIndex, 1);
  if (field === 'sources') {
    orphanSourceIds.delete((item as SourceData).id);
    keepOrphanSourceIds.delete((item as SourceData).id);
  }
  asList(columns[to], field).push(item);
  render();
}

function copyItem(field: ListField, from: number, itemIndex: number, to: number): void {
  if (to < 0 || to >= columns.length) return;
  asList(columns[to], field).push(clone(asList(columns[from], field)[itemIndex]));
  render();
}

function removeItem(field: ListField, colIndex: number, itemIndex: number): void {
  asList(columns[colIndex], field).splice(itemIndex, 1);
  render();
}

function editableList(): HTMLElement {
  return el('div', {class: 'reconcile-editable-list'});
}

function itemRow(...children: Node[]): HTMLElement {
  return el('div', {class: 'reconcile-item-row'}, ...children);
}

function addItemButton(label: string, onClick: () => void): HTMLElement {
  return button(label, onClick, 'reconcile-add-item-button');
}

function select(
  options: [Ref, string][],
  value: Ref,
  onChange: (value: string) => void,
): HTMLSelectElement {
  const input = el('select') as HTMLSelectElement;
  input.append(el('option', {value: '', text: '—'}));
  options.forEach(([id, title]) => input.append(el('option', {value: String(id), text: title})));
  input.value = String(value ?? '');
  input.addEventListener('change', () => onChange(input.value));
  return input;
}

function textInput(value: string, onInput: (input: HTMLInputElement) => void): HTMLInputElement {
  const input = el('input', {type: 'text', value}) as HTMLInputElement;
  input.addEventListener('input', () => onInput(input));
  return input;
}

function tagText(pair: Pair): string {
  return typeof pair[1] === 'number' ? tagById.get(pair[1]) || '' : String(pair[1] || '');
}

function tagValue(categoryId: number, text: string): Ref {
  const cat = tagCatById.get(categoryId);
  const match = cat?.tags.find(tag => tag.name === text);
  return match?.id ?? text.trim();
}

function authorText(pair: Pair): string {
  return typeof pair[1] === 'number'
    ? authorById.get(pair[1]) || ''
    : String(pair[1] || '');
}

function blankColumn(): ColumnData {
  return {
    client_id: `new-${nextNewColumn++}`,
    history_id: null,
    game_id: null,
    title: '',
    release_date: '',
    tags: [],
    authors: [],
    links: [],
    description_attributions: [],
    description: '',
    delete: false,
    sources: [],
  };
}

async function addGameColumn(rawGameId: string): Promise<void> {
  const gameId = Number(rawGameId);
  if (!Number.isInteger(gameId) || gameId <= 0) {
    window.alert('Укажите положительный id игры.');
    return;
  }
  if (columns.some(col => col.game_id === gameId)) {
    window.alert('Эта игра уже открыта в редакторе.');
    return;
  }
  const response = await fetch(gameUrl(gameId), {headers: {'X-Requested-With': 'XMLHttpRequest'}});
  if (!response.ok) {
    window.alert('Не удалось загрузить игру.');
    return;
  }
  columns.push((await response.json()) as ColumnData);
  render();
}

function gameUrl(gameId: number): string {
  return app.dataset.gameUrl!.replace('/0/', `/${gameId}/`);
}

function removeColumn(index: number): void {
  if (columns.length === 1) {
    window.alert('Нельзя убрать последнюю колонку.');
    return;
  }
  if (!window.confirm('Убрать колонку из редактора? Сама игра не изменится.')) return;
  columns.splice(index, 1);
  render();
}

async function saveReconcile(): Promise<void> {
  const error = validationError();
  if (error) {
    window.alert(error);
    return;
  }
  const response = await fetch(window.location.href, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      'X-CSRFToken': csrfInput.value || getCookie('csrftoken'),
    },
    body: JSON.stringify({
      columns,
      orphan_source_ids: Array.from(orphanSourceIds),
      keep_orphan_source_ids: Array.from(keepOrphanSourceIds),
    }),
  });
  const result = await response.json();
  if (!response.ok) {
    window.alert(result.error || 'Не удалось сохранить сверку.');
    return;
  }
  window.location.href = result.redirect;
}

function validationError(): string | null {
  for (const col of columns) {
    if (col.delete) {
      if (col.sources.length) {
        return 'Нельзя удалить игру с источниками: перенесите или открепите их.';
      }
      continue;
    }
    const createsOrHasGame = col.game_id || !col.history_id;
    if (createsOrHasGame && !col.title.trim()) {
      return 'У каждой новой или существующей игры должно быть название.';
    }
  }
  return null;
}

function datalists(): HTMLElement {
  const root = el('div');
  root.append(
    el(
      'datalist',
      {id: 'reconcile-authors'},
      ...payload.choices.authors.authors.map(author => el('option', {value: author.name})),
    ),
  );
  payload.choices.tags.categories.forEach(cat => {
    root.append(
      el(
        'datalist',
        {id: `reconcile-tags-${cat.id}`},
        ...cat.tags.map(tag => el('option', {value: tag.name})),
      ),
    );
  });
  return root;
}

function button(label: string, onClick: () => void, cls = ''): HTMLButtonElement {
  const btn = el('button', {type: 'button', class: cls, text: label}) as HTMLButtonElement;
  btn.addEventListener('click', onClick);
  return btn;
}

function link(href: string, text: string): HTMLAnchorElement {
  return el('a', {href, text}) as HTMLAnchorElement;
}

document.addEventListener('DOMContentLoaded', render);
