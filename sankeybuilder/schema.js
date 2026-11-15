/** Parse and normalize a Show Don't Tell document.
 *
 * Why a separate module: the Grok prompt, the file loader, and the editor
 * all have to agree on ids. Browse's CharityDatabase is the 990 warehouse
 * and must not be imported here.
 */

export const SCHEMA_VERSION = 1;
export const US_GOV_ID = "us-gov";

const KINDS = new Set(["org", "person", "gov"]);
const EDGE_KINDS = new Set(["grant", "partner"]);

export function slugify(name) {
  const s = String(name || "")
    .normalize("NFKD")
    .replace(/[\u0300-\u036f]/g, "")
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, "-")
    .replace(/^-+|-+$/g, "")
    .slice(0, 80);
  return s || "node";
}

/** 9 digits, or null. Hyphens and spaces stripped. Never pad a short string. */
export function normalizeEin(raw) {
  if (raw == null || raw === "") return null;
  const digits = String(raw).replace(/\D/g, "");
  if (digits.length !== 9) return null;
  return digits;
}

export function formatEin(digits) {
  if (!digits || digits.length !== 9) return "";
  return `${digits.slice(0, 2)}-${digits.slice(2)}`;
}

export function nodeIdFrom(raw) {
  const ein = normalizeEin(raw.ein);
  if (ein) return ein;
  if (raw.id && String(raw.id).trim()) return String(raw.id).trim();
  return slugify(raw.name);
}

function defaultInspector(ein) {
  const has = Boolean(ein);
  return {
    propublica: has,
    nonprofit: has,
    award_search: has,
    maps: true,
    google: true,
  };
}

function cleanInspector(raw, ein) {
  const d = defaultInspector(ein);
  const src = raw && typeof raw === "object" ? raw : {};
  const out = { ...d };
  for (const k of Object.keys(d)) {
    if (typeof src[k] === "boolean") out[k] = src[k];
  }
  if (!ein) {
    out.propublica = false;
    out.nonprofit = false;
    out.award_search = false;
  }
  return out;
}

function cleanNode(raw, errors, index) {
  if (!raw || typeof raw !== "object") {
    errors.push(`nodes[${index}] is not an object`);
    return null;
  }
  const name = String(raw.name || "").trim();
  if (!name) {
    errors.push(`nodes[${index}] needs a name`);
    return null;
  }
  let kind = String(raw.kind || "org").toLowerCase();
  if (!KINDS.has(kind)) {
    errors.push(`nodes[${index}] kind "${raw.kind}" is not org|person|gov`);
    kind = "org";
  }
  const ein = normalizeEin(raw.ein);
  const id = nodeIdFrom({ ...raw, ein, name });
  const photo =
    kind === "person" && raw.photo ? String(raw.photo).trim() : "";
  const govFunds = Number(raw.govFunds);
  return {
    id,
    name,
    kind,
    ein,
    starting: raw.starting !== false && raw.starting !== "false",
    photo,
    govFunds: Number.isFinite(govFunds) && govFunds > 0 ? govFunds : 0,
    inspector: cleanInspector(raw.inspector, ein),
  };
}

function cleanEdge(raw, ids, errors, index) {
  if (!raw || typeof raw !== "object") {
    errors.push(`edges[${index}] is not an object`);
    return null;
  }
  const from = String(raw.from || "").trim();
  const to = String(raw.to || "").trim();
  if (!from || !to) {
    errors.push(`edges[${index}] needs from and to`);
    return null;
  }
  if (!ids.has(from)) {
    errors.push(`edges[${index}] from "${from}" is not a node`);
    return null;
  }
  if (!ids.has(to)) {
    errors.push(`edges[${index}] to "${to}" is not a node`);
    return null;
  }
  if (from === to) {
    errors.push(`edges[${index}] is a self-loop`);
    return null;
  }
  let kind = String(raw.kind || "grant").toLowerCase();
  if (!EDGE_KINDS.has(kind)) {
    errors.push(`edges[${index}] kind "${raw.kind}" is not grant|partner`);
    kind = "grant";
  }
  const amount = Number(raw.amount);
  const years = Array.isArray(raw.years)
    ? raw.years.map(Number).filter((y) => y > 1900 && y < 2100)
    : [];
  return {
    id: raw.id ? String(raw.id) : `${from}~${to}~${kind}~${index}`,
    from,
    to,
    kind,
    amount:
      kind === "grant" && Number.isFinite(amount) && amount > 0 ? amount : 0,
    years,
    label: String(raw.label || "").trim(),
    cite: String(raw.cite || "").trim(),
  };
}

function ensureGovForFunds(nodes, edges) {
  const funded = nodes.filter((n) => n.govFunds > 0);
  if (!funded.length) return { nodes, edges };
  let gov = nodes.find((n) => n.id === US_GOV_ID || n.kind === "gov");
  if (!gov) {
    gov = {
      id: US_GOV_ID,
      name: "U.S. government",
      kind: "gov",
      ein: null,
      starting: false,
      photo: "",
      govFunds: 0,
      inspector: defaultInspector(null),
    };
    nodes = [gov, ...nodes];
  }
  const extra = [];
  funded.forEach((n) => {
    if (n.id === gov.id) return;
    const existing = edges.find(
      (e) => e.from === gov.id && e.to === n.id && e.kind === "grant",
    );
    if (existing) {
      existing.amount = n.govFunds;
      if (!existing.label) existing.label = "government funds";
      return;
    }
    extra.push({
      id: `${gov.id}~${n.id}~grant~govFunds-${extra.length}`,
      from: gov.id,
      to: n.id,
      kind: "grant",
      amount: n.govFunds,
      years: [],
      label: "government funds",
      cite: "",
    });
  });
  return { nodes, edges: extra.length ? edges.concat(extra) : edges };
}

export function emptyDocument() {
  return {
    version: SCHEMA_VERSION,
    title: "Untitled graph",
    source: { url: "", note: "" },
    nodes: [],
    edges: [],
  };
}

/**
 * @returns {{ ok: boolean, doc: object, errors: string[] }}
 */
/** Grok often wraps the object in ```json fences or a sentence. */
export function unwrapJsonText(s) {
  let t = String(s || "").trim();
  const fence = t.match(/```(?:json)?\s*([\s\S]*?)```/i);
  if (fence) return fence[1].trim();
  const start = t.indexOf("{");
  const end = t.lastIndexOf("}");
  if (start > 0 && end > start) return t.slice(start, end + 1);
  return t;
}

export function parseDocument(input) {
  const errors = [];
  let raw = input;
  if (typeof input === "string") {
    try {
      raw = JSON.parse(unwrapJsonText(input));
    } catch (e) {
      return { ok: false, doc: emptyDocument(), errors: ["JSON is not valid"] };
    }
  }
  if (!raw || typeof raw !== "object" || Array.isArray(raw)) {
    return { ok: false, doc: emptyDocument(), errors: ["Document is not an object"] };
  }
  const nodesIn = Array.isArray(raw.nodes)
    ? raw.nodes
    : Array.isArray(raw.orgs)
      ? raw.orgs
      : [];
  const edgesIn = Array.isArray(raw.edges)
    ? raw.edges
    : Array.isArray(raw.grants)
      ? raw.grants
      : [];

  const nodes = [];
  const seen = new Set();
  nodesIn.forEach((n, i) => {
    const node = cleanNode(n, errors, i);
    if (!node) return;
    if (seen.has(node.id)) {
      errors.push(`duplicate node id "${node.id}"`);
      return;
    }
    seen.add(node.id);
    nodes.push(node);
  });

  const edges = [];
  edgesIn.forEach((e, i) => {
    const edge = cleanEdge(e, seen, errors, i);
    if (edge) edges.push(edge);
  });

  const withGov = ensureGovForFunds(nodes, edges);
  const source =
    raw.source && typeof raw.source === "object"
      ? {
          url: String(raw.source.url || "").trim(),
          note: String(raw.source.note || "").trim(),
        }
      : { url: String(raw.source || "").trim(), note: "" };

  const doc = {
    version: SCHEMA_VERSION,
    title: String(raw.title || "Untitled graph").trim() || "Untitled graph",
    source,
    nodes: withGov.nodes,
    edges: withGov.edges,
  };
  return { ok: errors.length === 0, doc, errors };
}
