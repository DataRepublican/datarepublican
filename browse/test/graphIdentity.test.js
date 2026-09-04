import { describe, expect, it } from "vitest";
import {
  compareCharities,
  fitScaleWithReadableLabels,
  formatNumber,
  isGraphKey,
  isPatientAssistanceFiler,
  isPatientSubsidyName,
  isPatientSubsidyTarget,
  kindFrom,
  PATIENT_SUBSIDY_ID,
} from "../graphIdentity.js";

const GATES_GHOST_GIN = "70" + "ab".repeat(32);

describe("isGraphKey", () => {
  it("accepts 9-digit EINs and short USG", () => {
    expect(isGraphKey("911663695")).toBe(true);
    expect(isGraphKey("001")).toBe(true);
  });
  it("accepts 66- and 130-char GINs", () => {
    expect(isGraphKey(GATES_GHOST_GIN)).toBe(true);
    expect(GATES_GHOST_GIN).toHaveLength(66);
    expect(isGraphKey("70" + "ab".repeat(64))).toBe(true);
    expect("70" + "ab".repeat(64)).toHaveLength(130);
  });
  it("accepts leftover stubs", () => {
    expect(isGraphKey("etc911663695")).toBe(true);
    expect(isGraphKey(PATIENT_SUBSIDY_ID)).toBe(true);
  });
  it("flags HIPAA / patient-assistance strings from big_pharma_subsidy.json", () => {
    expect(PATIENT_SUBSIDY_ID).toBe("etc997777777");
    expect(isPatientSubsidyName("HIPAA REGULATIONS PREVENT THE LISTING")).toBe(
      true
    );
    expect(isPatientSubsidyName("Individual Patient Programs")).toBe(true);
    expect(isPatientSubsidyName("Eligible Patients (see Schedule #2)")).toBe(
      true
    );
    expect(isPatientSubsidyName("Atch 4")).toBe(true);
    expect(isPatientSubsidyName("DETAILS AVAILABLE UPON REQUEST")).toBe(true);
    expect(isPatientSubsidyName("AMALGAMATED CHARITABLE")).toBe(true);
    expect(isPatientSubsidyName("United Way of Central Indiana")).toBe(false);
    expect(isPatientSubsidyName("Welvista")).toBe(false);
    expect(isPatientSubsidyName("See More")).toBe(false);
    expect(isPatientSubsidyTarget(PATIENT_SUBSIDY_ID, "x", "261437283")).toBe(
      true
    );
    expect(isPatientAssistanceFiler("Pfizer Patient Assistance Foundation Inc")).toBe(
      true
    );
    expect(isPatientAssistanceFiler("Sanofi Cares North America")).toBe(true);
    expect(isPatientAssistanceFiler("Gates Trust")).toBe(false);
  });
  it("rejects junk", () => {
    expect(isGraphKey("SEE")).toBe(false);
    expect(isGraphKey("")).toBe(false);
    expect(isGraphKey("70short")).toBe(false);
  });
});

describe("kindFrom", () => {
  it("reads org_type / xml_name", () => {
    expect(kindFrom({ org_type: "ghost" }, "x")).toBe("ghost");
    expect(kindFrom({ xml_name: "leftover" }, "x")).toBe("leftover");
    expect(kindFrom({ org_type: "backfill" }, "042103594")).toBe("bmf");
  });
  it("infers leftover prefix and GIN length", () => {
    expect(kindFrom({}, "etc911663695")).toBe("leftover");
    expect(kindFrom({}, GATES_GHOST_GIN)).toBe("ghost");
  });
  it("defaults to charity", () => {
    expect(kindFrom({ org_type: "501(c)(3)", xml_name: "a_public.xml" }, "911663695")).toBe(
      "charity",
    );
  });
});

describe("formatNumber", () => {
  it("scales dollars", () => {
    expect(formatNumber(42e9)).toBe("42.0B");
    expect(formatNumber(5e6)).toBe("5.0M");
  });
});

describe("compareCharities", () => {
  it("sorts by combined grant volume then name", () => {
    const a = { grantsInTotal: 1, grantsTotal: 1, name: "B" };
    const b = { grantsInTotal: 10, grantsTotal: 0, name: "A" };
    expect(compareCharities(b, a)).toBeLessThan(0);
  });
});

describe("fitScaleWithReadableLabels", () => {
  it("does not zoom out past a 13px screen font", () => {
    expect(fitScaleWithReadableLabels(0.1, 48, 13)).toBeCloseTo(13 / 48);
    expect(fitScaleWithReadableLabels(0.5, 48, 13)).toBe(0.5);
  });
});
