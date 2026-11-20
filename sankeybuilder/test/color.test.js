import { describe, expect, it } from "vitest";
import { colorKeyFor, getColorForId, hashId } from "../color.js";

describe("color", () => {
  it("keys off EIN when present, otherwise the slug", () => {
    expect(colorKeyFor({ ein: "137029866", id: "osf" })).toBe("137029866");
    expect(colorKeyFor({ id: "susan-wiles" })).toBe("susan-wiles");
  });

  it("is stable for the same id and differs across ids", () => {
    expect(hashId("susan-wiles")).toBe(hashId("susan-wiles"));
    expect(hashId("susan-wiles")).not.toBe(hashId("casey-means"));
    expect(getColorForId("susan-wiles")).toBeTruthy();
  });
});
