// Progressive enhancement for the OpenRouter models table on the curation
// "Модели LLM" page: instant search by model name and click-to-sort columns,
// defaulting to the "$/игра" estimate so the cheapest models surface first.

function initSearch(table: HTMLTableElement): void {
  const input = document.querySelector<HTMLInputElement>('#llm-search');
  const rows = Array.from(table.tBodies[0].rows);
  input?.addEventListener('input', () => {
    const q = input.value.trim().toLowerCase();
    for (const row of rows) {
      const name = row.dataset.name?.toLowerCase() ?? '';
      row.style.display = name.includes(q) ? '' : 'none';
    }
  });
}

function cellValue(row: HTMLTableRowElement, index: number, numeric: boolean) {
  const raw = row.cells[index].dataset.sort ?? '';
  if (!numeric) return raw;
  // Unpriced/variable rows carry an empty value; sort them to the bottom
  // (Number('') is 0, so guard it explicitly).
  const n = raw === '' ? NaN : Number(raw);
  return Number.isNaN(n) ? Infinity : n;
}

type SortController = {
  resortIfCostColumn: () => void;
};

function initSort(table: HTMLTableElement): SortController {
  const body = table.tBodies[0];
  const headers = Array.from(table.tHead!.rows[0].cells);
  const strip = (s: string) => s.replace(/[ ▲▼]+$/, '');
  let current: { th: HTMLTableCellElement; ascending: boolean } | null = null;

  const sortBy = (th: HTMLTableCellElement, ascending: boolean) => {
    const index = headers.indexOf(th);
    const numeric = th.dataset.sortType === 'number';
    const rows = Array.from(body.rows);
    rows.sort((a, b) => {
      const va = cellValue(a, index, numeric);
      const vb = cellValue(b, index, numeric);
      const cmp = va < vb ? -1 : va > vb ? 1 : 0;
      return ascending ? cmp : -cmp;
    });
    rows.forEach(row => body.appendChild(row));

    for (const other of headers) other.textContent = strip(other.textContent!);
    th.textContent = strip(th.textContent!) + (ascending ? ' ▲' : ' ▼');
    current = { th, ascending };
  };

  for (const th of headers) {
    if (!th.dataset.sortType) continue;
    let ascending = true;
    th.addEventListener('click', () => {
      sortBy(th, ascending);
      ascending = !ascending;
    });
  }

  const initial = headers.find(th => 'defaultSort' in th.dataset);
  if (initial) sortBy(initial, true);

  return {
    resortIfCostColumn: () => {
      if (current?.th.dataset.costColumn !== undefined) {
        sortBy(current.th, current.ascending);
      }
    },
  };
}

function parseInput(form: HTMLFormElement, name: string): number {
  const input = form.elements.namedItem(name);
  if (!(input instanceof HTMLInputElement)) return 0;
  const value = Number(input.value);
  return Number.isFinite(value) && value > 0 ? value : 0;
}

function cost(
  row: HTMLTableRowElement,
  prompt: number,
  cached: number,
  write: number,
  completion: number,
): number | null {
  const inputCost = Number(row.dataset.inputCost);
  const cachedCost = Number(row.dataset.cachedInputCost);
  const writeCost = Number(row.dataset.cacheWriteCost);
  const outputCost = Number(row.dataset.outputCost);
  if (
    [inputCost, cachedCost, writeCost, outputCost].some(n => Number.isNaN(n)) ||
    (prompt && inputCost < 0) ||
    (cached && cachedCost < 0) ||
    (write && writeCost < 0) ||
    (completion && outputCost < 0)
  ) {
    return null;
  }
  const dollars =
    (inputCost * prompt + cachedCost * cached + writeCost * write + outputCost * completion) / 1_000_000;
  return dollars * 100;
}

function formatCost(value: number | null): string {
  if (value === null) return '—';
  const text = value.toFixed(4).replace('.', ',');
  const head = text.replace(/,?0+$/, '');
  const tail = text.slice(head.length);
  return tail ? `${head}<span class="zeros">${tail}</span>` : head;
}

function initCostForm(sort: SortController): void {
  const form = document.querySelector<HTMLFormElement>('#llm-cost-form');
  if (!form) return;

  const update = () => {
    const prompt = parseInput(form, 'prompt');
    const cached = parseInput(form, 'cached');
    const write = parseInput(form, 'write');
    const completion = parseInput(form, 'completion');
    for (const cell of document.querySelectorAll<HTMLTableCellElement>('[data-cost-cell]')) {
      const row = cell.closest('tr');
      if (!(row instanceof HTMLTableRowElement)) continue;
      const value = cost(row, prompt, cached, write, completion);
      cell.dataset.sort = value === null ? '' : String(value);
      cell.innerHTML = formatCost(value);
    }
    sort.resortIfCostColumn();
  };

  form.addEventListener('input', update);
  form.addEventListener('submit', event => event.preventDefault());
  update();
}

document.addEventListener('DOMContentLoaded', () => {
  const table = document.querySelector<HTMLTableElement>('#llm-available');
  if (!table) return;
  initSearch(table);
  const sort = initSort(table);
  initCostForm(sort);
});
