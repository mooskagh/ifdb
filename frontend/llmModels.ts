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

function initSort(table: HTMLTableElement): void {
  const body = table.tBodies[0];
  const headers = Array.from(table.tHead!.rows[0].cells);
  const strip = (s: string) => s.replace(/[ ▲▼]+$/, '');

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
}

document.addEventListener('DOMContentLoaded', () => {
  const table = document.querySelector<HTMLTableElement>('#llm-available');
  if (!table) return;
  initSearch(table);
  initSort(table);
});
