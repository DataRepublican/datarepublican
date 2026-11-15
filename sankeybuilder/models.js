import { colorKeyFor } from "./color.js";
import { formatEin, US_GOV_ID } from "./schema.js";

export const GRUMPY_TAKE =
  "https://gist.github.com/twinforces/534d9b662de4a010c1c4ebad934cd99a";

export const EXTRACT_GIST =
  "https://gist.github.com/twinforces/706b11ec77740c11a1f258fc9d5030db";

export function extractBootstrapPrompt(postUrl) {
  const body =
    `Read this gist: ${EXTRACT_GIST}\n\n` +
    "Then read the following post or article and output one JSON object.";
  const url = String(postUrl || "").trim();
  return url ? `${body}\n\n${url}` : body;
}

/** Grok compose URL. Empty when the post URL is missing or not http(s). */
export function extractGrokHref(postUrl) {
  const url = String(postUrl || "").trim();
  if (!/^https?:\/\//i.test(url)) return "";
  const params = new URLSearchParams();
  params.set("q", extractBootstrapPrompt(url));
  return `https://grok.com/?${params.toString()}`;
}

function dollars(n) {
  if (!n) return "";
  return new Intl.NumberFormat("en-US", {
    style: "currency",
    currency: "USD",
    maximumFractionDigits: 0,
  }).format(n);
}

export class GraphNode {
  constructor(raw) {
    this.id = raw.id;
    this.name = raw.name;
    this.kind = raw.kind;
    this.ein = raw.ein || null;
    this.starting = Boolean(raw.starting);
    this.photo = raw.photo || "";
    this.govFunds = raw.govFunds || 0;
    this.inspector = { ...raw.inspector };
  }

  get colorKey() {
    return colorKeyFor(this);
  }

  get longEIN() {
    return formatEin(this.ein);
  }

  get isPerson() {
    return this.kind === "person";
  }

  toolTipText() {
    const kind =
      this.kind === "person" ? "person" : this.kind === "gov" ? "government" : "organization";
    const lines = [this.name, kind];
    if (this.ein) lines.push(`EIN ${this.longEIN}`);
    const gov = dollars(this.govFunds);
    if (gov) lines.push(`Gov $ ${gov}`);
    return lines.join("\n");
  }

  toJSON() {
    const o = {
      id: this.id,
      name: this.name,
      kind: this.kind,
      starting: this.starting,
      inspector: { ...this.inspector },
    };
    if (this.ein) o.ein = this.longEIN;
    if (this.photo) o.photo = this.photo;
    if (this.govFunds) o.govFunds = this.govFunds;
    return o;
  }

  grokHref() {
    const who = this.ein
      ? `${this.name} (EIN ${this.longEIN})`
      : this.name;
    const params = new URLSearchParams();
    params.set("q", `I want a Grumpy Take on: ${who}\n\nRead and apply fully: ${GRUMPY_TAKE}`);
    return `https://grok.com/?${params.toString()}`;
  }

  propublicaHref() {
    if (!this.ein) return "";
    return `https://projects.propublica.org/nonprofits/organizations/${this.ein}`;
  }

  nonprofitHref() {
    if (!this.ein) return "";
    return `/nonprofit/?ein=${this.ein}`;
  }

  awardSearchHref() {
    if (!this.ein) return "";
    return `/award_search/?keywords=${this.ein}`;
  }

  mapsHref() {
    const q = this.longEIN ? `${this.name} ${this.longEIN}` : this.name;
    const params = new URLSearchParams();
    params.set("api", "1");
    params.set("query", q);
    return `https://www.google.com/maps/search/?${params.toString()}`;
  }

  googleHref() {
    const q = this.ein ? `${this.longEIN} ${this.name}` : this.name;
    const params = new URLSearchParams();
    params.set("q", q);
    return `https://google.com/search?${params.toString()}`;
  }

  inspectorLinks() {
    const links = [{ label: "Grok", href: this.grokHref() }];
    const flags = this.inspector || {};
    if (this.ein && flags.propublica) {
      links.push({ label: "ProPublica", href: this.propublicaHref() });
    }
    if (this.ein && flags.nonprofit) {
      links.push({ label: "Charity funding", href: this.nonprofitHref() });
    }
    if (this.ein && flags.award_search) {
      links.push({ label: "Federal grants", href: this.awardSearchHref() });
    }
    if (flags.maps) links.push({ label: "Maps", href: this.mapsHref() });
    if (flags.google) links.push({ label: "Google", href: this.googleHref() });
    return links;
  }
}

export class GraphEdge {
  constructor(raw) {
    this.id = raw.id;
    this.from = raw.from;
    this.to = raw.to;
    this.kind = raw.kind;
    this.amount = raw.amount || 0;
    this.years = Array.isArray(raw.years) ? raw.years.slice() : [];
    this.label = raw.label || "";
    this.cite = raw.cite || "";
  }

  /** Partner thickness is a constant so it cannot drown a grant. */
  sankeyValue() {
    if (this.kind === "partner") return 1;
    return Math.max(this.amount, 1);
  }

  toolTipText(fromName, toName) {
    const from = fromName || this.from;
    const to = toName || this.to;
    if (this.kind === "partner") {
      return `${from} · ${this.label || "partner"} · ${to}`;
    }
    const lines = [`${from} → ${to}`];
    const amt = dollars(this.amount);
    if (amt) lines.push(amt);
    if (this.label && this.label !== amt) lines.push(this.label);
    if (this.years.length) lines.push(this.years.join(", "));
    if (this.cite) lines.push(this.cite);
    return lines.join("\n");
  }

  toJSON() {
    const o = {
      id: this.id,
      from: this.from,
      to: this.to,
      kind: this.kind,
    };
    if (this.amount) o.amount = this.amount;
    if (this.years.length) o.years = this.years.slice();
    if (this.label) o.label = this.label;
    if (this.cite) o.cite = this.cite;
    return o;
  }
}

export class GraphDocument {
  constructor(raw) {
    this.version = raw.version;
    this.title = raw.title;
    this.source = { url: raw.source?.url || "", note: raw.source?.note || "" };
    this.nodes = (raw.nodes || []).map((n) => new GraphNode(n));
    this.edges = (raw.edges || []).map((e) => new GraphEdge(e));
  }

  node(id) {
    return this.nodes.find((n) => n.id === id) || null;
  }

  edge(id) {
    return this.edges.find((e) => e.id === id) || null;
  }

  toJSON() {
    return {
      version: this.version,
      title: this.title,
      source: { ...this.source },
      nodes: this.nodes.map((n) => n.toJSON()),
      edges: this.edges.map((e) => e.toJSON()),
    };
  }
}

export { US_GOV_ID };
