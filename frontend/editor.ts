// Game edit page: loads /json/gameinfo/, builds the author/tag/link/attribution
// widgets, and wires import + submit. Replaces the old jQuery `EDITOR` object.

import {PairSelector} from './editor/pairSelector';
import {UrlList} from './editor/urlList';
import {Attributions} from './editor/attributions';
import {getCookie, getJSON} from './editor/util';
import type {
  GameInfo,
  GameData,
  ImportResult,
  AuthorTypes,
  TagTypes,
  Pair,
} from './editor/types';

const $ = <T extends HTMLElement>(sel: string) =>
  document.querySelector<T>(sel)!;

let authors: PairSelector;
let tags: PairSelector;
let links: UrlList;
let attributions: Attributions;

function buildAuthors(data: AuthorTypes): PairSelector {
  const idToCat: Record<number, string> = {};
  const idToVal: Record<number, string> = {};
  data.roles.forEach(r => (idToCat[r.id] = r.title));
  data.authors.forEach(a => (idToVal[a.id] = a.name));
  const values = data.value.map(v => [v.role, v.author] as Pair);
  return new PairSelector($('#authors'), {
    idToCat,
    idToVal,
    values,
    catPlaceholder: 'Роль',
    valPlaceholder: 'Имя',
  });
}

function buildTags(data: TagTypes): PairSelector {
  const idToCat: Record<number, string> = {};
  const catToVals: Record<number, Record<string, number>> = {};
  const allowNewValCats: number[] = [];
  for (const c of data.categories) {
    idToCat[c.id] = c.name;
    catToVals[c.id] = Object.fromEntries(c.tags.map(t => [t.name, t.id]));
    if (c.allow_new_tags) allowNewValCats.push(c.id);
  }
  return new PairSelector($('#tags'), {
    idToCat,
    catToVals,
    allowNewValCats,
    values: [],
    showAllVals: true,
    allowNewCat: false,
    catPlaceholder: 'Категория',
    valPlaceholder: 'Свойство',
  });
}

function gameId(): string {
  return $<HTMLElement>('.gameedit').getAttribute('game-id') || '';
}

function updateFields(data: GameData): void {
  if (data.title !== undefined) $<HTMLTextAreaElement>('#title').value = data.title;
  if (data.desc !== undefined) {
    const desc = $<HTMLTextAreaElement>('#description');
    const old = desc.value;
    desc.value = old
      ? data.desc + '\n\n---\n_предыдущая версия описания:_\n\n' + old
      : data.desc;
  }
  attributions.merge(data.description_attributions);
  if (data.release_date !== undefined)
    $<HTMLInputElement>('#release_date').value = data.release_date;
  if (data.authors) authors.merge(data.authors);
  if (data.tags) tags.merge(data.tags);
  if (data.links) links.merge(data.links);
}

function submit(): void {
  const title = $<HTMLTextAreaElement>('#title').value;
  let valid = true;
  if (title === '') {
    $('#title_warning').style.display = '';
    valid = false;
  }
  const date = $<HTMLInputElement>('#release_date');
  if (date.value && !/^\d{4}-\d{2}-\d{2}$/.test(date.value)) {
    date.classList.add('invalidinput');
    valid = false;
  }
  valid = authors.isValid() && valid;
  valid = tags.isValid() && valid;
  valid = links.isValid() && valid;
  if (!valid) return;

  const res: GameData & {game_id?: string} = {
    title,
    desc: $<HTMLTextAreaElement>('#description').value,
    description_attributions: attributions.values(),
    release_date: date.value,
    authors: authors.values(),
    tags: tags.values(),
    links: links.values(),
  };
  if (gameId()) res.game_id = gameId();
  postRedirect('/game/store/', res);
}

function postRedirect(url: string, data: unknown): void {
  const form = document.createElement('form');
  form.method = 'POST';
  form.action = url;
  form.style.display = 'none';
  form.append(hidden('json', JSON.stringify(data)));
  form.append(hidden('csrfmiddlewaretoken', getCookie('csrftoken')));
  document.body.append(form);
  form.submit();
}

function hidden(name: string, value: string): HTMLInputElement {
  const input = document.createElement('input');
  input.type = 'hidden';
  input.name = name;
  input.value = value;
  return input;
}

async function importGame(): Promise<void> {
  const url = $<HTMLInputElement>('#import_url').value;
  const warning = $('#import_warning');
  if (!url) {
    warning.style.display = '';
    warning.textContent = 'А укажите URL';
    return;
  }
  warning.style.display = 'none';
  const data = await getJSON<ImportResult>('/json/import/', {url});
  if (data.error) {
    warning.style.display = '';
    warning.textContent = data.error;
    return;
  }
  updateFields(data);
  $<HTMLInputElement>('#import_url').value = '';
}

async function init(): Promise<void> {
  attributions = new Attributions($('#description_attributions'));
  $('#title').addEventListener('input', () => {
    $('#title_warning').style.display = 'none';
  });
  $('#release_date').addEventListener('input', e =>
    (e.target as HTMLElement).classList.remove('invalidinput'),
  );
  $('#import_button').addEventListener('click', importGame);
  $('#submit').addEventListener('click', submit);

  const params = gameId() ? {game_id: gameId()} : undefined;
  const data = await getJSON<GameInfo>('/json/gameinfo/', params);
  authors = buildAuthors(data.authortypes);
  tags = buildTags(data.tagtypes);
  links = new UrlList($('#links'), data.linktypes.categories);
  if (data.gamedata) updateFields(data.gamedata);
}

document.addEventListener('DOMContentLoaded', init);
