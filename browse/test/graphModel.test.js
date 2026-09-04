import { beforeEach, describe, expect, it } from "vitest";
import { Charity, Grant } from "../models.js";
import { IDS, buildGatesGraph } from "./gatesGraph.js";

describe("Charity / Grant model (Gates mini-graph)", () => {
  let g;
  beforeEach(() => {
    g = buildGatesGraph();
  });

  it("assigns kinds and 990 cards", () => {
    expect(g.nodes.trust.kind).toBe("charity");
    expect(g.nodes.trust.has990Card).toBe(true);
    expect(g.nodes.ghost.isGhost).toBe(true);
    expect(g.nodes.ghost.has990Card).toBe(false);
    expect(g.nodes.leftover.isLeftover).toBe(true);
    expect(g.nodes.leftover.has990Card).toBe(false);
    expect(g.nodes.mit.isBmfOnly).toBe(true);
    expect(g.nodes.mit.has990Card).toBe(false);
    expect(g.nodes.usg.isGov).toBe(true);
    expect(g.nodes.usg.has990Card).toBe(false);
  });

  it("never presents a GIN or leftover as an IRS EIN", () => {
    expect(g.nodes.ghost.longEIN).toBe("");
    expect(g.nodes.leftover.longEIN).toBe("");
    expect(g.nodes.trust.longEIN).toBe("91-1663695");
    expect(g.nodes.mit.longEIN).toBe("04-2103594");
  });

  it("grok link asks for a Grumpy Take and cites the gist", () => {
    const href = g.nodes.trust.grokLink("Grumpy Take");
    expect(href).toMatch(/grok\.com/);
    expect(href).toMatch(/I\+want\+a\+Grumpy\+Take\+on/);
    expect(decodeURIComponent(href)).toMatch(
      /gist\.github\.com\/twinforces\/534d9b662de4a010c1c4ebad934cd99a/
    );
  });

  it("orgShort copy for non-990 nodes", () => {
    expect(g.nodes.ghost.orgShort).toMatch(/Name-only/i);
    expect(g.nodes.leftover.orgShort).toMatch(/Name-only/i);
    expect(g.nodes.mit.orgShort).toMatch(/Name-only/i);
  });

  it("maps link uses BMF address when present", () => {
    g.nodes.trust.street = "500 5th Ave N";
    g.nodes.trust.city = "Seattle";
    g.nodes.trust.state = "WA";
    g.nodes.trust.zip = "98109";
    const href = g.nodes.trust.mapsLink("Google Maps");
    expect(href).toMatch(/google\.com\/maps\/search/);
    expect(href).toMatch(/Seattle/);
    expect(href).not.toMatch(/guidestar|charitynavigator/i);
  });

  it("grant tooltip uses filer and grantee names", () => {
    const tip = g.edges.toGhost.toolTipText();
    expect(tip).toMatch(/Gates/);
    expect(tip).not.toMatch(/undefined/);
  });

  it("wires grants and copies suggested EIN onto the ghost", () => {
    expect(g.edges.toGhost.filer).toBe(g.nodes.trust);
    expect(g.edges.toGhost.grantee).toBe(g.nodes.ghost);
    expect(g.nodes.ghost.suggestedEin).toBe(IDS.foundation);
    expect(g.edges.toGhost.inferred).toBe(true);
  });

  it("place() marks desiredVisible and reveals grants", () => {
    g.nodes.trust.place(0, 2);
    expect(g.nodes.trust.desiredVisible).toBe(true);
    expect(g.nodes.trust.visibleGrants.length).toBeGreaterThanOrEqual(2);
  });

  it("expandOutflows(1) reveals one hidden outflow", () => {
    g.nodes.trust.desiredVisible = true;
    const before = g.nodes.trust.invisibleGrants.length;
    expect(before).toBe(3);
    g.nodes.trust.expandOutflows(1);
    expect(g.nodes.trust.visibleGrants.length).toBe(1);
    expect(g.nodes.trust.invisibleGrants.length).toBe(2);
  });

  it("hide() clears desiredVisible", () => {
    g.nodes.trust.place(1, 1);
    g.nodes.trust.hide();
    expect(g.nodes.trust.desiredVisible).toBe(false);
  });

  it("propublica990Id is empty without a public.xml name", () => {
    expect(g.nodes.ghost.propublica990Id).toBe("");
    expect(g.nodes.mit.propublica990Id).toBe("");
    expect(g.nodes.leftover.propublica990Id).toBe("");
    expect(g.nodes.trust.propublica990Id).toBeTruthy();
  });
});
