import { describe, expect, it } from "vitest";
import { SankeyBuilderViewModel } from "../viewModel.js";
import { memoryStore } from "../store.js";
import { GraphNode } from "../models.js";
import osf from "../fixtures/osf-alliance.json";
import rogan from "../fixtures/rogan-means-wiles.json";

function vm(doc) {
  const v = new SankeyBuilderViewModel({ store: memoryStore() });
  if (doc) v.loadJSON(doc, { persist: true });
  return v;
}

describe("SankeyBuilderViewModel", () => {
  it("hides non-starting nodes until expanded", () => {
    const v = vm(osf);
    expect(v.visibleNodes().map((n) => n.id).sort()).toEqual(
      ["137029866", "example-alliance"].sort(),
    );
    v.revealNeighbors("example-alliance");
    expect(v.visibleNodes().map((n) => n.id)).toEqual(
      expect.arrayContaining(["jane-example", "us-gov"]),
    );
  });

  it("click modes isolate, expand, and hide", () => {
    const v = vm(osf);
    expect(v.clickMode).toBe("add");
    v.clickNode("example-alliance");
    expect(v.visibleNodes().map((n) => n.id)).toEqual(
      expect.arrayContaining(["jane-example", "us-gov"]),
    );
    v.setClickMode("focus");
    v.clickNode("137029866");
    const focused = v.visibleNodes().map((n) => n.id).sort();
    expect(focused).toEqual(["137029866", "example-alliance"].sort());
    v.setClickMode("subtract");
    v.clickNode("example-alliance");
    expect(v.visibleNodes().map((n) => n.id)).toEqual(["137029866"]);
    v.setClickMode("inspect");
    v.clickNode("137029866", { shiftKey: true });
    expect(v.visibleNodes().map((n) => n.id)).toEqual([]);
  });

  it("inspect click opens a hidden editor for a node or grant", () => {
    const v = vm(osf);
    v.setEditorOpen(false);
    v.setClickMode("inspect");
    v.clickNode("example-alliance");
    expect(v.editorOpen).toBe(true);
    expect(v.selectedId).toBe("example-alliance");
    v.setEditorOpen(false);
    const grant = v.doc.edges.find((e) => e.kind === "grant");
    v.clickEdge(grant.id);
    expect(v.editorOpen).toBe(true);
    expect(v.selectedEdgeId).toBe(grant.id);
    v.setEditorOpen(false);
    v.setClickMode("add");
    v.clickNode("example-alliance", { altKey: true });
    expect(v.editorOpen).toBe(true);
    v.setEditorOpen(false);
    v.clickNode("example-alliance");
    expect(v.editorOpen).toBe(false);
  });

  it("selecting a flow reveals both ends and table lists hidden nodes", () => {
    const v = vm(osf);
    expect(v.visibleNodes().map((n) => n.id)).not.toContain("jane-example");
    const partner = v.doc.edges.find((e) => e.kind === "partner");
    v.setSelectedEdge(partner.id);
    expect(v.selectedEdge().id).toBe(partner.id);
    expect(v.visibleNodes().map((n) => n.id)).toContain("jane-example");
    v.revealAll();
    expect(v.hidden.size).toBe(0);
    v.setView("table");
    expect(v.view).toBe("table");
    expect(v.editorOpen).toBe(true);
    v.setEditorOpen(false);
    expect(v.editorOpen).toBe(false);
    expect(v.controlsOpen).toBe(true);
    v.setControlsOpen(false);
    expect(v.controlsOpen).toBe(false);
    expect(v.circularLinks).toBe(true);
    v.setCircularLinks(false);
    expect(v.circularLinks).toBe(false);
  });

  it("typing govFunds on an existing org synthesizes the implied USG node", () => {
    const v = vm();
    v.upsertNode({ name: "Alpha Fund", kind: "org" });
    expect(v.doc.node("us-gov")).toBeFalsy();
    v.upsertNode({ id: "alpha-fund", name: "Alpha Fund", kind: "org", govFunds: 5000 });
    expect(v.doc.node("us-gov").name).toBe("U.S. government");
    expect(v.doc.node("alpha-fund").govFunds).toBe(5000);
    const grant = v.doc.edges.find((e) => e.from === "us-gov" && e.to === "alpha-fund");
    expect(grant.amount).toBe(5000);
    expect(v.hidden.has("us-gov")).toBe(false);
    v.upsertNode({ id: "alpha-fund", name: "Alpha Fund", kind: "org", govFunds: 9000 });
    expect(
      v.doc.edges.filter((e) => e.from === "us-gov" && e.to === "alpha-fund"),
    ).toHaveLength(1);
    expect(v.doc.edges.find((e) => e.from === "us-gov" && e.to === "alpha-fund").amount).toBe(9000);
  });

  it("adds empty organization and flow rows", () => {
    const v = vm();
    const a = v.addEmptyNode();
    expect(a.name).toBe("Untitled");
    const b = v.addEmptyNode();
    expect(b.name).toBe("Untitled 2");
    const edge = v.addEmptyEdge();
    expect(edge.from).toBeTruthy();
    expect(edge.to).toBeTruthy();
    expect(edge.from).not.toBe(edge.to);
    expect(edge.kind).toBe("grant");
    const empty = vm();
    empty.addEmptyEdge();
    expect(empty.doc.nodes.length).toBeGreaterThanOrEqual(2);
    expect(empty.doc.edges).toHaveLength(1);
  });

  it("keeps contract kinds through upsert and JSON", () => {
    const v = vm();
    v.upsertNode({ name: "DoD", kind: "gov" });
    v.upsertNode({ name: "Acme", kind: "org" });
    v.upsertEdge({ from: "dod", to: "acme", kind: "contract", amount: 99 });
    expect(v.doc.edges[0].kind).toBe("contract");
    expect(v.doc.edges[0].amount).toBe(99);
    expect(v.error).toBe("");
    const json = v.toJSON();
    expect(json.edges[0].kind).toBe("contract");
    const again = vm();
    again.loadJSON(json);
    expect(again.error).toBe("");
    expect(again.doc.edges[0].kind).toBe("contract");
    expect(again.doc.edges[0].amount).toBe(99);
  });

  it("CRUD for orgs and grants round-trips through JSON", () => {
    const v = vm();
    v.upsertNode({ name: "Alpha Fund", kind: "org", ein: "12-3456789" });
    v.upsertNode({ name: "Beta Project", kind: "org" });
    v.upsertEdge({
      from: "123456789",
      to: "beta-project",
      kind: "grant",
      amount: 4000,
    });
    const json = v.toJSON();
    expect(json.nodes).toHaveLength(2);
    expect(json.edges[0].amount).toBe(4000);
    v.deleteEdge(json.edges[0].id);
    v.deleteNode("123456789");
    expect(v.toJSON().nodes).toHaveLength(1);
    expect(v.toJSON().edges).toHaveLength(0);
  });

  it("Grok is always in the inspector; EIN links follow the flags", () => {
    const withEin = new GraphNode({
      id: "137029866",
      name: "Open Society Foundations",
      kind: "org",
      ein: "137029866",
      inspector: {
        propublica: true,
        nonprofit: false,
        award_search: true,
        maps: false,
        google: true,
      },
    });
    const labels = withEin.inspectorLinks().map((l) => l.label);
    expect(labels[0]).toBe("Grok");
    expect(labels).toContain("ProPublica");
    expect(labels).toContain("Federal grants");
    expect(labels).not.toContain("Charity funding");
    expect(labels).not.toContain("Maps");

    const person = new GraphNode({
      id: "susan-wiles",
      name: "Susan Wiles",
      kind: "person",
      inspector: {
        propublica: true,
        nonprofit: true,
        award_search: true,
        maps: true,
        google: true,
      },
    });
    expect(person.inspectorLinks().map((l) => l.label)).toEqual([
      "Grok",
      "Maps",
      "Google",
    ]);
  });

  it("partner edges do not take dollar thickness", () => {
    const v = vm(osf);
    v.revealNeighbors("example-alliance");
    const data = v.getSankeyData();
    const grant = data.links.find((l) => l.kind === "grant" && l.amount === 10500000);
    const partner = data.links.find((l) => l.kind === "partner");
    expect(grant.value).toBe(10500000);
    expect(partner.value).toBe(1);
  });

  it("persists to the store", async () => {
    const store = memoryStore();
    const a = new SankeyBuilderViewModel({ store });
    a.upsertNode({ name: "Kept", kind: "org" });
    const b = new SankeyBuilderViewModel({ store });
    await b.loadLocal();
    expect(b.doc.nodes[0].name).toBe("Kept");
  });

  it("refuses a CORS-blocked article URL", async () => {
    const v = vm();
    const ok = await v.loadFromUrl("https://www.nytimes.com/2024/01/01/us/example.html");
    expect(ok).toBe(false);
    expect(v.error).toMatch(/gist.githubusercontent.com/);
  });

  it("loads a gist raw URL through fetch", async () => {
    const v = new SankeyBuilderViewModel({
      store: memoryStore(),
      fetch: async () => ({
        ok: true,
        text: async () => JSON.stringify(rogan),
      }),
    });
    const ok = await v.loadFromUrl(
      "https://gist.githubusercontent.com/twinforces/abc/raw/graph.json",
    );
    expect(ok).toBe(true);
    expect(v.doc.nodes.map((n) => n.id)).toContain("susan-wiles");
  });

  it("writes a #d= fragment for a small graph", () => {
    const replaced = [];
    const v = new SankeyBuilderViewModel({
      store: memoryStore(),
      location: { pathname: "/sankeybuilder/", search: "", hash: "", origin: "" },
      history: { replaceState: (_s, _t, url) => replaced.push(url) },
    });
    v.upsertNode({ name: "Solo", kind: "person" });
    const token = v.writeFragment();
    expect(token).toBeTruthy();
    expect(replaced[0]).toMatch(/^\/sankeybuilder\/#d=/);
  });
});
