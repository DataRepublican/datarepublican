import { beforeEach, describe, expect, it } from "vitest";
import {
  Charity,
  bandById,
  bandHasFiles,
  canUpgradeBand,
  defaultBandId,
  estimateBandLoadMs,
  nextHostedBandId,
  recordBandLoadMs,
} from "../models.js";
import { IDS, buildGatesGraph } from "./gatesGraph.js";

describe("BrowseViewModel", () => {
  let g;
  beforeEach(() => {
    g = buildGatesGraph();
  });

  it("click mode add seeds without dropping other orgs", () => {
    g.nodes.trust.place(1, 1);
    g.vm.setClickMode("add");
    expect(g.vm.clickNode({}, g.nodes.foundation, null)).toBe("add");
    const show = g.vm.getShowList().map((s) => s.split(/[:~]/)[0]);
    expect(show).toEqual(expect.arrayContaining([IDS.trust, IDS.foundation]));
  });

  it("click mode subtract hides leftover see-more stubs", () => {
    g.nodes.trust.place(0, 3);
    g.vm.setClickMode("subtract");
    expect(g.vm.clickNode({}, g.nodes.leftover, null)).toBe("subtract");
    expect(g.vm.getHideList()).toContain(IDS.leftover);
    expect(g.nodes.leftover.desiredVisible).toBe(false);
  });

  it("focus click on an already-desired node expands both sides", () => {
    g.nodes.trust.place(0, 1);
    const beforeOut = g.nodes.trust.visibleGrants.length;
    g.vm.setClickMode("focus");
    expect(g.vm.clickNode({}, g.nodes.trust, null)).toBe("expand");
    expect(g.nodes.trust.visibleGrants.length).toBeGreaterThan(beforeOut);
  });

  it("⌘/Ctrl click adds without depending on the mode button", () => {
    g.nodes.trust.place(1, 1);
    g.vm.setClickMode("focus");
    expect(
      g.vm.clickNode({ metaKey: true }, g.nodes.foundation, null),
    ).toBe("add");
    const show = g.vm.getShowList().map((s) => s.split(/[:~]/)[0]);
    expect(show).toEqual(expect.arrayContaining([IDS.trust, IDS.foundation]));
  });

  it("click mode inspect does not tunnel", () => {
    g.nodes.trust.place(1, 1);
    g.vm.setClickMode("inspect");
    const before = g.vm.getShowList().slice();
    expect(g.vm.clickNode({}, g.nodes.foundation, null)).toBe("inspect");
    expect(g.vm.getShowList()).toEqual(before);
  });

  it("click mode zoom does not tunnel or seed", () => {
    g.nodes.trust.place(1, 1);
    g.vm.setClickMode("zoom");
    const before = g.vm.getShowList().slice();
    expect(g.vm.clickNode({}, g.nodes.foundation, null)).toBe("zoom");
    expect(g.vm.getShowList()).toEqual(before);
    expect(g.nodes.foundation.kindCaption).toBe("Charity");
  });

  it("clicking a leftover stub does not tunnel or load more", () => {
    g.nodes.trust.place(1, 1);
    const before = g.vm.getShowList().slice();
    expect(g.vm.clickNode({}, g.nodes.leftover, null)).toBe("leftover");
    expect(g.vm.getShowList()).toEqual(before);
  });

  it("tunnelNode leaves only that org on the show list", () => {
    g.nodes.trust.place(1, 1);
    g.nodes.foundation.place(1, 1);
    g.nodes.trust.tunnelNode();
    const show = g.vm.getShowList();
    expect(show).toHaveLength(1);
    expect(show[0].startsWith(IDS.trust)).toBe(true);
    expect(g.nodes.trust.desiredVisible).toBe(true);
    expect(g.nodes.foundation.desiredVisible).toBe(false);
  });

  it("focus breadcrumbs let you return to a preset", () => {
    g.vm.loadPreset({ title: "Uniparty", eins: [IDS.trust, IDS.foundation] }, "replace");
    g.nodes.trust.place(1, 1);
    g.nodes.foundation.place(1, 1);
    expect(g.vm.clickNode({}, g.nodes.mit, null)).toBe("focus");
    expect(g.vm.getShowList()).toHaveLength(1);
    expect(g.vm.getBreadCrumbs().length).toBeGreaterThanOrEqual(1);
    expect(g.vm.getBreadCrumbs()[0].title).toMatch(/Uniparty/i);
    g.vm.restoreCrumb(0);
    const restored = g.vm.getShowList().map((s) => s.split(/[:~]/)[0]);
    expect(restored).toEqual(expect.arrayContaining([IDS.trust, IDS.foundation]));
  });

  it("focus clears keywords so the graph actually focuses", () => {
    g.vm.setKeywordList(["gates"]);
    expect(g.vm.clickNode({}, g.nodes.trust, null)).toBe("focus");
    expect(g.vm.getKeywordList()).toEqual([]);
    expect(g.vm.getShowList().some((e) => e.startsWith(IDS.trust))).toBe(true);
  });

  it("loadPreset add unions, replace replaces", () => {
    g.vm.loadPreset({ eins: [IDS.trust] }, "add");
    g.vm.loadPreset({ eins: [IDS.foundation] }, "add");
    const added = g.vm.getShowList().map((s) => s.split("~")[0]);
    expect(added).toEqual(expect.arrayContaining([IDS.trust, IDS.foundation]));
    g.vm.loadPreset({ eins: [IDS.mit] }, "replace");
    const replaced = g.vm.getShowList().map((s) => s.split("~")[0]);
    expect(replaced).toEqual([IDS.mit]);
  });

  it("URL round-trips e= seeds", () => {
    g.vm.setShowList([`${IDS.trust}~1~1`]);
    const params = g.vm.computeURLParams();
    expect(params.getAll("e").some((e) => e.startsWith(IDS.trust))).toBe(true);
    g.nodes.trust.clearVisibility();
    g.vm.parseQueryParams(params);
    expect(g.vm.getShowList().some((e) => e.startsWith(IDS.trust))).toBe(true);
  });

  it("legacy ein= is read by parseParamsWithOldNew", () => {
    const params = new URLSearchParams();
    params.append("ein", `${IDS.trust}~2~2`);
    g.vm.parseQueryParams(params);
    const show = g.vm.getShowList();
    expect(show.some((e) => e.startsWith(IDS.trust))).toBe(true);
  });

  it("hide list drops the node from sankey data", () => {
    g.nodes.trust.place(1, 1);
    g.vm.computeImpliedVisibility();
    g.vm.addToHideList(IDS.mit);
    const data = g.vm.buildSankeyData();
    const ids = data.nodes.map((n) => n.ein);
    expect(ids).not.toContain(IDS.mit);
  });

  it("implied hop from Trust does not seed the Foundation 990 as a desired node", () => {
    g.nodes.trust.place(0, 1);
    g.vm.computeImpliedVisibility();
    expect(g.nodes.trust.desiredVisible).toBe(true);
    expect(g.nodes.foundation.desiredVisible).toBe(false);
    const ghostVisible =
      g.nodes.ghost.isVisible || g.nodes.ghost.impliedVisible > 0;
    expect(ghostVisible).toBe(true);
  });

  it("leftover stub is not a 990 card", () => {
    g.nodes.trust.place(0, 3);
    expect(g.nodes.leftover.has990Card).toBe(false);
    expect(g.nodes.leftover.kind).toBe("leftover");
  });

  it("default band is $10M; $1M and All are hosted upgrades", () => {
    expect(defaultBandId()).toBe("10M");
    expect(g.vm.loadedBand).toBe("10M");
    expect(canUpgradeBand("10M", "1M")).toBe(true);
    expect(canUpgradeBand("10M", "all")).toBe(true);
    expect(canUpgradeBand("1M", "10M")).toBe(false);
    expect(canUpgradeBand("10M", "10M")).toBe(false);
    expect(bandHasFiles(bandById("10M"))).toBe(true);
    expect(bandHasFiles(bandById("1M"))).toBe(true);
    expect(bandHasFiles(bandById("all"))).toBe(true);
    expect(nextHostedBandId("10M")).toBe("1M");
    expect(bandById("1M").files[0].baseFile).toMatch(/^https:\/\/www\.grumpytechbro\.com\//);
  });

  it("estimates $1M and All from this machine's $10M load, ignoring origin", () => {
    const store = {};
    const prev = globalThis.localStorage;
    globalThis.localStorage = {
      getItem: (k) => (k in store ? store[k] : null),
      setItem: (k, v) => {
        store[k] = String(v);
      },
    };
    try {
      recordBandLoadMs("10M", "web", 136000);
      const ten = bandById("10M");
      const one = bandById("1M");
      const all = bandById("all");
      expect(estimateBandLoadMs("1M")).toBe(
        Math.round(136000 * (one.zipBytes / ten.zipBytes))
      );
      expect(estimateBandLoadMs("all")).toBe(
        Math.round(136000 * (all.zipBytes / ten.zipBytes))
      );
    } finally {
      if (prev === undefined) delete globalThis.localStorage;
      else globalThis.localStorage = prev;
    }
  });

  it("requestBand same band is a no-op", async () => {
    await expect(g.vm.requestBand("10M")).resolves.toEqual({
      status: "current",
      band: "10M",
    });
    expect(g.vm.loadedBand).toBe("10M");
  });

  it("buildSankeyData node ids are graph keys; longEIN empty on ghosts", () => {
    g.nodes.trust.place(1, 3);
    g.vm.computeImpliedVisibility();
    const data = g.vm.buildSankeyData();
    for (const n of data.nodes) {
      expect(n.id).toBeTruthy();
      if (n.isGhost || n.isLeftover) {
        expect(n.longEIN).toBe("");
      }
    }
  });

});
