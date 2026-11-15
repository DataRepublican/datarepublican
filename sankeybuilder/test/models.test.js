import { describe, expect, it } from "vitest";
import {
  EXTRACT_GIST,
  extractBootstrapPrompt,
  extractGrokHref,
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
