import { describe, expect, it } from "vitest";
import {
  decodeFragment,
  encodeFragment,
  gistRawUrl,
  isAllowedLoadUrl,
  parseLocationShare,
} from "../share.js";

describe("share", () => {
  it("round-trips a small graph through #d=", () => {
    const doc = { version: 1, title: "t", nodes: [], edges: [] };
    const token = encodeFragment(doc);
    expect(token).toBeTruthy();
    expect(decodeFragment(token).title).toBe("t");
  });

  it("allows gist raw and same-origin fixtures only", () => {
    expect(
      isAllowedLoadUrl(
        "https://gist.githubusercontent.com/twinforces/abc/raw",
      ),
    ).toBe(true);
    expect(isAllowedLoadUrl("https://x.com/labtechleigh/status/1")).toBe(false);
    expect(
      isAllowedLoadUrl(
        "https://datarepublican.com/sankeybuilder/fixtures/osf-alliance.json",
        "https://datarepublican.com",
      ),
    ).toBe(true);
  });

  it("rewrites a gist page URL to raw", () => {
    expect(gistRawUrl("https://gist.github.com/twinforces/abcdef1234567890")).toBe(
      "https://gist.githubusercontent.com/twinforces/abcdef1234567890/raw",
    );
  });

  it("reads #d= from the location", () => {
    const token = encodeFragment({ version: 1, title: "frag" });
    const share = parseLocationShare("", `#d=${token}`);
    expect(share.type).toBe("fragment");
  });
});
