import { describe, expect, it } from "vitest";
import { DATA_FILES, idbDataIsCurrent } from "../data_files.js";

describe("idbDataIsCurrent", () => {
  const v = DATA_FILES.dbVersion;

  it("accepts a finished store at the published dbVersion", () => {
    expect(idbDataIsCurrent(v, true)).toBe(true);
  });

  it("rejects a version bump so loadData can wipe and refetch", () => {
    expect(idbDataIsCurrent("2026-09-03T17:26:39Z", true, v)).toBe(false);
  });

  it("rejects a store that never finished ingest", () => {
    expect(idbDataIsCurrent(v, undefined)).toBe(false);
    expect(idbDataIsCurrent(v, false)).toBe(false);
    expect(idbDataIsCurrent(v, "true")).toBe(false);
  });

  it("rejects an empty metadata store", () => {
    expect(idbDataIsCurrent(undefined, undefined)).toBe(false);
  });
});
