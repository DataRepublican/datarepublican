import { extractGrokHref } from "./models.js";
import { formatEin } from "./schema.js";
import { bindSankey } from "./sankeyView.js";
import { bindTable } from "./tableView.js";

function esc(s) {
  return String(s ?? "")
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;");
}

function moneyInput(n) {
  return n ? String(n) : "";
}

const ICONS = {
  plus: '<path d="M5 12h14"/><path d="M12 5v14"/>',
  minus: '<path d="M5 12h14"/>',
  maximize:
    '<path d="M8 3H5a2 2 0 0 0-2 2v3"/><path d="M21 8V5a2 2 0 0 0-2-2h-3"/><path d="M3 16v3a2 2 0 0 0 2 2h3"/><path d="M16 21h3a2 2 0 0 0 2-2v-3"/>',
  chevronsUp: '<path d="m17 11-5-5-5 5"/><path d="m17 18-5-5-5 5"/>',
  chevronsDown: '<path d="m7 6 5 5 5-5"/><path d="m7 13 5 5 5-5"/>',
  rotateCcw:
    '<path d="M3 12a9 9 0 1 0 9-9 9.75 9.75 0 0 0-6.74 2.74L3 8"/><path d="M3 3v5h5"/>',
  pointer:
    '<path d="M12.586 12.586 19 19"/><path d="M3.688 3.037a.497.497 0 0 0-.651.651l6.5 16a.5.5 0 0 0 .947-.063L12.586 12.586l7.04-2.102a.5.5 0 0 0 .063-.947z"/>',
  scan:
    '<path d="M3 7V5a2 2 0 0 1 2-2h2"/><path d="M17 3h2a2 2 0 0 1 2 2v2"/><path d="M21 17v2a2 2 0 0 1-2 2h-2"/><path d="M7 21H5a2 2 0 0 1-2-2v-2"/>',
  x: '<path d="M18 6 6 18"/><path d="m6 6 12 12"/>',
  search: '<circle cx="11" cy="11" r="8"/><path d="m21 21-4.3-4.3"/>',
};

const MODE_TIPS = {
  focus:
    "Clicking a node shows only that node and its direct ties, so you can follow the graph one node at a time.",
  zoom: "Clicking a node frames it and one hop of ties. The rest of the graph stays; only the camera moves.",
  add: "Clicking a node keeps the graph and reveals its neighbors both ways. ⌘ or Ctrl does the same from any mode.",
  subtract: "Clicking a node hides it. Shift-click does the same from any mode.",
  inspect: "Clicking a node or flow opens the editor even if it is hidden, without changing who is visible. Alt or Option does the same from any mode.",
};

function iconBtn(id, name, tip, glyph) {
  return `<button type="button" class="sb-tool" id="${id}"
    aria-label="${esc(name)}" data-tip-title="${esc(name)}" data-tip="${esc(tip)}">
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"
         stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">${glyph}</svg>
  </button>`;
}

function iconMode(mode, name, tip, glyph) {
  return `<button type="button" class="sb-tool sb-tool--mode" data-mode="${mode}"
    role="radio" aria-checked="false" aria-pressed="false"
    aria-label="${esc(name)}" data-tip-title="${esc(name)}" data-tip="${esc(tip)}">
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"
         stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">${glyph}</svg>
  </button>`;
}

export function bindView(root, vm) {
  const header = root.querySelector("#sb-header");
  const stage = root.querySelector("#sb-stage");
  const canvas = root.querySelector("#sb-canvas");
  const svg = root.querySelector("#sb-svg");
  const table = root.querySelector("#sb-table");
  const panel = root.querySelector("#sb-panel");
  const viewDiagram = root.querySelector("#sb-view-diagram");
  const viewTable = root.querySelector("#sb-view-table");
  const viewEditor = root.querySelector("#sb-view-editor");
  const viewControls = root.querySelector("#sb-view-controls");
  const status = root.querySelector("#sb-status");
  const err = root.querySelector("#sb-error");
  const fileInput = document.getElementById("sb-file");
  const urlInput = document.getElementById("sb-url");
  const legal = document.getElementById("sb-legal");
  const legalOpen = root.querySelector("#sb-legal-open");
  const paste = document.getElementById("sb-paste");
  const pasteOpen = root.querySelector("#sb-paste-open");
  const pasteForm = document.getElementById("sb-paste-form");
  const pasteText = document.getElementById("sb-paste-text");
  const pasteErr = document.getElementById("sb-paste-error");
  const loadDlg = document.getElementById("sb-load");
  const loadForm = document.getElementById("sb-load-form");
  const loadErr = document.getElementById("sb-load-error");

  canvas.querySelector("#sb-controls").innerHTML = `
    <div class="sb-ctrl-row">
      ${iconBtn("sb-zoom-in", "Zoom in", "Zoom in.", ICONS.plus)}
      ${iconBtn("sb-zoom-out", "Zoom out", "Zoom out.", ICONS.minus)}
      ${iconBtn("sb-zoom-fit", "Reset view", "Fit the whole graph in the canvas.", ICONS.maximize)}
    </div>
    <div class="sb-ctrl-row">
      ${iconBtn("sb-scale-up", "Expand flows", "Make the flows taller so overlapping labels have more room.", ICONS.chevronsUp)}
      ${iconBtn("sb-scale-down", "Compact flows", "Pack the flows tighter so more of the graph fits.", ICONS.chevronsDown)}
      ${iconBtn("sb-scale-reset", "Reset flow scale", "Back to the default flow spacing.", ICONS.rotateCcw)}
    </div>
    <div class="sb-ctrl-row" id="sb-click-mode" role="radiogroup" aria-label="Click mode">
      ${iconMode("focus", "Focus", MODE_TIPS.focus, ICONS.pointer)}
      ${iconMode("zoom", "Zoom", MODE_TIPS.zoom, ICONS.scan)}
      ${iconMode("add", "Expand", MODE_TIPS.add, ICONS.plus)}
      ${iconMode("subtract", "Hide", MODE_TIPS.subtract, ICONS.x)}
      ${iconMode("inspect", "Inspect", MODE_TIPS.inspect, ICONS.search)}
    </div>
    <div class="sb-circular" title="Looping grant flows">
      <span class="sb-circular-label">Show<br>circular</span>
      <div class="sb-switch">
        <input type="checkbox" id="sb-circular" aria-label="Hide circular flows">
        <label for="sb-circular"></label>
      </div>
      <span class="sb-circular-label">Hide<br>circular</span>
    </div>`;

  const sankey = bindSankey(svg, vm);
  if (table) bindTable(table, vm);

  canvas.querySelector("#sb-zoom-in").addEventListener("click", () => sankey.zoomBy(1.3));
  canvas.querySelector("#sb-zoom-out").addEventListener("click", () => sankey.zoomBy(0.7));
  canvas.querySelector("#sb-zoom-fit").addEventListener("click", () => sankey.fit());
  canvas.querySelector("#sb-scale-up").addEventListener("click", () => vm.scaleUp());
  canvas.querySelector("#sb-scale-down").addEventListener("click", () => vm.scaleDown());
  canvas.querySelector("#sb-scale-reset").addEventListener("click", () => vm.scaleReset());
  canvas.querySelector("#sb-click-mode").addEventListener("click", (ev) => {
    const btn = ev.target.closest("[data-mode]");
    if (btn) vm.setClickMode(btn.getAttribute("data-mode"));
  });
  const circular = canvas.querySelector("#sb-circular");
  circular?.addEventListener("change", () => {
    vm.setCircularLinks(!circular.checked);
  });

  legalOpen?.addEventListener("click", (e) => {
    e.preventDefault();
    legal?.showModal();
  });
  legal?.querySelector("[data-close]")?.addEventListener("click", () => legal.close());

  pasteOpen?.addEventListener("click", () => {
    if (pasteErr) {
      pasteErr.hidden = true;
      pasteErr.textContent = "";
    }
    paste?.showModal();
    pasteText?.focus();
  });
  paste?.querySelector("[data-close]")?.addEventListener("click", () => paste.close());
  pasteForm?.addEventListener("submit", (e) => {
    e.preventDefault();
    const t = pasteText?.value || "";
    if (!t.trim()) return;
    const ok = vm.loadJSON(t);
    if (ok) {
      if (pasteText) pasteText.value = "";
      paste?.close();
      return;
    }
    if (pasteErr) {
      pasteErr.hidden = false;
      pasteErr.textContent = vm.error || "JSON is not valid";
    }
  });

  const newBtn = root.querySelector("#sb-new");
  newBtn?.addEventListener("click", () => vm.newDocument());
  root.querySelector("#sb-save")?.addEventListener("click", () => download(vm));
  root.querySelector("#sb-save-svg")?.addEventListener("click", () => downloadSvg(vm));
  root.querySelector("#sb-open")?.addEventListener("click", () => fileInput?.click());
  const shareBtn = root.querySelector("#sb-share");
  shareBtn?.addEventListener("click", async () => {
    const token = vm.writeFragment();
    if (!token) return;
    try {
      await navigator.clipboard.writeText(location.href);
    } catch {
      /* hash is already in the address bar */
    }
    const prev = shareBtn.textContent;
    shareBtn.textContent = "Copied to clipboard";
    window.setTimeout(() => {
      if (shareBtn.textContent === "Copied to clipboard") shareBtn.textContent = prev;
    }, 2000);
  });
  root.querySelector("#sb-load-url")?.addEventListener("click", () => {
    if (loadErr) {
      loadErr.hidden = true;
      loadErr.textContent = "";
    }
    loadDlg?.showModal();
    urlInput?.focus();
  });
  loadDlg?.querySelector("[data-close]")?.addEventListener("click", () => loadDlg.close());
  loadForm?.addEventListener("submit", async (e) => {
    e.preventDefault();
    const u = urlInput?.value.trim();
    if (!u) return;
    const ok = await vm.loadFromUrl(u);
    if (ok) {
      if (urlInput) urlInput.value = "";
      loadDlg?.close();
      return;
    }
    if (loadErr) {
      loadErr.hidden = false;
      loadErr.textContent = vm.error || "Could not load that URL";
    }
  });
  const postUrl = root.querySelector("#sb-post-url");
  root.querySelector("#sb-extract-post")?.addEventListener("click", () => {
    const href = extractGrokHref(postUrl?.value || "");
    if (!href) {
      vm.setError("Paste a post or article URL first.");
      postUrl?.focus();
      return;
    }
    vm.setError("");
    window.open(href, "_blank", "noopener,noreferrer");
  });
  viewDiagram?.addEventListener("click", () => vm.setView("diagram"));
  viewTable?.addEventListener("click", () => vm.setView("table"));
  viewEditor?.addEventListener("click", () => vm.setEditorOpen(!vm.editorOpen));
  viewControls?.addEventListener("click", () => vm.setControlsOpen(!vm.controlsOpen));

  fileInput?.addEventListener("change", async () => {
    const f = fileInput.files?.[0];
    if (!f) return;
    const text = await f.text();
    vm.loadJSON(text);
    fileInput.value = "";
  });

  let sheet = null;
  if (window.DRSheet) {
    sheet = window.DRSheet.attach(panel, {
      label: "Editor",
      onClose: () => vm.setSelected(null),
    });
  }

  function render() {
    const n = vm.doc.nodes.length;
    const e = vm.doc.edges.length;
    const vis = vm.visibleNodes().length;
    if (status) {
      status.textContent = `${vm.doc.title} · ${vis} of ${n} nodes · ${e} flows`;
    }
    if (err) {
      err.hidden = !vm.error;
      err.textContent = vm.error;
    }
    panel.innerHTML = panelHtml(vm);
    bindPanel(panel, vm);
    root.dataset.view = vm.view;
    root.dataset.editor = vm.editorOpen ? "on" : "off";
    root.dataset.controls = vm.controlsOpen ? "on" : "off";
    viewDiagram?.setAttribute("aria-pressed", String(vm.view === "diagram"));
    viewTable?.setAttribute("aria-pressed", String(vm.view === "table"));
    viewEditor?.setAttribute("aria-pressed", String(vm.editorOpen));
    if (viewEditor) viewEditor.textContent = vm.editorOpen ? "Hide Editor" : "Show Editor";
    viewControls?.setAttribute("aria-pressed", String(vm.controlsOpen));
    if (viewControls) viewControls.textContent = vm.controlsOpen ? "Hide Controls" : "Show Controls";
    if (newBtn) newBtn.textContent = n || e ? "Clear" : "New";
    if (circular) circular.checked = !vm.circularLinks;
    root.querySelectorAll("#sb-click-mode [data-mode]").forEach((btn) => {
      const on = btn.getAttribute("data-mode") === vm.clickMode;
      btn.setAttribute("aria-pressed", String(on));
      btn.setAttribute("aria-checked", String(on));
    });
    if (sheet && window.DRSheet?.isMobile?.()) {
      if (vm.editorOpen && (vm.selectedId || vm.selectedEdgeId)) sheet.open();
      else sheet.close();
    }
  }

  vm.subscribe(render);
  render();
  measure(header, root);
  new ResizeObserver(() => measure(header, root)).observe(header);

  return { sankey };
}

function measure(header, root) {
  const stage = root.querySelector("#sb-stage");
  if (!stage) return;
  let top = 0;
  let el = stage;
  while (el) {
    top += el.offsetTop;
    el = el.offsetParent;
  }
  root.style.setProperty("--sb-stage-top", `${top}px`);
  void header;
}

function download(vm) {
  const blob = new Blob([JSON.stringify(vm.toJSON(), null, 2)], {
    type: "application/json",
  });
  clickDownload(blob, `${slugFile(vm.doc.title)}.json`);
}

function downloadSvg(vm) {
  const svgEl = document.getElementById("sb-svg");
  if (!svgEl || !svgEl.querySelector("g.sb-node")) return;
  const clone = svgEl.cloneNode(true);
  clone.setAttribute("xmlns", "http://www.w3.org/2000/svg");
  clone.setAttribute("xmlns:xlink", "http://www.w3.org/1999/xlink");
  const live = svgEl.querySelector("g.sb-main");
  if (live && typeof live.getBBox === "function") {
    const b = live.getBBox();
    const pad = 24;
    clone.setAttribute(
      "viewBox",
      `${b.x - pad} ${b.y - pad} ${Math.max(1, b.width + pad * 2)} ${Math.max(1, b.height + pad * 2)}`,
    );
    clone.removeAttribute("width");
    clone.removeAttribute("height");
    const main = clone.querySelector("g.sb-main");
    if (main) main.removeAttribute("transform");
  }
  const blob = new Blob([new XMLSerializer().serializeToString(clone)], {
    type: "image/svg+xml;charset=utf-8",
  });
  clickDownload(blob, `${slugFile(vm.doc.title)}.svg`);
}

function clickDownload(blob, name) {
  const a = document.createElement("a");
  a.href = URL.createObjectURL(blob);
  a.download = name;
  a.click();
  URL.revokeObjectURL(a.href);
}

function slugFile(t) {
  return String(t || "graph")
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, "-")
    .replace(/^-+|-+$/g, "")
    .slice(0, 40) || "graph";
}

function panelHtml(vm) {
  const node = vm.selectedNode();
  const edge = vm.selectedEdge();
  return `
    ${edge ? edgeForm(edge, vm) : node ? nodeForm(node, vm) : addForms(vm)}
    ${edge ? "" : edgeList(vm, node)}
  `;
}

function addForms(vm) {
  return `
    <header class="insp-head">
      <p class="insp-kind">Editor</p>
      <h3>Add to the graph</h3>
      <p class="insp-id">Nothing selected. Click a node or a flow, or add one here.</p>
    </header>
    <div class="insp-body">
      ${
        vm.hidden.size
          ? `<div class="insp-actions"><button type="button" class="insp-primary" data-reveal-all>Show all ${vm.hidden.size} hidden</button></div>`
          : ""
      }
      <form id="sb-node-form" class="sb-form">
        <label>Name <input name="name" required maxlength="200" autocomplete="off"></label>
        <label>Kind
          <select name="kind">
            <option value="org">Organization</option>
            <option value="person">Person</option>
            <option value="gov">Government</option>
          </select>
        </label>
        <label>EIN <input name="ein" inputmode="numeric" placeholder="optional, 12-3456789"></label>
        <label>Photo URL <input name="photo" placeholder="people only"></label>
        <label>Government funds ($) <input name="govFunds" inputmode="decimal"></label>
        <label class="sb-check"><input type="checkbox" name="starting" checked> Starting set</label>
        ${inspectorFields(null)}
        <button type="submit" class="insp-primary">Add</button>
      </form>
      <form id="sb-edge-form" class="sb-form">
        <p class="insp-k">Add a flow</p>
        <label>From
          <select name="from">${nodeOptions(vm, "")}</select>
        </label>
        <label>To
          <select name="to">${nodeOptions(vm, "")}</select>
        </label>
        <label>Kind
          <select name="kind">
            <option value="grant">Grant (dollars)</option>
            <option value="partner">Partner (not money)</option>
          </select>
        </label>
        <label>Amount ($) <input name="amount" inputmode="decimal"></label>
        <label>Label <input name="label"></label>
        <label>Cite <input name="cite"></label>
        <button type="submit" class="insp-primary">Add flow</button>
      </form>
    </div>
  `;
}

function nodeForm(node, vm) {
  const kind =
    node.kind === "person" ? "Person" : node.kind === "gov" ? "Government" : "Organization";
  return `
    <button type="button" class="insp-close" data-hide-editor aria-label="Hide editor">×</button>
    <header class="insp-head">
      <p class="insp-kind">${esc(kind)}</p>
      <h3>${esc(node.name)}</h3>
      <p class="insp-id">${node.ein ? `EIN ${esc(node.longEIN)}` : esc(node.id)}</p>
    </header>
    <div class="insp-body">
      <div class="insp-actions">
        <button type="button" class="insp-primary" data-focus-node="${esc(node.id)}">Focus</button>
        <button type="button" class="insp-primary" data-zoom-node="${esc(node.id)}">Zoom ±1 hop</button>
      </div>
      <div class="insp-links">${node.inspectorLinks().map((l) => `<a href="${esc(l.href)}" target="_blank" rel="noopener noreferrer">${esc(l.label)}</a>`).join(" · ")}</div>
      <form id="sb-node-form" class="sb-form">
        <input type="hidden" name="id" value="${esc(node.id)}">
        <label>Name <input name="name" required value="${esc(node.name)}"></label>
        <label>Kind
          <select name="kind">
            <option value="org" ${node.kind === "org" ? "selected" : ""}>Organization</option>
            <option value="person" ${node.kind === "person" ? "selected" : ""}>Person</option>
            <option value="gov" ${node.kind === "gov" ? "selected" : ""}>Government</option>
          </select>
        </label>
        <label>EIN <input name="ein" value="${esc(formatEin(node.ein))}" placeholder="optional"></label>
        <label>Photo URL <input name="photo" value="${esc(node.photo)}"></label>
        <label>Government funds ($) <input name="govFunds" value="${esc(moneyInput(node.govFunds))}"></label>
        <label class="sb-check"><input type="checkbox" name="starting" ${node.starting ? "checked" : ""}> Starting set</label>
        ${inspectorFields(node)}
        <div class="insp-actions">
          <button type="submit" class="insp-primary">Save</button>
          <button type="button" class="insp-neighbor" data-delete-node="${esc(node.id)}">Delete</button>
        </div>
      </form>
      <form id="sb-edge-form" class="sb-form">
        <p class="insp-k">Add a flow from here</p>
        <label>To
          <select name="to">${nodeOptions(vm, node.id)}</select>
        </label>
        <input type="hidden" name="from" value="${esc(node.id)}">
        <label>Kind
          <select name="kind">
            <option value="grant">Grant (dollars)</option>
            <option value="partner">Partner (not money)</option>
          </select>
        </label>
        <label>Amount ($) <input name="amount" inputmode="decimal"></label>
        <label>Label <input name="label"></label>
        <label>Cite <input name="cite"></label>
        <button type="submit" class="insp-primary">Add flow</button>
      </form>
    </div>
  `;
}

function parseYears(s) {
  return String(s || "")
    .split(/[,\s]+/)
    .map(Number)
    .filter((y) => y > 1900 && y < 2100);
}

function edgeForm(edge, vm) {
  const a = vm.doc.node(edge.from);
  const b = vm.doc.node(edge.to);
  const partner = edge.kind === "partner";
  return `
    <button type="button" class="insp-close" data-hide-editor aria-label="Hide editor">×</button>
    <header class="insp-head">
      <p class="insp-kind">${partner ? "Partner" : "Grant"}</p>
      <h3>${partner ? "Not money" : esc(moneyInput(edge.amount) ? `$${Number(edge.amount).toLocaleString("en-US")}` : "Grant")}</h3>
    </header>
    <div class="insp-body">
      <p class="insp-grant">
        <button type="button" class="insp-neighbor" data-select-node="${esc(edge.from)}">${esc(a?.name || edge.from)}</button>
        <span>→</span>
        <button type="button" class="insp-neighbor" data-select-node="${esc(edge.to)}">${esc(b?.name || edge.to)}</button>
      </p>
      <p class="insp-note">${
        partner
          ? "Dashed on the diagram. Switch to Grant to attach dollars."
          : "Thickness follows the amount."
      }</p>
      <form id="sb-edge-edit" class="sb-form">
        <input type="hidden" name="id" value="${esc(edge.id)}">
        <label>From
          <select name="from">${nodeOptions(vm, "", edge.from)}</select>
        </label>
        <label>To
          <select name="to">${nodeOptions(vm, "", edge.to)}</select>
        </label>
        <label>Kind
          <select name="kind">
            <option value="grant" ${partner ? "" : "selected"}>Grant (dollars)</option>
            <option value="partner" ${partner ? "selected" : ""}>Partner (not money)</option>
          </select>
        </label>
        <label>Amount ($) <input name="amount" inputmode="decimal" value="${esc(moneyInput(edge.amount))}"></label>
        <label>Years <input name="years" value="${esc(edge.years.join(", "))}" placeholder="2016, 2021"></label>
        <label>Label <input name="label" value="${esc(edge.label)}"></label>
        <label>Cite <input name="cite" value="${esc(edge.cite)}"></label>
        <div class="insp-actions">
          <button type="submit" class="insp-primary">Save</button>
          <button type="button" class="insp-neighbor" data-delete-edge="${esc(edge.id)}">Delete</button>
        </div>
      </form>
    </div>
  `;
}

function inspectorFields(node) {
  const i = node?.inspector || {
    propublica: Boolean(node?.ein),
    nonprofit: Boolean(node?.ein),
    award_search: Boolean(node?.ein),
    maps: true,
    google: true,
  };
  const einOff = !node?.ein;
  return `
    <fieldset class="sb-inspect">
      <legend>Inspector links</legend>
      <p class="sb-lede">Grok is always on. EIN links stay off until an EIN is stored.</p>
      <label class="sb-check"><input type="checkbox" checked disabled> Grok</label>
      <label class="sb-check"><input type="checkbox" name="insp-propublica" ${i.propublica ? "checked" : ""} ${einOff ? "disabled" : ""}> ProPublica</label>
      <label class="sb-check"><input type="checkbox" name="insp-nonprofit" ${i.nonprofit ? "checked" : ""} ${einOff ? "disabled" : ""}> Charity funding</label>
      <label class="sb-check"><input type="checkbox" name="insp-award_search" ${i.award_search ? "checked" : ""} ${einOff ? "disabled" : ""}> Federal grants</label>
      <label class="sb-check"><input type="checkbox" name="insp-maps" ${i.maps ? "checked" : ""}> Maps</label>
      <label class="sb-check"><input type="checkbox" name="insp-google" ${i.google ? "checked" : ""}> Google</label>
    </fieldset>
  `;
}

function nodeOptions(vm, disabledId, selectedId) {
  const opts = vm.doc.nodes
    .map((n) => {
      const dis = n.id === disabledId ? "disabled" : "";
      const sel = n.id === selectedId ? "selected" : "";
      return `<option value="${esc(n.id)}" ${dis} ${sel}>${esc(n.name)}</option>`;
    })
    .join("");
  return `<option value="">Choose…</option>${opts}`;
}

function edgeList(vm, node) {
  const edges = node
    ? vm.doc.edges.filter((e) => e.from === node.id || e.to === node.id)
    : vm.doc.edges;
  if (!edges.length) return "";
  return `
    <div class="insp-neighbors">
      <p class="insp-k">${node ? "Flows on this node" : "All flows"}</p>
      <ul>
        ${edges
          .map((e) => {
            const a = vm.doc.node(e.from);
            const b = vm.doc.node(e.to);
            return `<li>
              <button type="button" class="insp-neighbor" data-select-edge="${esc(e.id)}">${esc(a?.name || e.from)} → ${esc(b?.name || e.to)}</button>
              <span>${esc(e.kind)}${e.amount ? " · $" + e.amount.toLocaleString("en-US") : ""}</span>
            </li>`;
          })
          .join("")}
      </ul>
    </div>
  `;
}

function readInspector(form) {
  return {
    propublica: form.querySelector('[name="insp-propublica"]')?.checked || false,
    nonprofit: form.querySelector('[name="insp-nonprofit"]')?.checked || false,
    award_search: form.querySelector('[name="insp-award_search"]')?.checked || false,
    maps: form.querySelector('[name="insp-maps"]')?.checked || false,
    google: form.querySelector('[name="insp-google"]')?.checked || false,
  };
}

function bindPanel(panel, vm) {
  panel.querySelector("[data-deselect]")?.addEventListener("click", () => {
    vm.setSelected(null);
    vm.setEditorOpen(false);
  });
  panel.querySelector("[data-hide-editor]")?.addEventListener("click", () => vm.setEditorOpen(false));
  panel.querySelector("[data-reveal-all]")?.addEventListener("click", () => vm.revealAll());
  panel.querySelector("[data-focus-node]")?.addEventListener("click", (ev) => {
    const id = ev.currentTarget.getAttribute("data-focus-node");
    vm.setClickMode("focus");
    vm.clickNode(id);
  });
  panel.querySelector("[data-zoom-node]")?.addEventListener("click", (ev) => {
    const id = ev.currentTarget.getAttribute("data-zoom-node");
    vm.setClickMode("zoom");
    vm.clickNode(id);
  });
  panel.querySelectorAll("[data-select-node]").forEach((b) => {
    b.addEventListener("click", () => vm.setSelected(b.getAttribute("data-select-node")));
  });
  panel.querySelectorAll("[data-select-edge]").forEach((b) => {
    b.addEventListener("click", () => vm.setSelectedEdge(b.getAttribute("data-select-edge")));
  });
  panel.querySelector("#sb-edge-edit")?.addEventListener("submit", (e) => {
    e.preventDefault();
    const fd = new FormData(e.target);
    vm.upsertEdge({
      id: fd.get("id"),
      from: fd.get("from"),
      to: fd.get("to"),
      kind: fd.get("kind"),
      amount: fd.get("amount"),
      years: parseYears(fd.get("years")),
      label: fd.get("label"),
      cite: fd.get("cite"),
    });
  });
  panel.querySelector("#sb-node-form")?.addEventListener("submit", (e) => {
    e.preventDefault();
    const f = e.target;
    const fd = new FormData(f);
    vm.upsertNode({
      id: fd.get("id") || undefined,
      name: fd.get("name"),
      kind: fd.get("kind"),
      ein: fd.get("ein"),
      photo: fd.get("photo"),
      govFunds: fd.get("govFunds"),
      starting: fd.has("starting"),
      inspector: readInspector(f),
    });
  });
  panel.querySelector("#sb-edge-form")?.addEventListener("submit", (e) => {
    e.preventDefault();
    const fd = new FormData(e.target);
    vm.upsertEdge({
      from: fd.get("from"),
      to: fd.get("to"),
      kind: fd.get("kind"),
      amount: fd.get("amount"),
      label: fd.get("label"),
      cite: fd.get("cite"),
    });
  });
  panel.querySelectorAll("[data-delete-node]").forEach((b) => {
    b.addEventListener("click", () => vm.deleteNode(b.getAttribute("data-delete-node")));
  });
  panel.querySelectorAll("[data-delete-edge]").forEach((b) => {
    b.addEventListener("click", () => vm.deleteEdge(b.getAttribute("data-delete-edge")));
  });
}
