"use strict";
(() => {
  // frontend/editor/util.ts
  function getCookie(name) {
    for (const cookie of document.cookie.split(";")) {
      const c = cookie.trim();
      if (c.startsWith(name + "=")) {
        return decodeURIComponent(c.slice(name.length + 1));
      }
    }
    return "";
  }
  function el(tag, attrs = {}, ...children) {
    const node = document.createElement(tag);
    for (const [k, v] of Object.entries(attrs)) {
      if (v === false) continue;
      if (k === "text") node.textContent = String(v);
      else node.setAttribute(k, String(v));
    }
    node.append(...children);
    return node;
  }

  // frontend/reconcile.ts
  var app = document.querySelector("#reconcile-app");
  var csrfInput = document.querySelector("#reconcile-csrf");
  var payload = JSON.parse(
    document.querySelector("#reconcile-data").textContent || "{}"
  );
  var columns = payload.columns;
  var nextNewColumn = 1;
  var orphanSourceIds = /* @__PURE__ */ new Set();
  var roleById = new Map(payload.choices.authors.roles.map((r) => [r.id, r.title]));
  var roleIdByName = new Map(payload.choices.authors.roles.map((r) => [r.title, r.id]));
  var authorById = new Map(payload.choices.authors.authors.map((a) => [a.id, a.name]));
  var authorIdByName = new Map(payload.choices.authors.authors.map((a) => [a.name, a.id]));
  var tagCatById = new Map(payload.choices.tags.categories.map((c) => [c.id, c]));
  var tagById = new Map(
    payload.choices.tags.categories.flatMap((c) => c.tags.map((t) => [t.id, t.name]))
  );
  var linkCatById = new Map(payload.choices.links.categories.map((c) => [c.id, c.title]));
  function clone(value) {
    return JSON.parse(JSON.stringify(value));
  }
  function asList(col, field) {
    return col[field];
  }
  function render() {
    const grid = el("div", { class: "reconcile-grid" });
    grid.style.setProperty("--reconcile-columns", String(columns.length));
    addGridRow(grid, "", (col, i) => columnHeader(col, i), "reconcile-cell--top");
    addGridRow(grid, "GameHistory id", historyCell);
    addGridRow(grid, "Game id", gameCell);
    addGridRow(grid, "\u0423\u0434\u0430\u043B\u0438\u0442\u044C", deleteCell);
    addGridRow(grid, "GameSources", sourceCell);
    addGridRow(grid, "\u041D\u0430\u0437\u0432\u0430\u043D\u0438\u0435", titleCell);
    addGridRow(grid, "\u0414\u0430\u0442\u0430 \u0440\u0435\u043B\u0438\u0437\u0430", releaseDateCell);
    addGridRow(grid, "\u0421\u0432\u043E\u0439\u0441\u0442\u0432\u0430", tagCell);
    addGridRow(grid, "\u0410\u0432\u0442\u043E\u0440\u044B", authorCell);
    addGridRow(grid, "URL", linkCell);
    addGridRow(grid, "\u0418\u0441\u0442\u043E\u0447\u043D\u0438\u043A\u0438 \u043E\u043F\u0438\u0441\u0430\u043D\u0438\u044F", attributionCell);
    addGridRow(grid, "\u041E\u043F\u0438\u0441\u0430\u043D\u0438\u0435", descriptionCell);
    app.replaceChildren(toolbar(), grid, datalists());
  }
  function toolbar() {
    const gameId = el("input", {
      type: "number",
      min: "1",
      placeholder: "id \u0438\u0433\u0440\u044B",
      class: "reconcile-add-game-id"
    });
    const addGame = button("\u0414\u043E\u0431\u0430\u0432\u0438\u0442\u044C \u0438\u0433\u0440\u0443", () => addGameColumn(gameId.value));
    const addNew = button("\u041D\u043E\u0432\u0430\u044F \u043A\u043E\u043B\u043E\u043D\u043A\u0430", () => {
      columns.push(blankColumn());
      render();
    });
    const save = button("\u0421\u043E\u0445\u0440\u0430\u043D\u0438\u0442\u044C \u0441\u0432\u0435\u0440\u043A\u0443", saveReconcile, "reconcile-save-button");
    return el(
      "div",
      { class: "reconcile-toolbar" },
      el("label", {}, el("span", { text: "\u0414\u043E\u0431\u0430\u0432\u0438\u0442\u044C \u043F\u043E game id" }), gameId),
      addGame,
      addNew,
      save
    );
  }
  function addGridRow(grid, label, renderCell, extraClass = "") {
    grid.append(el("div", { class: `reconcile-row-label ${extraClass}`, text: label }));
    columns.forEach((col, i) => {
      const cell2 = renderCell(col, i);
      if (extraClass) cell2.classList.add(extraClass);
      if (col.delete) cell2.classList.add("reconcile-cell--deleted");
      grid.append(cell2);
    });
  }
  function cell(...children) {
    return el("div", { class: "reconcile-cell" }, ...children);
  }
  function columnHeader(col, index) {
    return cell(
      el("div", { class: "reconcile-column-title", text: col.title || "(\u0431\u0435\u0437 \u043D\u0430\u0437\u0432\u0430\u043D\u0438\u044F)" }),
      el("div", { class: "curation-meta", text: columnSubtitle(col) }),
      button("\u0423\u0431\u0440\u0430\u0442\u044C \u043A\u043E\u043B\u043E\u043D\u043A\u0443", () => removeColumn(index), "reconcile-secondary-button")
    );
  }
  function columnSubtitle(col) {
    const history = col.history_id ? `history #${col.history_id}` : "new history";
    const game = col.game_id ? `game #${col.game_id}` : "new game";
    return `${history}, ${game}`;
  }
  function historyCell(col) {
    if (!col.history_id) return cell(el("span", { class: "curation-meta", text: "\u043F\u043E\u0441\u043B\u0435 \u0441\u043E\u0445\u0440\u0430\u043D\u0435\u043D\u0438\u044F" }));
    return cell(link(`/curation/${col.history_id}/`, `#${col.history_id}`));
  }
  function gameCell(col) {
    if (!col.game_id) return cell(el("span", { class: "curation-meta", text: "\u043F\u043E\u0441\u043B\u0435 \u0441\u043E\u0445\u0440\u0430\u043D\u0435\u043D\u0438\u044F" }));
    return cell(link(`/game/${col.game_id}/`, `#${col.game_id}`));
  }
  function deleteCell(col) {
    const input = el("input", { type: "checkbox" });
    input.checked = col.delete;
    input.disabled = !col.game_id && !col.history_id;
    input.addEventListener("change", () => {
      col.delete = input.checked;
      render();
    });
    return cell(
      el(
        "label",
        { class: "reconcile-check-label" },
        input,
        el("span", { text: "\u0443\u0434\u0430\u043B\u0438\u0442\u044C \u0438\u0433\u0440\u0443/\u0438\u0441\u0442\u043E\u0440\u0438\u044E" })
      ),
      el("div", {
        class: "curation-meta",
        text: "\u0418\u0433\u0440\u0443 \u0441 \u0438\u0441\u0442\u043E\u0447\u043D\u0438\u043A\u0430\u043C\u0438 \u0443\u0434\u0430\u043B\u0438\u0442\u044C \u043D\u0435\u043B\u044C\u0437\u044F: \u0441\u043D\u0430\u0447\u0430\u043B\u0430 \u043F\u0435\u0440\u0435\u043D\u0435\u0441\u0438\u0442\u0435 \u0438\u043B\u0438 \u043E\u0442\u043A\u0440\u0435\u043F\u0438\u0442\u0435 \u0438\u0441\u0442\u043E\u0447\u043D\u0438\u043A\u0438."
      })
    );
  }
  function sourceCell(col, index) {
    const root = cell();
    if (!col.sources.length) {
      root.append(el("div", { class: "curation-meta", text: "\u0418\u0441\u0442\u043E\u0447\u043D\u0438\u043A\u043E\u0432 \u043D\u0435\u0442." }));
      return root;
    }
    col.sources.forEach((source, itemIndex) => {
      root.append(
        el(
          "div",
          { class: "reconcile-source-row" },
          sourceActions(index, itemIndex),
          el(
            "div",
            { class: "reconcile-source-body" },
            link(source.detail_url, `#${source.id}`),
            el("span", { text: ` ${source.type}` }),
            source.url ? el("div", { class: "curation-meta reconcile-break", text: source.url }) : el("div", { class: "curation-meta", text: "(no url)" })
          )
        )
      );
    });
    return root;
  }
  function titleCell(col) {
    const input = el("input", { type: "text", value: col.title });
    input.addEventListener("input", () => col.title = input.value);
    return cell(input);
  }
  function releaseDateCell(col) {
    const input = el("input", { type: "date", value: col.release_date });
    input.addEventListener("input", () => col.release_date = input.value);
    return cell(input);
  }
  function tagCell(col, index) {
    const root = editableList();
    col.tags.forEach((pair, itemIndex) => {
      const cat = select(
        payload.choices.tags.categories.map((c) => [c.id, c.name]),
        pair[0],
        (value2) => {
          pair[0] = Number(value2);
          pair[1] = "";
          render();
        }
      );
      const value = textInput(tagText(pair), (input) => {
        pair[1] = tagValue(Number(pair[0]), input.value);
      });
      value.setAttribute("list", `reconcile-tags-${pair[0]}`);
      root.append(itemRow(cat, value, itemActions("tags", index, itemIndex, true)));
    });
    root.append(addItemButton("\u0414\u043E\u0431\u0430\u0432\u0438\u0442\u044C \u0441\u0432\u043E\u0439\u0441\u0442\u0432\u043E", () => {
      col.tags.push([payload.choices.tags.categories[0]?.id || "", ""]);
      render();
    }));
    return cell(root);
  }
  function authorCell(col, index) {
    const root = editableList();
    col.authors.forEach((pair, itemIndex) => {
      const role = select(
        payload.choices.authors.roles.map((r) => [r.id, r.title]),
        pair[0],
        (value) => pair[0] = value ? Number(value) : ""
      );
      const author = textInput(authorText(pair), (input) => {
        pair[1] = authorIdByName.get(input.value) ?? input.value.trim();
      });
      author.setAttribute("list", "reconcile-authors");
      root.append(itemRow(role, author, itemActions("authors", index, itemIndex, true)));
    });
    root.append(addItemButton("\u0414\u043E\u0431\u0430\u0432\u0438\u0442\u044C \u0430\u0432\u0442\u043E\u0440\u0430", () => {
      col.authors.push([payload.choices.authors.roles[0]?.id || "", ""]);
      render();
    }));
    return cell(root);
  }
  function linkCell(col, index) {
    const root = editableList();
    col.links.forEach((row, itemIndex) => {
      const cat = select(
        payload.choices.links.categories.map((c) => [c.id, c.title]),
        row[0],
        (value) => row[0] = Number(value)
      );
      const desc = textInput(row[1], (input) => row[1] = input.value);
      desc.placeholder = "\u041E\u043F\u0438\u0441\u0430\u043D\u0438\u0435";
      const url = textInput(row[2], (input) => row[2] = input.value);
      url.placeholder = "URL";
      root.append(
        itemRow(cat, desc, url, itemActions("links", index, itemIndex, true))
      );
    });
    root.append(addItemButton("\u0414\u043E\u0431\u0430\u0432\u0438\u0442\u044C URL", () => {
      col.links.push([payload.choices.links.categories[0]?.id || "", "", ""]);
      render();
    }));
    return cell(root);
  }
  function attributionCell(col, index) {
    const root = editableList();
    col.description_attributions.forEach((value, itemIndex) => {
      const input = textInput(value, (input2) => {
        col.description_attributions[itemIndex] = input2.value;
      });
      root.append(
        itemRow(input, itemActions("description_attributions", index, itemIndex, true))
      );
    });
    root.append(addItemButton("\u0414\u043E\u0431\u0430\u0432\u0438\u0442\u044C \u0438\u0441\u0442\u043E\u0447\u043D\u0438\u043A", () => {
      col.description_attributions.push("");
      render();
    }));
    return cell(root);
  }
  function descriptionCell(col) {
    const textarea = el("textarea", { class: "reconcile-description" });
    textarea.value = col.description;
    textarea.addEventListener("input", () => col.description = textarea.value);
    return cell(textarea);
  }
  function itemActions(field, colIndex, itemIndex, allowCopy) {
    const root = el("div", { class: "reconcile-item-actions" });
    root.append(moveButton("\u2190", field, colIndex, itemIndex, -1));
    if (allowCopy) root.append(copyButton("copy \u2190", field, colIndex, itemIndex, -1));
    if (allowCopy) root.append(copyButton("copy \u2192", field, colIndex, itemIndex, 1));
    root.append(moveButton("\u2192", field, colIndex, itemIndex, 1));
    if (field !== "sources") {
      root.append(button("\xD7", () => removeItem(field, colIndex, itemIndex), "reconcile-danger-button"));
    }
    return root;
  }
  function sourceActions(colIndex, itemIndex) {
    const root = itemActions("sources", colIndex, itemIndex, false);
    root.append(
      button("\u043E\u0442\u043A\u0440\u0435\u043F\u0438\u0442\u044C", () => orphanSource(colIndex, itemIndex), "reconcile-danger-button")
    );
    return root;
  }
  function orphanSource(colIndex, itemIndex) {
    const source = columns[colIndex].sources[itemIndex];
    if (!window.confirm(`\u041E\u0442\u043A\u0440\u0435\u043F\u0438\u0442\u044C \u0438\u0441\u0442\u043E\u0447\u043D\u0438\u043A #${source.id} \u043E\u0442 \u0438\u0441\u0442\u043E\u0440\u0438\u0438?`)) return;
    columns[colIndex].sources.splice(itemIndex, 1);
    orphanSourceIds.add(source.id);
    render();
  }
  function moveButton(label, field, colIndex, itemIndex, direction) {
    const target = colIndex + direction;
    const result = button(label, () => moveItem(field, colIndex, itemIndex, target), "reconcile-secondary-button");
    result.disabled = target < 0 || target >= columns.length;
    return result;
  }
  function copyButton(label, field, colIndex, itemIndex, direction) {
    const target = colIndex + direction;
    const result = button(label, () => copyItem(field, colIndex, itemIndex, target), "reconcile-secondary-button");
    result.disabled = target < 0 || target >= columns.length;
    return result;
  }
  function moveItem(field, from, itemIndex, to) {
    if (to < 0 || to >= columns.length) return;
    const fromList = asList(columns[from], field);
    const [item] = fromList.splice(itemIndex, 1);
    if (field === "sources") orphanSourceIds.delete(item.id);
    asList(columns[to], field).push(item);
    render();
  }
  function copyItem(field, from, itemIndex, to) {
    if (to < 0 || to >= columns.length) return;
    asList(columns[to], field).push(clone(asList(columns[from], field)[itemIndex]));
    render();
  }
  function removeItem(field, colIndex, itemIndex) {
    asList(columns[colIndex], field).splice(itemIndex, 1);
    render();
  }
  function editableList() {
    return el("div", { class: "reconcile-editable-list" });
  }
  function itemRow(...children) {
    return el("div", { class: "reconcile-item-row" }, ...children);
  }
  function addItemButton(label, onClick) {
    return button(label, onClick, "reconcile-add-item-button");
  }
  function select(options, value, onChange) {
    const input = el("select");
    input.append(el("option", { value: "", text: "\u2014" }));
    options.forEach(([id, title]) => input.append(el("option", { value: String(id), text: title })));
    input.value = String(value ?? "");
    input.addEventListener("change", () => onChange(input.value));
    return input;
  }
  function textInput(value, onInput) {
    const input = el("input", { type: "text", value });
    input.addEventListener("input", () => onInput(input));
    return input;
  }
  function tagText(pair) {
    return typeof pair[1] === "number" ? tagById.get(pair[1]) || "" : String(pair[1] || "");
  }
  function tagValue(categoryId, text) {
    const cat = tagCatById.get(categoryId);
    const match = cat?.tags.find((tag) => tag.name === text);
    return match?.id ?? text.trim();
  }
  function authorText(pair) {
    return typeof pair[1] === "number" ? authorById.get(pair[1]) || "" : String(pair[1] || "");
  }
  function blankColumn() {
    return {
      client_id: `new-${nextNewColumn++}`,
      history_id: null,
      game_id: null,
      title: "",
      release_date: "",
      tags: [],
      authors: [],
      links: [],
      description_attributions: [],
      description: "",
      delete: false,
      sources: []
    };
  }
  async function addGameColumn(rawGameId) {
    const gameId = Number(rawGameId);
    if (!Number.isInteger(gameId) || gameId <= 0) {
      window.alert("\u0423\u043A\u0430\u0436\u0438\u0442\u0435 \u043F\u043E\u043B\u043E\u0436\u0438\u0442\u0435\u043B\u044C\u043D\u044B\u0439 id \u0438\u0433\u0440\u044B.");
      return;
    }
    if (columns.some((col) => col.game_id === gameId)) {
      window.alert("\u042D\u0442\u0430 \u0438\u0433\u0440\u0430 \u0443\u0436\u0435 \u043E\u0442\u043A\u0440\u044B\u0442\u0430 \u0432 \u0440\u0435\u0434\u0430\u043A\u0442\u043E\u0440\u0435.");
      return;
    }
    const response = await fetch(gameUrl(gameId), { headers: { "X-Requested-With": "XMLHttpRequest" } });
    if (!response.ok) {
      window.alert("\u041D\u0435 \u0443\u0434\u0430\u043B\u043E\u0441\u044C \u0437\u0430\u0433\u0440\u0443\u0437\u0438\u0442\u044C \u0438\u0433\u0440\u0443.");
      return;
    }
    columns.push(await response.json());
    render();
  }
  function gameUrl(gameId) {
    return app.dataset.gameUrl.replace("/0/", `/${gameId}/`);
  }
  function removeColumn(index) {
    if (columns.length === 1) {
      window.alert("\u041D\u0435\u043B\u044C\u0437\u044F \u0443\u0431\u0440\u0430\u0442\u044C \u043F\u043E\u0441\u043B\u0435\u0434\u043D\u044E\u044E \u043A\u043E\u043B\u043E\u043D\u043A\u0443.");
      return;
    }
    if (!window.confirm("\u0423\u0431\u0440\u0430\u0442\u044C \u043A\u043E\u043B\u043E\u043D\u043A\u0443 \u0438\u0437 \u0440\u0435\u0434\u0430\u043A\u0442\u043E\u0440\u0430? \u0421\u0430\u043C\u0430 \u0438\u0433\u0440\u0430 \u043D\u0435 \u0438\u0437\u043C\u0435\u043D\u0438\u0442\u0441\u044F.")) return;
    columns.splice(index, 1);
    render();
  }
  async function saveReconcile() {
    const error = validationError();
    if (error) {
      window.alert(error);
      return;
    }
    const response = await fetch(window.location.href, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        "X-CSRFToken": csrfInput.value || getCookie("csrftoken")
      },
      body: JSON.stringify({
        columns,
        orphan_source_ids: Array.from(orphanSourceIds)
      })
    });
    const result = await response.json();
    if (!response.ok) {
      window.alert(result.error || "\u041D\u0435 \u0443\u0434\u0430\u043B\u043E\u0441\u044C \u0441\u043E\u0445\u0440\u0430\u043D\u0438\u0442\u044C \u0441\u0432\u0435\u0440\u043A\u0443.");
      return;
    }
    window.location.href = result.redirect;
  }
  function validationError() {
    for (const col of columns) {
      if (col.delete) {
        if (col.sources.length) {
          return "\u041D\u0435\u043B\u044C\u0437\u044F \u0443\u0434\u0430\u043B\u0438\u0442\u044C \u0438\u0433\u0440\u0443 \u0441 \u0438\u0441\u0442\u043E\u0447\u043D\u0438\u043A\u0430\u043C\u0438: \u043F\u0435\u0440\u0435\u043D\u0435\u0441\u0438\u0442\u0435 \u0438\u043B\u0438 \u043E\u0442\u043A\u0440\u0435\u043F\u0438\u0442\u0435 \u0438\u0445.";
        }
        continue;
      }
      const createsOrHasGame = col.game_id || !col.history_id;
      if (createsOrHasGame && !col.title.trim()) {
        return "\u0423 \u043A\u0430\u0436\u0434\u043E\u0439 \u043D\u043E\u0432\u043E\u0439 \u0438\u043B\u0438 \u0441\u0443\u0449\u0435\u0441\u0442\u0432\u0443\u044E\u0449\u0435\u0439 \u0438\u0433\u0440\u044B \u0434\u043E\u043B\u0436\u043D\u043E \u0431\u044B\u0442\u044C \u043D\u0430\u0437\u0432\u0430\u043D\u0438\u0435.";
      }
    }
    return null;
  }
  function datalists() {
    const root = el("div");
    root.append(
      el(
        "datalist",
        { id: "reconcile-authors" },
        ...payload.choices.authors.authors.map((author) => el("option", { value: author.name }))
      )
    );
    payload.choices.tags.categories.forEach((cat) => {
      root.append(
        el(
          "datalist",
          { id: `reconcile-tags-${cat.id}` },
          ...cat.tags.map((tag) => el("option", { value: tag.name }))
        )
      );
    });
    return root;
  }
  function button(label, onClick, cls = "") {
    const btn = el("button", { type: "button", class: cls, text: label });
    btn.addEventListener("click", onClick);
    return btn;
  }
  function link(href, text) {
    return el("a", { href, text });
  }
  document.addEventListener("DOMContentLoaded", render);
})();
