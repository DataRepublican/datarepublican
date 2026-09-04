/**
 * Pure graph identity — no DOM, IDB, or D3.
 * Charity kinds and keys for /browse (EIN, GIN, leftover stub).
 */

import subsidySpec from "./big_pharma_subsidy.js";

function escapeRegExp(s) {
  return String(s).replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
}

function subsidyBlock(spec) {
  return (spec && (spec["BIG PHARMA SUBSIDY"] || spec)) || {};
}

function compileSubsidyPatterns(spec) {
  const patterns = subsidyBlock(spec).patterns || [];
  const compiled = [];
  for (const pat of patterns) {
    try {
      compiled.push(new RegExp(String(pat), "i"));
    } catch {
      compiled.push(new RegExp(escapeRegExp(String(pat)), "i"));
    }
  }
  return compiled;
}

const SUBSIDY_PATTERNS = compileSubsidyPatterns(subsidySpec);

export function formatNumber(num) {
  if (num >= 1e12) return (num / 1e12).toFixed(1) + "T";
  if (num >= 1e9) return (num / 1e9).toFixed(1) + "B";
  if (num >= 1e6) return (num / 1e6).toFixed(1) + "M";
  if (num >= 1e3) return (num / 1e3).toFixed(1) + "K";
  return num == null ? "N/A" : num.toString();
}

/** 9-digit EIN, GIN (70+sha), or leftover stub etcXXXXXXXXX */
export function isGraphKey(id) {
  if (!id) return false;
  if (/^[0-9]{3,9}$/.test(id)) return true;
  if (/^70[0-9a-fA-F]{64}$/.test(id)) return true;
  if (/^70[0-9a-fA-F]{128}$/.test(id)) return true;
  if (/^etc[0-9]{9}$/.test(id)) return true;
  return false;
}

export function kindFrom(row, ein) {
  const org = (row && row.org_type) || "";
  const xml = (row && row.xml_name) || "";
  if (org === "ghost" || xml === "ghost") return "ghost";
  if (org === "leftover" || xml === "leftover") return "leftover";
  if (org === "backfill" || xml === "backfill") return "bmf";
  if (ein && /^etc[0-9]{9}$/.test(ein)) return "leftover";
  if (ein && (ein.length === 66 || ein.length === 130) && ein.startsWith("70"))
    return "ghost";
  return "charity";
}

const subsidyDigits = String(
  subsidyBlock(subsidySpec).synthetic_ein || "997777777",
).replace(/\D/g, "");
export const PATIENT_SUBSIDY_ID = `etc${subsidyDigits.padStart(9, "0")}`;

export function isPatientSubsidyName(name) {
  if (!name) return false;
  const text = String(name);
  return SUBSIDY_PATTERNS.some((rx) => rx.test(text));
}

/** HIPAA/patient-redacted ghosts or the shared sink. Leftover stubs are handled separately. */
export function isPatientSubsidyTarget(id, name, _filerEin) {
  if (id === PATIENT_SUBSIDY_ID) return true;
  return isPatientSubsidyName(name);
}

/** Manufacturer PAPs whose unnamed remainder is copay / patient assistance. */
export function isPatientAssistanceFiler(name) {
  if (!name) return false;
  return /patient (assistance|access|foundation)|safety net|cares (foundation|north america)/i.test(
    String(name),
  );
}

export function compareCharities(a, b) {
  return (
    b.grantsInTotal + b.grantsTotal - (a.grantsInTotal + a.grantsTotal) ||
    a.name.localeCompare(b.name)
  );
}

export function compareLinks(a, b) {
  return b.value - a.value;
}

/** Keep zoom-to-fit from shrinking SVG labels below minScreenPx. */
export function fitScaleWithReadableLabels(
  fitScale,
  svgFontPx,
  minScreenPx = 13
) {
  if (!Number.isFinite(fitScale) || fitScale <= 0) return fitScale;
  if (!Number.isFinite(svgFontPx) || svgFontPx <= 0) return fitScale;
  return Math.max(fitScale, minScreenPx / svgFontPx);
}
