import { describe, expect, it } from "vitest";
import {
  EXTRACT_GIST,
  extractBootstrapPrompt,
  extractGrokHref,
  GraphNode,
  GraphEdge,
} from "../models.js";

describe("extract bootstrap", () => {
  it("points Grok at the schema gist then the post", () => {
    const t = extractBootstrapPrompt();
    expect(t).toContain(EXTRACT_GIST);
    expect(t).toMatch(/^Read this gist:/);
    expect(t).toContain("Then read the following post or article");
    expect(t).not.toMatch(/Never invent an EIN/);
  });

  it("builds a grok.com compose link from a post URL", () => {
    const post = "https://x.com/labtechleigh/status/2118414465632739481";
    expect(extractGrokHref("")).toBe("");
    expect(extractGrokHref("not-a-url")).toBe("");
    const href = extractGrokHref(post);
    expect(href.startsWith("https://grok.com/?")).toBe(true);
    const q = new URL(href).searchParams.get("q");
    expect(q).toContain(EXTRACT_GIST);
    expect(q).toContain(post);
  });
});

describe("hover copy", () => {
  it("names an org, its EIN, and Gov $", () => {
    const n = new GraphNode({
      id: "137029866",
      name: "Open Society Foundations",
      kind: "org",
      ein: "137029866",
      govFunds: 250000,
      inspector: {},
    });
    expect(n.toolTipText()).toMatch(/Open Society Foundations/);
    expect(n.toolTipText()).toMatch(/EIN 13-7029866/);
    expect(n.toolTipText()).toMatch(/\$250,000/);
  });

  it("writes a grant as from → to with dollars", () => {
    const e = new GraphEdge({
      id: "a~b~grant",
      from: "a",
      to: "b",
      kind: "grant",
      amount: 10500000,
      label: "$10.5M",
      years: [2023],
    });
    const tip = e.toolTipText("Open Society Foundations", "Example Alliance");
    expect(tip).toMatch(/Open Society Foundations → Example Alliance/);
    expect(tip).toMatch(/\$10,500,000/);
    expect(tip).not.toMatch(/undefined/);
  });

  it("writes a partner without dollars", () => {
    const e = new GraphEdge({
      id: "j~a~partner",
      from: "j",
      to: "a",
      kind: "partner",
      label: "board",
    });
    expect(e.toolTipText("Jane Example", "Example Alliance")).toBe(
      "Jane Example · board · Example Alliance",
    );
  });
});
