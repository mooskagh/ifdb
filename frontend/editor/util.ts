// Small DOM/HTTP helpers shared across the editor modules.

export function getCookie(name: string): string {
  for (const cookie of document.cookie.split(';')) {
    const c = cookie.trim();
    if (c.startsWith(name + '=')) {
      return decodeURIComponent(c.slice(name.length + 1));
    }
  }
  return '';
}

export async function getJSON<T>(
  url: string,
  params?: Record<string, string>,
): Promise<T> {
  const qs = params ? '?' + new URLSearchParams(params).toString() : '';
  const resp = await fetch(url + qs, {
    headers: {'X-Requested-With': 'XMLHttpRequest'},
  });
  return resp.json();
}

type Attrs = Record<string, string | number | boolean>;
type Child = Node | string;

// Tiny element builder: el('input', {class: 'foo'}, child1, child2).
export function el<K extends keyof HTMLElementTagNameMap>(
  tag: K,
  attrs: Attrs = {},
  ...children: Child[]
): HTMLElementTagNameMap[K] {
  const node = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs)) {
    if (v === false) continue;
    if (k === 'text') node.textContent = String(v);
    else node.setAttribute(k, String(v));
  }
  node.append(...children);
  return node;
}
