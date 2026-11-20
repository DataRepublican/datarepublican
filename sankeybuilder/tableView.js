import { edgeKindChoices, formatEin, isPartnerKind, normalizeEdgeKind } from "./schema.js";
import {
  createTable,
  getCoreRowModel,
  getSortedRowModel,
} from "https://cdn.jsdelivr.net/npm/@tanstack/table-core@8.20.5/+esm";

function esc(s) {
  return String(s ?? "")
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;");
}

function nodeOptions(vm, selected) {
  return vm.doc.nodes
    .map(
      (n) =>
        `<option value="${esc(n.id)}" ${n.id === selected ? "selected" : ""}>${esc(n.name)}</option>`,
    )
    .join("");
}

function cmp(a, b) {
  if (a == null && b == null) return 0;
  if (a == null) return -1;
  if (b == null) return 1;
  if (typeof a === "number" && typeof b === "number") return a - b;
  const sa = String(a).toLowerCase();
  const sb = String(b).toLowerCase();
  return sa < sb ? -1 : sa > sb ? 1 : 0;
}

function sortingFn(rowA, rowB, columnId) {
  return cmp(rowA.getValue(columnId), rowB.getValue(columnId));
}

function filteredNodes(vm) {
  const q = vm.searchQuery.trim().toLowerCase();
  let nodes = vm.doc.nodes.slice();
  if (!q) return nodes;
  const digits = q.replace(/\D/g, "");
  return nodes.filter(
    (n) =>
      n.name.toLowerCase().includes(q) ||
      n.id.toLowerCase().includes(q) ||
      (n.ein && digits && n.ein.includes(digits)),
  );
}

function filteredEdges(vm, nodes) {
  const q = vm.searchQuery.trim().toLowerCase();
  const idSet = new Set(nodes.map((n) => n.id));
  let edges = vm.doc.edges.slice();
  if (!q) return edges;
  return edges.filter((e) => {
    if (idSet.has(e.from) || idSet.has(e.to)) return true;
    const a = vm.doc.node(e.from);
    const b = vm.doc.node(e.to);
    return (
      (a && a.name.toLowerCase().includes(q)) ||
      (b && b.name.toLowerCase().includes(q)) ||
      (e.label && e.label.toLowerCase().includes(q))
    );
  });
}

function makeTable(rows, columns, sorting, onSortingChange) {
  return createTable({
    data: rows,
    columns,
    state: { sorting },
    onSortingChange,
    getCoreRowModel: getCoreRowModel(),
    getSortedRowModel: getSortedRowModel(),
    getRowId: (row) => row.id,
  });
}

export function bindTable(host, vm) {
  let nodeSort = [{ id: "name", desc: false }];
  let edgeSort = [{ id: "fromName", desc: false }];

  host.addEventListener("click", (ev) => {
    const th = ev.target.closest("th[data-col]");
    if (th) {
      const sheet = th.closest("table")?.dataset.sheet;
      const id = th.getAttribute("data-col");
      const sort = sheet === "edges" ? edgeSort : nodeSort;
      const cur = sort[0];
      const next =
        cur && cur.id === id
          ? [{ id, desc: !cur.desc }]
          : [{ id, desc: false }];
      if (sheet === "edges") edgeSort = next;
      else nodeSort = next;
      render();
      return;
    }
    const trNode = ev.target.closest("tr[data-node]");
    if (trNode && !ev.target.closest("input, select, button")) {
      vm.setSelected(trNode.getAttribute("data-node"));
      return;
    }
    const addNode = ev.target.closest("[data-add-node]");
    if (addNode) {
      const node = vm.addEmptyNode();
      render();
      focusRow("node", node?.id, "name");
      return;
    }
    const addEdge = ev.target.closest("[data-add-edge]");
    if (addEdge) {
      const edge = vm.addEmptyEdge();
      render();
      focusRow("edge", edge?.id, "amount");
      return;
    }
    const trEdge = ev.target.closest("tr[data-edge]");
    if (trEdge && !ev.target.closest("input, select, button")) {
      vm.setSelectedEdge(trEdge.getAttribute("data-edge"));
    }
  });

  host.addEventListener("change", (ev) => {
    const trNode = ev.target.closest("tr[data-node]");
    if (trNode) {
      const id = trNode.getAttribute("data-node");
      const existing = vm.doc.node(id);
      if (!existing) return;
      vm.upsertNode({
        id,
        name: trNode.querySelector('[name="name"]')?.value,
        kind: trNode.querySelector('[name="kind"]')?.value,
        ein: trNode.querySelector('[name="ein"]')?.value,
        starting: trNode.querySelector('[name="starting"]')?.checked,
        govFunds: trNode.querySelector('[name="govFunds"]')?.value,
        photo: existing.photo,
        inspector: existing.inspector,
      });
      return;
    }
    const trEdge = ev.target.closest("tr[data-edge]");
    if (trEdge) {
      const id = trEdge.getAttribute("data-edge");
      const existing = vm.doc.edge(id);
      if (!existing) return;
      let kind = normalizeEdgeKind(
        trEdge.querySelector('[name="kind"]')?.value || existing.kind,
      );
      const amountRaw = trEdge.querySelector('[name="amount"]')?.value;
      let amount = Number(amountRaw) || 0;
      if (amount > 0 && isPartnerKind(kind)) kind = "grant";
      if (isPartnerKind(kind)) amount = 0;
      vm.upsertEdge({
        id,
        from: trEdge.querySelector('[name="from"]')?.value,
        to: trEdge.querySelector('[name="to"]')?.value,
        kind,
        amount,
        label: trEdge.querySelector('[name="label"]')?.value,
        cite: existing.cite,
        years: existing.years,
      });
    }
  });

  function nodeRowsHtml(table) {
    return table
      .getRowModel()
      .rows.map((r) => {
        const n = r.original;
        const on = n.id === vm.selectedId;
        return `<tr data-node="${esc(n.id)}" aria-selected="${on ? "true" : "false"}">
          <td><input name="name" value="${esc(n.name)}" aria-label="Name"></td>
          <td><select name="kind" aria-label="Kind">
            <option value="org" ${n.kind === "org" ? "selected" : ""}>org</option>
            <option value="person" ${n.kind === "person" ? "selected" : ""}>person</option>
            <option value="gov" ${n.kind === "gov" ? "selected" : ""}>gov</option>
          </select></td>
          <td><input name="ein" value="${esc(formatEin(n.ein))}" placeholder="—" aria-label="EIN"></td>
          <td><input type="checkbox" name="starting" ${n.starting ? "checked" : ""} aria-label="Starting set"></td>
          <td class="sb-num"><input name="govFunds" inputmode="decimal" value="${n.govFunds || ""}" aria-label="Government funds"></td>
        </tr>`;
      })
      .join("");
  }

  function edgeRowsHtml(table) {
    return table
      .getRowModel()
      .rows.map((r) => {
        const e = r.original;
        const on = e.id === vm.selectedEdgeId;
        return `<tr data-edge="${esc(e.id)}" aria-selected="${on ? "true" : "false"}">
          <td><select name="from" aria-label="From">${nodeOptions(vm, e.from)}</select></td>
          <td><select name="to" aria-label="To">${nodeOptions(vm, e.to)}</select></td>
          <td><select name="kind" aria-label="Kind">
            ${edgeKindChoices(e.kind)
              .map(
                (o) =>
                  `<option value="${esc(o.value)}" ${o.value === normalizeEdgeKind(e.kind) ? "selected" : ""}>${esc(o.value)}</option>`,
              )
              .join("")}
          </select></td>
          <td class="sb-num"><input name="amount" inputmode="decimal" value="${!isPartnerKind(e.kind) && e.amount ? e.amount : ""}" placeholder="${isPartnerKind(e.kind) ? "—" : "0"}" aria-label="Amount"></td>
          <td><input name="label" value="${esc(e.label)}" aria-label="Label"></td>
        </tr>`;
      })
      .join("");
  }

  function headerHtml(table) {
    const sort = (table.getState().sorting || [])[0];
    return table
      .getAllLeafColumns()
      .map((col) => {
        const id = col.id;
        const dir = sort && sort.id === id ? (sort.desc ? "desc" : "asc") : "";
        const ind = dir === "asc" ? "▲" : dir === "desc" ? "▼" : "⇅";
        return `<th data-col="${esc(id)}" aria-sort="${dir || "none"}">${esc(col.columnDef.header)}<span class="sb-sort-ind">${ind}</span></th>`;
      })
      .join("");
  }

  function render() {
    if (vm.view !== "table") {
      host.hidden = true;
      return;
    }
    host.hidden = false;
    const nodes = filteredNodes(vm);
    const edges = filteredEdges(vm, nodes).map((e) => ({
      ...e,
      fromName: vm.doc.node(e.from)?.name || e.from,
      toName: vm.doc.node(e.to)?.name || e.to,
    }));
    const hiddenN = vm.hidden.size;

    const nodeTable = makeTable(
      nodes,
      [
        { id: "name", accessorKey: "name", header: "Name", sortingFn },
        { id: "kind", accessorKey: "kind", header: "Kind", sortingFn },
        { id: "ein", accessorKey: "ein", header: "EIN", sortingFn },
        { id: "starting", accessorKey: "starting", header: "Start", sortingFn },
        { id: "govFunds", accessorKey: "govFunds", header: "Gov $", sortingFn },
      ],
      nodeSort,
      (updater) => {
        nodeSort = typeof updater === "function" ? updater(nodeSort) : updater;
        render();
      },
    );

    const edgeTable = makeTable(
      edges,
      [
        { id: "fromName", accessorKey: "fromName", header: "From", sortingFn },
        { id: "toName", accessorKey: "toName", header: "To", sortingFn },
        { id: "kind", accessorKey: "kind", header: "Kind", sortingFn },
        { id: "amount", accessorKey: "amount", header: "Amount", sortingFn },
        { id: "label", accessorKey: "label", header: "Label", sortingFn },
      ],
      edgeSort,
      (updater) => {
        edgeSort = typeof updater === "function" ? updater(edgeSort) : updater;
        render();
      },
    );

    host.innerHTML = `
      <div class="sb-table-toolbar">
        <p class="sb-lede">${vm.doc.nodes.length} organizations and people · ${vm.doc.edges.length} flows. Dashed on the diagram is a <strong>partner</strong> (no dollars). Grants carry an amount. A Gov $ amount adds an implied U.S. government node.</p>
        ${
          hiddenN
            ? `<button type="button" class="dr-btn" data-reveal-all>Show all ${hiddenN} hidden on the diagram</button>`
            : ""
        }
      </div>
      <div class="sb-sheet-head">
        <h2>Organizations and people</h2>
        <button type="button" class="dr-btn" data-add-node>Add row</button>
      </div>
      <div class="sb-table-wrap">
        <table data-sheet="nodes" id="sb-nodes-table">
          <thead><tr>${headerHtml(nodeTable)}</tr></thead>
          <tbody>${nodeRowsHtml(nodeTable)}</tbody>
        </table>
      </div>
      <div class="sb-sheet-head">
        <h2>Flows</h2>
        <button type="button" class="dr-btn" data-add-edge>Add row</button>
      </div>
      <div class="sb-table-wrap">
        <table data-sheet="edges" id="sb-edges-table">
          <thead><tr>${headerHtml(edgeTable)}</tr></thead>
          <tbody>${edgeRowsHtml(edgeTable)}</tbody>
        </table>
      </div>
    `;
    host.querySelector("[data-reveal-all]")?.addEventListener("click", () => vm.revealAll());
  }

  function focusRow(kind, id, field) {
    if (!id) return;
    const attr = kind === "edge" ? "data-edge" : "data-node";
    const input = host.querySelector(
      `tr[${attr}="${CSS.escape(id)}"] [name="${field}"]`,
    );
    if (!input) return;
    input.focus();
    if (typeof input.select === "function") input.select();
  }

  vm.subscribe(render);
  render();
}
