import { describe, expect, it } from "vitest";
import {
  formatEin,
  normalizeEin,
  parseDocument,
  slugify,
  unwrapJsonText,
  US_GOV_ID,
} from "../schema.js";
import osf from "../fixtures/osf-alliance.json";
import esrn from "../fixtures/esrn-partners.json";

describe("schema", () => {
  it("slugifies a name when there is no EIN", () => {
    expect(slugify("Open Society Foundations")).toBe("open-society-foundations");
  });

  it("keeps a 9-digit EIN and drops anything else", () => {
    expect(normalizeEin("13-7029866")).toBe("137029866");
    expect(normalizeEin("137029866")).toBe("137029866");
    expect(normalizeEin("12")).toBe(null);
    expect(formatEin("137029866")).toBe("13-7029866");
  });

  it("uses EIN digits as the node id", () => {
    const { ok, doc, errors } = parseDocument(osf);
    expect(errors).toEqual([]);
    expect(ok).toBe(true);
    expect(doc.nodes.map((n) => n.id)).toEqual(
      expect.arrayContaining(["137029866", "example-alliance", "jane-example", US_GOV_ID]),
    );
  });

  it("synthesizes a government node from govFunds", () => {
    const { doc } = parseDocument(osf);
    const govEdge = doc.edges.find(
      (e) => e.from === US_GOV_ID && e.to === "example-alliance",
    );
    expect(govEdge.amount).toBe(250000);
    expect(govEdge.kind).toBe("grant");
  });

  it("loads the ESRN extract fixture", () => {
    const { ok, doc, errors } = parseDocument(esrn);
    expect(errors).toEqual([]);
    expect(ok).toBe(true);
    expect(doc.title).toMatch(/ESRN/);
    expect(doc.edges.filter((e) => e.kind === "partner").length).toBeGreaterThan(5);
    expect(doc.edges.some((e) => e.kind === "grant" && e.amount === 10475001)).toBe(true);
  });

  it("unwraps Grok fences and leading chatter", () => {
    const inner = '{"version":1,"title":"t","nodes":[{"name":"A","kind":"org"}],"edges":[]}';
    expect(JSON.parse(unwrapJsonText("```json\n" + inner + "\n```")).title).toBe("t");
    const { ok, doc } = parseDocument("Here you go:\n```json\n" + inner + "\n```\n");
    expect(ok).toBe(true);
    expect(doc.title).toBe("t");
    expect(doc.nodes[0].id).toBe("a");
  });

  it("rejects an edge whose end is missing", () => {
    const { ok, errors } = parseDocument({
      nodes: [{ name: "A", kind: "org" }],
      edges: [{ from: "a", to: "nobody", kind: "grant", amount: 1 }],
    });
    expect(ok).toBe(false);
    expect(errors.join(" ")).toMatch(/nobody/);
  });

  it("does not duplicate a synthesized government grant on re-parse", () => {
    const once = parseDocument(osf).doc;
    const twice = parseDocument(once).doc;
    const grants = twice.edges.filter(
      (e) => e.from === US_GOV_ID && e.to === "example-alliance",
    );
    expect(grants).toHaveLength(1);
  });

  it("updates the implied government grant when govFunds changes", () => {
    const once = parseDocument({
      nodes: [{ name: "Alpha Fund", kind: "org", govFunds: 100 }],
    }).doc;
    expect(once.nodes.some((n) => n.id === US_GOV_ID)).toBe(true);
    expect(once.edges.find((e) => e.from === US_GOV_ID && e.to === "alpha-fund").amount).toBe(100);
    const twice = parseDocument({
      ...once,
      nodes: once.nodes.map((n) =>
        n.id === "alpha-fund" ? { ...n, govFunds: 250 } : n,
      ),
    }).doc;
    const grants = twice.edges.filter((e) => e.from === US_GOV_ID && e.to === "alpha-fund");
    expect(grants).toHaveLength(1);
    expect(grants[0].amount).toBe(250);
  });

  it("does not treat a short id as an EIN", () => {
    const { doc } = parseDocument({
      nodes: [{ name: "Ghost", kind: "org", ein: "123" }],
    });
    expect(doc.nodes[0].ein).toBe(null);
    expect(doc.nodes[0].id).toBe("ghost");
  });
});
