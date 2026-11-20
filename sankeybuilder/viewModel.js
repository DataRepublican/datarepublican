import { GraphDocument } from "./models.js";
import {
  emptyDocument,
  parseDocument,
  nodeIdFrom,
  normalizeEin,
  normalizeEdgeKind,
  isPartnerKind,
  slugify,
  US_GOV_ID,
} from "./schema.js";
import {
  encodeFragment,
  decodeFragment,
  parseLocationShare,
  gistRawUrl,
  isAllowedLoadUrl,
} from "./share.js";
import { memoryStore } from "./store.js";

function uniqueEdgeId(doc, from, to, kind) {
  const base = `${from}~${to}~${kind}`;
  if (!doc.edges.some((e) => e.id === base)) return base;
  let i = 2;
  while (doc.edges.some((e) => e.id === `${base}-${i}`)) i += 1;
  return `${base}-${i}`;
}

export class SankeyBuilderViewModel {
  constructor(opts = {}) {
    this.store = opts.store || memoryStore();
    this.fetchFn = opts.fetch || (typeof fetch === "function" ? fetch.bind(globalThis) : null);
    this.location = opts.location || (typeof window !== "undefined" ? window.location : { search: "", hash: "", origin: "", pathname: "/sankeybuilder/" });
    this.history = opts.history || (typeof window !== "undefined" ? window.history : { replaceState() {} });
    this.doc = new GraphDocument(emptyDocument());
    this.selectedId = null;
    this.selectedEdgeId = null;
    this.view = "diagram";
    this.editorOpen = true;
    this.controlsOpen = true;
    this.circularLinks = true;
    this.hidden = new Set();
    this.status = "";
    this.error = "";
    this.listeners = new Set();
    this.searchQuery = "";
    // Expand is the author-graph default: click reveals neighbors. Browse
    // defaults to focus because the warehouse is already fully drawn.
    this.clickMode = "add";
    this.flowScale = 1;
    this.camera = null;
  }

  subscribe(fn) {
    this.listeners.add(fn);
    return () => this.listeners.delete(fn);
  }

  notify() {
    for (const fn of this.listeners) fn(this);
  }

  setStatus(msg) {
    this.status = msg || "";
    this.notify();
  }

  setError(msg) {
    this.error = msg || "";
    this.notify();
  }

  loadParsed(parsed, { persist = true } = {}) {
    if (!parsed.ok && parsed.errors.length && parsed.doc.nodes.length === 0) {
      this.error = parsed.errors.join("; ");
      this.notify();
      return false;
    }
    this.doc = new GraphDocument(parsed.doc);
    this.error = parsed.ok ? "" : parsed.errors.join("; ");
    this.selectedId = null;
    this.selectedEdgeId = null;
    this.applyStartingSet();
    if (persist) this.saveLocal();
    this.notify();
    return true;
  }

  loadJSON(input, opts) {
    return this.loadParsed(parseDocument(input), opts);
  }

  applyStartingSet() {
    const starters = this.doc.nodes.filter((n) => n.starting);
    if (!starters.length) {
      this.hidden = new Set();
      return;
    }
    const visible = new Set(starters.map((n) => n.id));
    this.hidden = new Set(
      this.doc.nodes.filter((n) => !visible.has(n.id)).map((n) => n.id),
    );
  }

  neighborIds(id) {
    const extra = [];
    for (const e of this.doc.edges) {
      if (e.from === id) extra.push(e.to);
      if (e.to === id) extra.push(e.from);
    }
    return extra;
  }

  revealNeighbors(id) {
    for (const x of this.neighborIds(id)) this.hidden.delete(x);
    this.notify();
  }

  setClickMode(mode) {
    const allowed = new Set(["focus", "zoom", "add", "subtract", "inspect"]);
    this.clickMode = allowed.has(mode) ? mode : "add";
    this.notify();
    return this.clickMode;
  }

  /** Shift = hide, Alt/Option = inspect, ⌘/Ctrl = expand. Plain click uses the mode button. */
  modeFromEvent(event) {
    if (event && event.shiftKey) return "subtract";
    if (event && event.altKey) return "inspect";
    if (event && (event.metaKey || event.ctrlKey)) return "add";
    return this.clickMode || "add";
  }

  clickNode(id, event) {
    const mode = this.modeFromEvent(event);
    if (mode === "subtract") {
      this.hidden.add(id);
      if (this.selectedId === id) this.selectedId = null;
      this.camera = "fit";
      this.notify();
      return mode;
    }
    this.selectedId = id;
    this.selectedEdgeId = null;
    if (mode === "inspect") {
      this.camera = null;
      this.editorOpen = true;
      this.notify();
      return mode;
    }
    if (mode === "zoom") {
      this.camera = "neighborhood";
      this.notify();
      return mode;
    }
    if (mode === "focus") {
      const keep = new Set([id, ...this.neighborIds(id)]);
      this.hidden = new Set(
        this.doc.nodes.filter((n) => !keep.has(n.id)).map((n) => n.id),
      );
      this.camera = "fit";
      this.notify();
      return mode;
    }
    for (const x of this.neighborIds(id)) this.hidden.delete(x);
    this.notify();
    return "add";
  }

  nodePadding() {
    return Math.max(8, Math.round(24 * this.flowScale));
  }

  scaleUp() {
    this.flowScale = Math.min(3, Math.round(this.flowScale * 1.25 * 100) / 100);
    this.notify();
  }

  scaleDown() {
    this.flowScale = Math.max(0.4, Math.round((this.flowScale / 1.25) * 100) / 100);
    this.notify();
  }

  scaleReset() {
    this.flowScale = 1;
    this.notify();
  }

  setView(view) {
    this.view = view === "table" ? "table" : "diagram";
    this.notify();
  }

  setEditorOpen(on) {
    this.editorOpen = Boolean(on);
    this.notify();
  }

  setControlsOpen(on) {
    this.controlsOpen = Boolean(on);
    this.notify();
  }

  setCircularLinks(on) {
    this.circularLinks = Boolean(on);
    this.notify();
  }

  setSelected(id) {
    this.selectedId = id || null;
    this.selectedEdgeId = null;
    this.notify();
  }

  clickEdge(id, event) {
    const edge = id ? this.doc.edge(id) : null;
    this.selectedEdgeId = edge ? edge.id : null;
    this.selectedId = null;
    if (edge) {
      this.hidden.delete(edge.from);
      this.hidden.delete(edge.to);
    }
    if (edge && this.modeFromEvent(event) === "inspect") this.editorOpen = true;
    this.notify();
  }

  setSelectedEdge(id) {
    const edge = id ? this.doc.edge(id) : null;
    this.selectedEdgeId = edge ? edge.id : null;
    this.selectedId = null;
    if (edge) {
      this.hidden.delete(edge.from);
      this.hidden.delete(edge.to);
    }
    this.notify();
  }

  selectedNode() {
    return this.selectedId ? this.doc.node(this.selectedId) : null;
  }

  selectedEdge() {
    return this.selectedEdgeId ? this.doc.edge(this.selectedEdgeId) : null;
  }

  revealAll() {
    this.hidden = new Set();
    this.notify();
  }

  setSearch(q) {
    this.searchQuery = String(q || "");
    this.notify();
  }

  searchHits() {
    const q = this.searchQuery.trim().toLowerCase();
    if (!q) return [];
    return this.doc.nodes.filter(
      (n) =>
        n.name.toLowerCase().includes(q) ||
        n.id.toLowerCase().includes(q) ||
        (n.ein && n.ein.includes(q.replace(/\D/g, ""))),
    );
  }

  focusSearchHit() {
    const hits = this.searchHits();
    if (hits.length === 1) {
      this.hidden.delete(hits[0].id);
      this.setSelected(hits[0].id);
    }
    return hits;
  }

  setTitle(title) {
    this.doc.title = String(title || "").trim() || "Untitled graph";
    this.saveLocal();
    this.notify();
  }

  setSource(source) {
    this.doc.source = {
      url: String(source?.url || "").trim(),
      note: String(source?.note || "").trim(),
    };
    this.saveLocal();
    this.notify();
  }

  upsertNode(partial) {
    const ein = normalizeEin(partial.ein);
    const id = partial.id || nodeIdFrom({ ...partial, ein });
    const existing = this.doc.node(id);
    const next = {
      id,
      name: String(partial.name || existing?.name || "").trim(),
      kind: partial.kind || existing?.kind || "org",
      ein: ein !== undefined && partial.ein !== undefined ? ein : existing?.ein || null,
      starting:
        partial.starting !== undefined
          ? Boolean(partial.starting)
          : existing
            ? existing.starting
            : true,
      photo: partial.photo !== undefined ? String(partial.photo || "") : existing?.photo || "",
      govFunds:
        partial.govFunds !== undefined
          ? Number(partial.govFunds) || 0
          : existing?.govFunds || 0,
      inspector: {
        ...(existing?.inspector || {
          propublica: Boolean(ein),
          nonprofit: Boolean(ein),
          award_search: Boolean(ein),
          maps: true,
          google: true,
        }),
        ...(partial.inspector || {}),
      },
    };
    if (!next.name) {
      this.error = "Name is required";
      this.notify();
      return null;
    }
    const json = this.doc.toJSON();
    const idx = json.nodes.findIndex((n) => n.id === id);
    if (idx >= 0) json.nodes[idx] = { ...json.nodes[idx], ...next };
    else json.nodes.push(next);
    const parsed = parseDocument(json);
    this.doc = new GraphDocument(parsed.doc);
    this.hidden.delete(id);
    if (next.govFunds > 0) {
      const gov = this.doc.nodes.find((n) => n.id === US_GOV_ID || n.kind === "gov");
      if (gov) this.hidden.delete(gov.id);
    }
    this.selectedId = id;
    this.selectedEdgeId = null;
    this.error = "";
    this.saveLocal();
    this.notify();
    return this.doc.node(id);
  }

  addEmptyNode() {
    let n = 1;
    let name = "Untitled";
    while (
      this.doc.nodes.some((node) => node.id === slugify(name) || node.name === name)
    ) {
      n += 1;
      name = `Untitled ${n}`;
    }
    return this.upsertNode({ name, kind: "org", starting: true });
  }

  addEmptyEdge() {
    while (this.doc.nodes.length < 2) this.addEmptyNode();
    const nodes = this.doc.nodes;
    const selected = this.selectedId && this.doc.node(this.selectedId);
    const from = selected ? selected.id : nodes[0].id;
    const to = nodes.find((n) => n.id !== from)?.id;
    if (!to) {
      this.error = "A flow needs two different nodes";
      this.notify();
      return null;
    }
    return this.upsertEdge({ from, to, kind: "grant", amount: 0 });
  }

  deleteNode(id) {
    const json = this.doc.toJSON();
    json.nodes = json.nodes.filter((n) => n.id !== id);
    json.edges = json.edges.filter((e) => e.from !== id && e.to !== id);
    this.doc = new GraphDocument(json);
    this.hidden.delete(id);
    if (this.selectedId === id) this.selectedId = null;
    if (this.selectedEdgeId) {
      const e = this.doc.edge(this.selectedEdgeId);
      if (!e) this.selectedEdgeId = null;
    }
    this.saveLocal();
    this.notify();
  }

  upsertEdge(partial) {
    const from = String(partial.from || "").trim();
    const to = String(partial.to || "").trim();
    if (!from || !to || from === to) {
      this.error = "A flow needs two different nodes";
      this.notify();
      return null;
    }
    if (!this.doc.node(from) || !this.doc.node(to)) {
      this.error = "Both ends have to be organizations or people in the graph";
      this.notify();
      return null;
    }
    const kind = normalizeEdgeKind(partial.kind || "grant");
    const existing = partial.id
      ? this.doc.edges.find((e) => e.id === partial.id)
      : null;
    const id = existing ? existing.id : uniqueEdgeId(this.doc, from, to, kind);
    const next = {
      id,
      from,
      to,
      kind,
      amount: isPartnerKind(kind)
        ? 0
        : partial.amount !== undefined
          ? Number(partial.amount) || 0
          : existing?.amount || 0,
      years: Array.isArray(partial.years)
        ? partial.years
        : existing?.years || [],
      label:
        partial.label !== undefined
          ? String(partial.label || "").trim()
          : existing?.label || "",
      cite:
        partial.cite !== undefined
          ? String(partial.cite || "").trim()
          : existing?.cite || "",
    };
    if (existing) Object.assign(existing, next);
    else {
      const json = this.doc.toJSON();
      json.edges.push(next);
      this.doc = new GraphDocument(json);
    }
    this.error = "";
    this.selectedEdgeId = id;
    this.selectedId = null;
    this.hidden.delete(from);
    this.hidden.delete(to);
    this.saveLocal();
    this.notify();
    return this.doc.edge(id);
  }

  deleteEdge(id) {
    const json = this.doc.toJSON();
    json.edges = json.edges.filter((e) => e.id !== id);
    this.doc = new GraphDocument(json);
    if (this.selectedEdgeId === id) this.selectedEdgeId = null;
    this.saveLocal();
    this.notify();
  }

  newDocument() {
    this.doc = new GraphDocument(emptyDocument());
    this.selectedId = null;
    this.selectedEdgeId = null;
    this.hidden = new Set();
    this.error = "";
    this.status = "New graph";
    this.saveLocal();
    this.notify();
  }

  toJSON() {
    return this.doc.toJSON();
  }

  async saveLocal() {
    try {
      await this.store.set(this.doc.toJSON());
    } catch (e) {
      this.error = "Could not save locally";
    }
  }

  async loadLocal() {
    const raw = await this.store.get();
    if (!raw) return false;
    return this.loadJSON(raw, { persist: false });
  }

  async loadFromUrl(url) {
    const origin = this.location.origin || "";
    const abs = (() => {
      try {
        return new URL(url, origin || "https://datarepublican.com").href;
      } catch {
        return "";
      }
    })();
    const gist = gistRawUrl(url);
    const target = gist || abs;
    if (!isAllowedLoadUrl(target, origin) && !gist) {
      this.error =
        "Load from a gist.githubusercontent.com raw URL, or a file on this tool. News and X pages block the browser.";
      this.notify();
      return false;
    }
    if (!this.fetchFn) {
      this.error = "Fetch is not available";
      this.notify();
      return false;
    }
    try {
      const res = await this.fetchFn(target);
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const text = await res.text();
      const ok = this.loadJSON(text);
      if (ok) this.status = `Loaded ${target}`;
      return ok;
    } catch (e) {
      this.error = `Could not load that URL (${e.message || e})`;
      this.notify();
      return false;
    }
  }

  writeFragment() {
    const token = encodeFragment(this.doc.toJSON());
    if (!token) {
      this.status = "Graph is too large for a URL. Save a JSON file or a gist instead.";
      this.notify();
      return null;
    }
    const url = `${this.location.pathname || "/sankeybuilder/"}#d=${token}`;
    try {
      this.history.replaceState(null, "", url);
    } catch {
      /* tests, or a too-long URL the browser rejected */
    }
    this.notify();
    return token;
  }

  async bootFromLocation() {
    const share = parseLocationShare(this.location.search, this.location.hash);
    if (share?.type === "fragment") {
      try {
        const raw = decodeFragment(share.value);
        return this.loadJSON(raw, { persist: true });
      } catch (e) {
        this.error = "The share fragment is not valid JSON";
        this.notify();
        return false;
      }
    }
    if (share?.type === "gist") {
      const rawUrl = gistRawUrl(share.value) || share.value;
      return this.loadFromUrl(rawUrl);
    }
    if (share?.type === "url") return this.loadFromUrl(share.value);
    return this.loadLocal();
  }

  visibleNodes() {
    return this.doc.nodes.filter((n) => !this.hidden.has(n.id));
  }

  visibleEdges() {
    const vis = new Set(this.visibleNodes().map((n) => n.id));
    return this.doc.edges.filter((e) => vis.has(e.from) && vis.has(e.to));
  }

  /**
   * d3-sankey-circular wants {nodes, links} with value on each link.
   * Partner links keep value=1 so dollar thickness stays on grants.
   */
  getSankeyData() {
    const nodes = this.visibleNodes().map((n) => ({
      id: n.id,
      name: n.name,
      kind: n.kind,
      ein: n.ein,
      photo: n.photo,
      colorKey: n.colorKey,
      starting: n.starting,
      tip: n.toolTipText(),
    }));
    const idSet = new Set(nodes.map((n) => n.id));
    const links = this.visibleEdges()
      .filter((e) => idSet.has(e.from) && idSet.has(e.to))
      .map((e) => {
        const from = this.doc.node(e.from);
        const to = this.doc.node(e.to);
        return {
          source: e.from,
          target: e.to,
          value: e.sankeyValue(),
          kind: e.kind,
          label: e.label,
          amount: e.amount,
          cite: e.cite,
          id: e.id,
          tip: e.toolTipText(from?.name, to?.name),
        };
      });
    return { nodes, links };
  }

  suggestedSlug(name) {
    return slugify(name);
  }
}
