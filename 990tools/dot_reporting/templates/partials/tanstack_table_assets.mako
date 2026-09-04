<%doc>
Shared TanStack Table (headless) assets.
Mount targets:
  window.__CLUSTER_TABLE__ + #ts-table-root  (index pages)
  window.__TS_TABLES__ = [{ rootId, rows, columns, pageSize, initialSort }, ...]
Note: do not use ## comments inside <%text> — they are emitted literally.
</%doc>
<%text>
<style>
  .ts-wrap { margin: 0.5rem 0 1rem; }
  .ts-toolbar {
    display: flex; flex-wrap: wrap; gap: 0.75rem; align-items: center;
    margin-bottom: 0.5rem; font-size: 0.9rem;
  }
  .ts-toolbar input[type="search"] {
    min-width: 200px; padding: 0.35rem 0.55rem; border: 1px solid #ccc; border-radius: 4px;
  }
  .ts-toolbar select { padding: 0.3rem 0.4rem; }
  .ts-pager { display: flex; gap: 0.4rem; align-items: center; margin-left: auto; }
  .ts-pager button {
    padding: 0.25rem 0.55rem; border: 1px solid #ccc; background: #fff;
    border-radius: 4px; cursor: pointer;
  }
  .ts-pager button:disabled { opacity: 0.4; cursor: default; }
  .ts-table-root table,
  #ts-table-root table { width: 100%; border-collapse: collapse; font-size: 0.88rem; }
  .ts-table-root th, .ts-table-root td,
  #ts-table-root th, #ts-table-root td {
    border: 1px solid #ddd; padding: 0.45rem 0.55rem; text-align: left; vertical-align: top;
  }
  .ts-table-root th,
  #ts-table-root th {
    background: #f4f4f4; position: sticky; top: 0; cursor: pointer; user-select: none;
    white-space: nowrap;
  }
  .ts-table-root th .sort-ind,
  #ts-table-root th .sort-ind { color: #888; font-size: 0.75rem; margin-left: 0.25rem; }
  .ts-table-root th.sorted,
  #ts-table-root th.sorted { background: #e8f0fe; }
  .ts-table-root tr:nth-child(even),
  #ts-table-root tr:nth-child(even) { background: #fafafa; }
  .ts-table-root tr.dot-heavy,
  #ts-table-root tr.dot-heavy { background: #fff4e5 !important; }
  .ts-table-root tr.sus-row,
  #ts-table-root tr.sus-row { background: #fee2e2 !important; }
  .ts-meta { font-size: 0.85rem; color: #666; }
  .ts-empty { color: #888; font-size: 0.9rem; padding: 0.5rem 0; }
  button.ts-filter-phone {
    border: none; background: none; padding: 0; margin: 0;
    color: #0b57d0; font: inherit; font-weight: 600; cursor: pointer;
    text-decoration: none;
  }
  button.ts-filter-phone:hover { text-decoration: underline; }
</style>
<script type="module">
import {
  createTable,
  getCoreRowModel,
  getSortedRowModel,
  getFilteredRowModel,
  getPaginationRowModel,
} from "https://cdn.jsdelivr.net/npm/@tanstack/table-core@8.20.5/+esm";

function num(v) {
  if (v == null || v === "" || v === "—") return null;
  if (typeof v === "number") return v;
  const n = Number(String(v).replace(/[$,]/g, ""));
  return Number.isFinite(n) ? n : null;
}

function cmp(a, b) {
  const na = num(a), nb = num(b);
  if (na != null && nb != null) return na === nb ? 0 : na < nb ? -1 : 1;
  const sa = (a == null ? "" : String(a)).toLowerCase();
  const sb = (b == null ? "" : String(b)).toLowerCase();
  return sa < sb ? -1 : sa > sb ? 1 : 0;
}

function buildColumns(colDefs) {
  return colDefs.map((c) => ({
    id: c.id,
    accessorKey: c.id,
    header: c.header,
    enableSorting: c.sortable !== false,
    cell: (info) => info.getValue(),
    sortingFn: (rowA, rowB, columnId) =>
      cmp(rowA.getValue(columnId), rowB.getValue(columnId)),
  }));
}

function renderCellHtml(colId, row, raw) {
  if (colId.endsWith("_html") && raw != null) return String(raw);
  const htmlKey = colId + "_html";
  if (row[htmlKey] != null) return row[htmlKey];
  if (raw == null || raw === "") return "—";
  return escapeHtml(String(raw));
}

function escapeHtml(s) {
  return String(s)
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;");
}

/** Mount one TanStack table into `root` from cfg { rows, columns, pageSize, initialSort }. */
export function mountTanStackTable(root, cfg) {
  if (!root || !cfg || !cfg.rows || !cfg.columns) return;
  if (!cfg.rows.length) {
    root.innerHTML = '<p class="ts-empty">No rows</p>';
    return;
  }

  // Hide legacy static table sibling if marked
  if (cfg.hideLegacyId) {
    const legacy = document.getElementById(cfg.hideLegacyId);
    if (legacy) legacy.style.display = "none";
  }

  let sorting = Array.isArray(cfg.initialSort) ? cfg.initialSort.slice() : [];
  let globalFilter = "";
  let pagination = {
    pageIndex: 0,
    pageSize: cfg.pageSize || 25,
  };
  const enableReviewFilter = !!cfg.enableReviewFilter;
  const columns = buildColumns(cfg.columns);

  // External filter API (phone stack → carriers table)
  root.__tsApi = {
    setFilter(q) {
      globalFilter = q == null ? "" : String(q);
      pagination = { ...pagination, pageIndex: 0 };
      redraw();
    },
    getFilter() {
      return globalFilter;
    },
  };

  function tableState() {
    return {
      sorting,
      globalFilter,
      pagination,
      columnFilters: [],
      columnVisibility: {},
      columnOrder: [],
      columnPinning: { left: [], right: [] },
      rowPinning: { top: [], bottom: [] },
      columnSizing: {},
      columnSizingInfo: {
        startOffset: null,
        startSize: null,
        deltaOffset: null,
        deltaPercentage: null,
        isResizingColumn: false,
        columnSizingStart: [],
      },
      rowSelection: {},
      expanded: {},
      grouping: [],
    };
  }

  function makeTable() {
    return createTable({
      data: cfg.rows,
      columns,
      state: tableState(),
      onSortingChange: (updater) => {
        sorting = typeof updater === "function" ? updater(sorting) : updater;
        redraw();
      },
      onGlobalFilterChange: (updater) => {
        globalFilter = typeof updater === "function" ? updater(globalFilter) : updater;
        pagination = { ...pagination, pageIndex: 0 };
        redraw();
      },
      onPaginationChange: (updater) => {
        pagination = typeof updater === "function" ? updater(pagination) : updater;
        redraw();
      },
      getCoreRowModel: getCoreRowModel(),
      getSortedRowModel: getSortedRowModel(),
      getFilteredRowModel: getFilteredRowModel(),
      getPaginationRowModel: getPaginationRowModel(),
      globalFilterFn: (row, _columnId, filterValue) => {
        if (!filterValue) return true;
        const q = String(filterValue).toLowerCase();
        return Object.keys(row.original).some((k) => {
          if (k.endsWith("_html")) return false;
          const v = row.original[k];
          return v != null && String(v).toLowerCase().includes(q);
        });
      },
    });
  }

  function redraw() {
    const table = makeTable();
    const reviewMode = enableReviewFilter
      ? window.__TS_REVIEW_FILTER__ || "all"
      : "all";
    let pageRows = table.getRowModel().rows;
    if (reviewMode !== "all" && typeof window.getStatus === "function") {
      pageRows = table.getPrePaginationRowModel().rows.filter((r) => {
        const slug = r.original.slug || "";
        const status = window.getStatus(slug);
        if (reviewMode === "sus")
          return status === "sus-dot" || status === "sus-ins" || status === "sus";
        if (reviewMode === "sus-dot") return status === "sus-dot";
        if (reviewMode === "sus-ins") return status === "sus-ins";
        if (reviewMode === "not") return status === "not";
        if (reviewMode === "unreviewed") return !status;
        return true;
      });
      const start = pagination.pageIndex * pagination.pageSize;
      render(table, pageRows.slice(start, start + pagination.pageSize), pageRows.length);
      return;
    }
    render(table, pageRows, table.getFilteredRowModel().rows.length);
  }

  function render(table, rows, filteredCount) {
    const sortMap = Object.fromEntries(
      (table.getState().sorting || []).map((s) => [s.id, s.desc ? "desc" : "asc"])
    );
    const leafCols = table.getAllLeafColumns();
    const headerCells = leafCols
      .map((col) => {
        const id = col.id;
        const sorted = sortMap[id];
        const ind = sorted === "asc" ? "▲" : sorted === "desc" ? "▼" : "⇅";
        const cls = sorted ? "sorted" : "";
        const label = col.columnDef.header;
        return `<th class="${cls}" data-col="${escapeHtml(id)}">${escapeHtml(String(label))}<span class="sort-ind">${ind}</span></th>`;
      })
      .join("");

    const body = rows
      .map((r) => {
        const o = r.original;
        const heavy = o.dot_heavy ? "dot-heavy" : "";
        const tds = leafCols
          .map((col) => {
            const id = col.id;
            return `<td>${renderCellHtml(id, o, o[id])}</td>`;
          })
          .join("");
        return `<tr class="${heavy}" data-slug="${escapeHtml(o.slug || "")}" data-phy-po-box="${o.phy_po_box ? "true" : "false"}" data-has-physical="${o.has_physical ? "true" : "false"}">${tds}</tr>`;
      })
      .join("");

    const pageCount = Math.max(1, Math.ceil(filteredCount / pagination.pageSize) || 1);
    const pageIndex = pagination.pageIndex;
    const sizes = cfg.pageSizeOptions || [10, 25, 50, 100, 200];

    root.innerHTML = `
      <div class="ts-wrap">
        <div class="ts-toolbar">
          <label>Search <input type="search" class="ts-search" placeholder="Filter rows…" value="${escapeHtml(globalFilter)}"></label>
          <label>Page size
            <select class="ts-page-size">
              ${sizes.map((n) => `<option value="${n}" ${n === pagination.pageSize ? "selected" : ""}>${n}</option>`).join("")}
            </select>
          </label>
          <span class="ts-meta">${filteredCount} rows · page ${pageIndex + 1}/${pageCount}</span>
          <div class="ts-pager">
            <button type="button" class="ts-first" ${pageIndex <= 0 ? "disabled" : ""}>«</button>
            <button type="button" class="ts-prev" ${pageIndex <= 0 ? "disabled" : ""}>‹</button>
            <button type="button" class="ts-next" ${pageIndex >= pageCount - 1 ? "disabled" : ""}>›</button>
            <button type="button" class="ts-last" ${pageIndex >= pageCount - 1 ? "disabled" : ""}>»</button>
          </div>
        </div>
        <table>
          <thead><tr>${headerCells}</tr></thead>
          <tbody>${body}</tbody>
        </table>
      </div>`;

    root.querySelectorAll("th[data-col]").forEach((th) => {
      th.addEventListener("click", () => {
        const id = th.getAttribute("data-col");
        const cur = sorting.find((s) => s.id === id);
        if (!cur) sorting = [{ id, desc: true }];
        else if (cur.desc) sorting = [{ id, desc: false }];
        else sorting = [];
        redraw();
      });
    });
    const search = root.querySelector(".ts-search");
    search.addEventListener("input", () => {
      globalFilter = search.value;
      pagination = { ...pagination, pageIndex: 0 };
      redraw();
    });
    root.querySelector(".ts-page-size").addEventListener("change", (e) => {
      pagination = { pageIndex: 0, pageSize: Number(e.target.value) || 25 };
      redraw();
    });
    root.querySelector(".ts-first").addEventListener("click", () => {
      pagination = { ...pagination, pageIndex: 0 };
      redraw();
    });
    root.querySelector(".ts-prev").addEventListener("click", () => {
      pagination = { ...pagination, pageIndex: Math.max(0, pagination.pageIndex - 1) };
      redraw();
    });
    root.querySelector(".ts-next").addEventListener("click", () => {
      pagination = { ...pagination, pageIndex: pagination.pageIndex + 1 };
      redraw();
    });
    root.querySelector(".ts-last").addEventListener("click", () => {
      pagination = { ...pagination, pageIndex: Math.max(0, pageCount - 1) };
      redraw();
    });

    if (typeof window.applyReviewState === "function" && enableReviewFilter) {
      window.applyReviewState();
    }
  }

  if (enableReviewFilter) {
    window.__TS_REDRAW__ = redraw;
    const origFilter = window.filterRows;
    window.filterRows = function (mode) {
      window.__TS_REVIEW_FILTER__ = mode;
      if (typeof origFilter === "function") {
        try {
          origFilter(mode);
        } catch (_) {}
      }
      pagination = { ...pagination, pageIndex: 0 };
      redraw();
    };
  }

  redraw();
}

function boot() {
  // Index-style single table
  if (window.__CLUSTER_TABLE__) {
    const root =
      document.getElementById("ts-table-root") ||
      document.querySelector(".ts-table-root");
    if (root) {
      const cfg = { ...window.__CLUSTER_TABLE__, enableReviewFilter: true, hideLegacyId: "clusters-table" };
      mountTanStackTable(root, cfg);
    }
  }
  // Detail-style multi tables
  const multi = window.__TS_TABLES__;
  if (Array.isArray(multi)) {
    multi.forEach((cfg) => {
      if (!cfg) return;
      const id = cfg.rootId || cfg.id;
      const root = id ? document.getElementById(id) : null;
      if (root) mountTanStackTable(root, cfg);
    });
  }
  // Phone stack → filter carriers table (classic shell breakout UX)
  if (!window.__TS_PHONE_FILTER_BOUND__) {
    window.__TS_PHONE_FILTER_BOUND__ = true;
    document.addEventListener("click", (e) => {
      const btn = e.target && e.target.closest && e.target.closest("button.ts-filter-phone");
      if (!btn) return;
      e.preventDefault();
      const phone = btn.getAttribute("data-phone") || "";
      const targetId = btn.getAttribute("data-target") || "ts-carriers";
      const target = document.getElementById(targetId);
      if (target && target.__tsApi && typeof target.__tsApi.setFilter === "function") {
        target.__tsApi.setFilter(phone);
        target.scrollIntoView({ behavior: "smooth", block: "start" });
      }
    });
  }
  // data-ts-config elements: <div id="x" class="ts-table-root" data-ts-config='...'></div>
  document.querySelectorAll("[data-ts-config]").forEach((el) => {
    try {
      const cfg = JSON.parse(el.getAttribute("data-ts-config"));
      mountTanStackTable(el, cfg);
    } catch (e) {
      console.warn("TanStack data-ts-config parse failed", e);
    }
  });
}

if (document.readyState === "loading") {
  document.addEventListener("DOMContentLoaded", boot);
} else {
  boot();
}

// Expose for ad-hoc use
window.mountTanStackTable = mountTanStackTable;
</script>

</%text>
