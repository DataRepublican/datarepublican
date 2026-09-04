import {
  BrowseViewModel,
  Charity,
  Grant,
  resetGraph,
} from "../models.js";

/** Valid 66-char GIN (70 + 64 hex). */
export const GATES_GHOST_GIN = "70" + "ab".repeat(32);

export const IDS = {
  usg: "001",
  trust: "911663695",
  foundation: "562618866",
  ghost: GATES_GHOST_GIN,
  leftover: "etc911663695",
  mit: "042103594",
};

function rowFor(kind, extra = {}) {
  const xml =
    kind === "ghost"
      ? "ghost"
      : kind === "leftover"
        ? "leftover"
        : kind === "bmf"
          ? "backfill"
          : "2024_public.xml";
  const org =
    kind === "charity" ? "501(c)(3)" : kind === "bmf" ? "backfill" : kind;
  return {
    org_type: org,
    xml_name: xml,
    tax_year: 2024,
    form_type: kind === "charity" ? "990PF" : "",
    total_assets: 1,
    denominator: 1,
    ...extra,
  };
}

function makeCharity({ ein, name, kind, govt_amt = 0, receipt_amt = 0 }) {
  return new Charity({
    ein,
    name,
    xml_name: rowFor(kind).xml_name,
    govt_amt,
    receipt_amt,
    contrib_amt: 0,
    row: rowFor(kind),
  });
}

export function buildGatesGraph(urlAdapter = { replace() {} }) {
  resetGraph();
  const vm = new BrowseViewModel({ urlAdapter });
  const nodes = {
    usg: makeCharity({
      ein: IDS.usg,
      name: "US Government",
      kind: "charity",
      govt_amt: 0,
    }),
    trust: makeCharity({
      ein: IDS.trust,
      name: "Gates Trust",
      kind: "charity",
      receipt_amt: 50e9,
    }),
    foundation: makeCharity({
      ein: IDS.foundation,
      name: "Gates Foundation",
      kind: "charity",
      receipt_amt: 40e9,
    }),
    ghost: makeCharity({
      ein: IDS.ghost,
      name: "GATES FOUNDATION",
      kind: "ghost",
    }),
    leftover: makeCharity({
      ein: IDS.leftover,
      name: "see more",
      kind: "leftover",
    }),
    mit: makeCharity({
      ein: IDS.mit,
      name: "Massachusetts Institute of Technology",
      kind: "bmf",
    }),
  };
  const edges = {
    toGhost: new Grant({
      filer_ein: IDS.trust,
      grant_ein: IDS.ghost,
      amt: 42e9,
      inferred: true,
      suggested_ein: IDS.foundation,
    }),
    toLeftover: new Grant({
      filer_ein: IDS.trust,
      grant_ein: IDS.leftover,
      amt: 5e6,
    }),
    toMit: new Grant({
      filer_ein: IDS.trust,
      grant_ein: IDS.mit,
      amt: 10e6,
    }),
  };
  return { vm, nodes, edges };
}
