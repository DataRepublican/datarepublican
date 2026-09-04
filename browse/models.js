const POWER_LAW_RESET = 3;
const TOP_N_INITIAL = 5;
const START_REVEAL = 5;
const MAX_EXPAND_SCALE = 4096;
const MIN_EXPAND_SCALE = 1.5;
const EXPAND_FACTOR = 1.25;

const MIN_REVEAL = 2;
const NEXT_REVEAL = 3;
const NEXT_REVEAL_MAX = 15;
const GOV_EIN = "001";
const MAX_NODES = 100;
const STORE_CHUNK_SIZE = 10000;
const PROCESS_CHUNK_SIZE = 10000;
const CHUNK_SIZE = 10000;

const MAX_KEYWORD_NODES = 100;

const DB_NAME = "CharityDatabase";
const DB_VERSION = 1;
const CHARITY_STORE = "charities";
const GRANT_STORE = "grants";
const METADATA_STORE = "metadata";
const DATA_VERSION = "2026-09-02";
/** Sanity floor after the $10M band export (~104k orgs / ~580k grants), not the old 910k dump. */
const MIN_LOADED_CHARITIES = 10000;
const MIN_LOADED_GRANTS = 10000;
const BALANCELIMIT = 20;
const PER_COL = 3;
const PER_ROW = 3;

import { DATA_FILES } from "./data_files.js"; // Adjust path if needed

export const BAND_ORDER = ["10M", "1M", "all"];

export function browseBands() {
  return DATA_FILES.bands || [];
}

export function defaultBandId() {
  return DATA_FILES.defaultBand || "10M";
}

export function bandById(id) {
  return browseBands().find((b) => b.id === id) || null;
}

export function bandIndex(id) {
  const i = BAND_ORDER.indexOf(id);
  return i < 0 ? 0 : i;
}

export function canUpgradeBand(fromId, toId) {
  return bandIndex(toId) > bandIndex(fromId);
}

export function bandHasFiles(band) {
  if (!band || band.available === false) return false;
  const files = band.files || [];
  return files.some((f) => (f.chunkCount || 0) > 0);
}

/** Next deeper band that this origin actually hosts. */
export function nextHostedBandId(fromId) {
  const start = bandIndex(fromId);
  for (const b of browseBands()) {
    if (bandIndex(b.id) > start && bandHasFiles(b)) return b.id;
  }
  return null;
}

export function filesForBand(id) {
  const band = bandById(id);
  if (bandHasFiles(band)) return band.files;
  if (id === defaultBandId() || id === "10M") return DATA_FILES.files || [];
  return [];
}

export function bandCutLabel(id) {
  return (bandById(id) || bandById(defaultBandId()) || { label: "$10M" }).label;
}

export function formatDuration(ms) {
  if (!Number.isFinite(ms) || ms < 0) return "";
  if (ms < 1000) return `${Math.round(ms)}ms`;
  const s = ms / 1000;
  if (s < 90) return `${s < 10 ? s.toFixed(1) : Math.round(s)}s`;
  const m = Math.floor(s / 60);
  const r = Math.round(s - m * 60);
  return r ? `${m}m ${r}s` : `${m}m`;
}

const LOAD_TIME_KEY = "browseBandLoadMs";

export function recordBandLoadMs(bandId, source, ms) {
  if (typeof localStorage === "undefined" || !bandId || !Number.isFinite(ms))
    return;
  try {
    const all = JSON.parse(localStorage.getItem(LOAD_TIME_KEY) || "{}");
    const ver = DATA_FILES.dbVersion || "";
    if (!all[ver]) all[ver] = {};
    if (!all[ver][bandId]) all[ver][bandId] = {};
    all[ver][bandId][source] = Math.round(ms);
    localStorage.setItem(LOAD_TIME_KEY, JSON.stringify(all));
  } catch (e) {
    /* quota / private mode */
  }
}

export function lastBandLoadMs(bandId, source) {
  if (typeof localStorage === "undefined") return null;
  try {
    const all = JSON.parse(localStorage.getItem(LOAD_TIME_KEY) || "{}");
    const ver = DATA_FILES.dbVersion || "";
    const ms = all[ver] && all[ver][bandId] && all[ver][bandId][source];
    return Number.isFinite(ms) ? ms : null;
  } catch (e) {
    return null;
  }
}

/** This machine's $10M wait. Prefer first download; IDB reload is the fallback. */
export function tenMLoadMs() {
  return lastBandLoadMs("10M", "web") || lastBandLoadMs("10M", "idb");
}

/**
 * Scale the measured $10M load by zip bytes.
 * Origin (Vercel vs DreamHost) is ignored — unzip+IDB dominates, and we
 * only have one timed wait per visitor.
 */
export function estimateBandLoadMs(bandId) {
  const base = tenMLoadMs();
  const from = bandById("10M");
  const to = bandById(bandId);
  if (!base || !from || !to || bandId === "10M") return base;
  if (!from.zipBytes || !to.zipBytes) return null;
  return Math.round(base * (to.zipBytes / from.zipBytes));
}

import ORGANIZATION_TYPES from "./charityTypes.js";
import { iso3166_alpha2 } from "./countryCodes.js";
import { openDB } from "https://cdn.jsdelivr.net/npm/idb@8/+esm";
import JSZip from "https://cdn.jsdelivr.net/npm/jszip@3.10.1/+esm";
import presetsData from "./presets.js";
import {
  compareCharities,
  compareLinks,
  fitScaleWithReadableLabels,
  formatNumber,
  isGraphKey,
  kindFrom,
  PATIENT_SUBSIDY_ID,
} from "./graphIdentity.js";

export {
  compareCharities,
  compareLinks,
  fitScaleWithReadableLabels,
  formatNumber,
  isGraphKey,
  kindFrom,
  PATIENT_SUBSIDY_ID,
};
let DEBUGLOG = false;
let DEBUGSTOP = false;

let GOV_NODE = null; // I use this when debugging.
let colorOffest = 0;
const d3Array =
  (typeof window !== "undefined" && window.d3) || {
    max: (arr, acc) => {
      const vals = acc ? arr.map(acc) : arr;
      return Math.max(...vals.filter((x) => x != null && Number.isFinite(x)));
    },
  };

/**
 * Tried logarithmic scaling, but it was too drastic 1M vs. 1B was 3. 
 * Power law scaling is more natural, default of cube root means
 * it looks like this:
 * 
 * Steps    Power Law (x^(1/3))    Logarithmic (ln(x))
1K       10                     6.9078
1M       100                    13.8155
1B       1,000                  20.7233
1T       10,000                 27.6310

 * @param {*} amt 
 * @returns 
 */
export function scaleValue(amt) {
  return Math.pow(amt, 1 / viewModel.POWER_LAW);
}

/**
 * As they say in Highlander, there can be only one
 */
let viewModel = null;

function hashEIN(ein) {
  let hash = 2862953042; // so 001 is greenish
  const paddedEin = ein.length === 3 ? ein.padEnd(9, "0") : ein; // Pad 3-digit EINs
  for (let i = 0; i < paddedEin.length; i++) {
    const weight = i < 2 ? 2 : 1; // Weight IRS office digits
    hash ^= paddedEin.charCodeAt(i) * weight;
    hash = (hash * 16777619) >>> 0;
  }
  return (hash % 1000000) / 1000000;
}

function interpolateBand(t, baseBrightness, mod_brightness) {
  const abs_diff = Math.abs(t - 0.5);
  const brightness = Math.max(0.05, baseBrightness - mod_brightness * abs_diff); // Clamp min brightness
  const saturation = 1.5 - 1.5 * abs_diff; // Original fixed saturation
  return d3.cubehelix(
    360 * t - 65, // Tuned offset to make 001 (t~0.55) hue ~133 (forest green)
    saturation,
    brightness
  );
}

const brightnessBands = [
  { base: 0.7, mod: 0.8 }, // 0: pastel (light)
  { base: 0.5, mod: 0.6 }, // 1: medium
  { base: 0.4, mod: 0.3 }, // 2: dark (~0.3 center)
  { base: 0.3, mod: 0.2 }, // 3: extra dark (~0.23 center)
];

const bandOffset = 1; // Tuned: lastDigit=1 +1 %4=2 -> dark for node

function colorBandIndex(ein) {
  const lastDigit = parseInt(ein.slice(-1), 10);
  const n = Number.isFinite(lastDigit)
    ? lastDigit
    : ein.charCodeAt(ein.length - 1);
  return (n + bandOffset) % 4;
}

export function getColorForEIN(ein) {
  let t = hashEIN(ein);
  let bandIndex = colorBandIndex(ein);
  const brightBand = brightnessBands[bandIndex];
  return interpolateBand(t, brightBand.base, brightBand.mod);
}

export function getTextColorForEIN(ein) {
  let t = hashEIN(ein);
  let bandIndex = colorBandIndex(ein) + 1; // One darker
  bandIndex = Math.min(3, bandIndex); // Cap at extra dark (no wrap to light for contrast)
  const brightBand = brightnessBands[bandIndex];
  return interpolateBand(t, brightBand.base, brightBand.mod);
}

export function interpolateBandIndex(t, band) {
  return interpolateBand(t, colorBands[band].base, colorBands[band].mod);
}

// Initialize IndexedDB

async function initDB() {
  if (DEBUGLOG) console.log("Opening IndexedDB: CharityDatabase");
  // Close any existing connections
  const existingDBs = indexedDB.databases ? await indexedDB.databases() : [];
  for (const dbInfo of existingDBs) {
    if (dbInfo.name === "CharityDatabase") {
      if (DEBUGLOG) console.log("Closing existing CharityDatabase connection");
      await new Promise((resolve) => {
        const request = indexedDB.open(dbInfo.name);
        request.onsuccess = () => {
          request.result.close();
          resolve();
        };
      });
    }
  }

  return new Promise((resolve, reject) => {
    const request = indexedDB.open("CharityDatabase", 1);
    request.onupgradeneeded = (event) => {
      const db = event.target.result;
      if (DEBUGLOG) console.log("Creating or upgrading IndexedDB stores...");
      if (db.objectStoreNames.contains(CHARITY_STORE)) {
        db.deleteObjectStore(CHARITY_STORE);
        if (DEBUGLOG) console.log(`Deleted existing ${CHARITY_STORE} store`);
      }
      if (db.objectStoreNames.contains(GRANT_STORE)) {
        db.deleteObjectStore(GRANT_STORE);
        if (DEBUGLOG) console.log(`Deleted existing ${GRANT_STORE} store`);
      }
      if (db.objectStoreNames.contains(METADATA_STORE)) {
        db.deleteObjectStore(METADATA_STORE);
        if (DEBUGLOG) console.log(`Deleted existing ${METADATA_STORE} store`);
      }
      db.createObjectStore(CHARITY_STORE, { keyPath: "filer_ein" });
      if (DEBUGLOG)
        console.log(`Created ${CHARITY_STORE} store with keyPath: filer_ein`);
      db.createObjectStore(GRANT_STORE, { keyPath: "id" });
      if (DEBUGLOG)
        console.log(`Created ${GRANT_STORE} store with keyPath: id`);
      db.createObjectStore(METADATA_STORE, { keyPath: "id" });
      if (DEBUGLOG)
        console.log(`Created ${METADATA_STORE} store with keyPath: id`);
    };
    request.onsuccess = () => {
      if (DEBUGLOG) console.log("IndexedDB opened successfully");
      resolve(request.result);
    };
    request.onerror = () => {
      if (DEBUGLOG) console.error("Failed to open IndexedDB:", request.error);
      reject(request.error);
    };
  });
}

async function clearStorage() {
  try {
    const db = await initDB();
    const tx = db.transaction(
      [CHARITY_STORE, GRANT_STORE, METADATA_STORE],
      "readwrite"
    );
    updateStatus("clearing store", "orange");
    await tx.objectStore(CHARITY_STORE).clear();
    await tx.objectStore(GRANT_STORE).clear();
    await tx.objectStore(METADATA_STORE).clear();
    await tx.done;
    Charity.charityLookup = {};
    Grant.grantLookup = {};
    updateStatus("Local storage cleared, reloading data...", "black", true);
    await viewModel.loadData();
  } catch (err) {
    console.error("Error clearing storage:", err);
    updateStatus(`Error clearing storage: ${err.message}`, "red", false);
    throw err;
  }
}

function idbCount(db, storeName) {
  return new Promise((resolve, reject) => {
    const tx = db.transaction(storeName, "readonly");
    const request = tx.objectStore(storeName).count();
    request.onsuccess = () => resolve(request.result || 0);
    request.onerror = () => reject(request.error);
  });
}

function idbGetMeta(db, id) {
  return new Promise((resolve, reject) => {
    const tx = db.transaction(METADATA_STORE, "readonly");
    const request = tx.objectStore(METADATA_STORE).get(id);
    request.onsuccess = () => resolve(request.result?.value);
    request.onerror = () => reject(request.error);
  });
}

async function idbPutMeta(db, entries) {
  const tx = db.transaction(METADATA_STORE, "readwrite");
  const store = tx.objectStore(METADATA_STORE);
  await Promise.all(
    Object.entries(entries).map(
      ([id, value]) =>
        new Promise((resolve, reject) => {
          const request = store.put({ id, value });
          request.onsuccess = resolve;
          request.onerror = () => reject(request.error);
        })
    )
  );
  await tx.done;
}

async function hasValidData(db) {
  try {
    const versionRequest = await idbGetMeta(db, "version");
    const generatedRequest = await idbGetMeta(db, "generated");
    if (
      versionRequest !== DATA_FILES.dbVersion ||
      generatedRequest !== true
    ) {
      return false;
    }
    const nCharities = await idbCount(db, CHARITY_STORE);
    const nGrants = await idbCount(db, GRANT_STORE);
    if (nCharities < MIN_LOADED_CHARITIES || nGrants < MIN_LOADED_GRANTS) {
      console.warn(
        `IndexedDB incomplete (${nCharities} charities, ${nGrants} grants); reloading`
      );
      return false;
    }
    loadingViaDB();
    return true;
  } catch (error) {
    console.error("Error checking hasValidData:", error);
    return false;
  }
}

// Fetch data from IndexedDB
async function fetchLocalData(db, storeName) {
  try {
    const tx = db.transaction(storeName, "readonly");
    const store = tx.objectStore(storeName);
    const records = [];
    const cursorRequest = store.openCursor();

    await new Promise((resolve, reject) => {
      cursorRequest.onsuccess = (event) => {
        const cursor = event.target.result;
        if (cursor) {
          records.push(cursor.value);
          cursor.continue();
        } else {
          resolve();
        }
      };
      cursorRequest.onerror = () => reject(cursorRequest.error);
    });

    await tx.done;
    if (DEBUGLOG)
      console.log(`Retrieved ${records.length} records from ${storeName}`);
    return records;
  } catch (error) {
    console.error(`Error fetching data from ${storeName}:`, error);
    throw error;
  }
}

async function storeData(db, storeName, records) {
  if (!db) {
    throw new Error(`Database is undefined in storeData for ${storeName}`);
  }
  if (!storeName) {
    throw new Error(`storeName is undefined in storeData`);
  }
  if (!Array.isArray(records)) {
    throw new Error(
      `Records is not an array in storeData for ${storeName}: ${JSON.stringify(
        records
      )}`
    );
  }
  if (!db.objectStoreNames.contains(storeName)) {
    throw new Error(`Store ${storeName} does not exist in database`);
  }

  try {
    if (DEBUGLOG) console.time(`storeD-${storeName}`);
    const tx = db.transaction(storeName, "readwrite");
    const store = tx.objectStore(storeName);
    let storedRecords = 0;

    for (const record of records) {
      store.put(record);
      storedRecords++;
    }

    await new Promise((resolve, reject) => {
      tx.oncomplete = () => resolve();
      tx.onabort = () =>
        reject(new Error(`Transaction aborted for ${storeName}`));
      tx.onerror = () => reject(tx.error);
    });

    if (DEBUGLOG) console.timeEnd(`storeD-${storeName}`);
    return storedRecords;
  } catch (err) {
    console.error(`Error storing data in ${storeName}:`, err);
    updateStatus(`Error storing ${storeName}: ${err.message}`, "red", false);
    throw err;
  }
}

async function clearGraphStores(db) {
  const tx = db.transaction([CHARITY_STORE, GRANT_STORE], "readwrite");
  await tx.objectStore(CHARITY_STORE).clear();
  await tx.objectStore(GRANT_STORE).clear();
  await tx.done;
}

async function exportDB() {
  try {
    const db = await initDB();
    const tx = db.transaction(
      [CHARITY_STORE, GRANT_STORE, METADATA_STORE],
      "readonly"
    );
    const charities = await tx.objectStore(CHARITY_STORE).getAll();
    const grants = await tx.objectStore(GRANT_STORE).getAll();
    const metadata = await tx.objectStore(METADATA_STORE).getAll();
    await tx.done;

    // Export charities
    const charitiesBlob = new Blob([JSON.stringify({ charities })], {
      type: "application/json",
    });
    const charitiesUrl = URL.createObjectURL(charitiesBlob);
    const charitiesA = document.createElement("a");
    charitiesA.href = charitiesUrl;
    charitiesA.download = "charities_db.json";
    charitiesA.click();
    URL.revokeObjectURL(charitiesUrl);

    // Export grants
    const grantsBlob = new Blob([JSON.stringify({ grants })], {
      type: "application/json",
    });
    const grantsUrl = URL.createObjectURL(grantsBlob);
    const grantsA = document.createElement("a");
    grantsA.href = grantsUrl;
    grantsA.download = "grants_db.json";
    grantsA.click();
    URL.revokeObjectURL(grantsUrl);

    // Export metadata
    const metadataBlob = new Blob([JSON.stringify({ metadata })], {
      type: "application/json",
    });
    const metadataUrl = URL.createObjectURL(metadataBlob);
    const metadataA = document.createElement("a");
    metadataA.href = metadataUrl;
    metadataA.download = "metadata_db.json";
    metadataA.click();
    URL.revokeObjectURL(metadataUrl);

    updateStatus("Database exported successfully", "green", false);
  } catch (err) {
    console.error("Error exporting database:", err);
    updateStatus(`Error exporting database: ${err.message}`, "red", false);
    throw err;
  }
}

async function fetchAndStoreTSV(db, files) {
  try {
    if (!Array.isArray(files)) {
      throw new Error(
        `files parameter is not an array: ${JSON.stringify(files)}`
      );
    }
    updateStatus(`Fetching charities and grants...`);
    let charityRowsProcessed = 0;
    let charityRowsSkipped = 0;
    let grantRowsProcessed = 0;
    let grantRowsSkipped = 0;
    const BATCH_SIZE = STORE_CHUNK_SIZE;
    const MAX_CONCURRENT = 16;
    let writeChain = Promise.resolve();
    const enqueueWrite = (fn) => {
      const next = writeChain.then(fn, fn);
      writeChain = next.catch(() => {});
      return next;
    };

    async function processChunk({
      tsvText,
      tsvFile,
      chunkIndex,
      type,
      grantType,
    }) {
      const lines = tsvText.split("\n").filter((line) => line.trim());
      if (lines.length < 1) {
        return { processed: 0, skipped: 0 };
      }
      const headers = lines[0].split("\t").map((header) => header.trim());
      const expectedColumns =
        type === "charities"
          ? [
              "filer_ein",
              "filer_name",
              "xml_name",
              "receipt_amt",
              "govt_amt",
              "contrib_amt",
              "tax_year",
              "org_type",
              "total_assets",
              "form_type",
              "denominator",
            ]
          : ["filer_ein", "grant_ein", "grant_amt"]; // inferred, suggested_ein optional extra
      const columnMap = {};
      headers.forEach((header, i) => {
        columnMap[header] = i;
      });

      const missingColumns = expectedColumns.filter(
        (col) => !(col in columnMap)
      );
      if (missingColumns.length > 0) {
        return { processed: 0, skipped: 0 };
      }

      const records = [];
      let rowsProcessed = 0;
      let rowsSkipped = 0;

      for (
        let startIndex = 1;
        startIndex < lines.length;
        startIndex += BATCH_SIZE
      ) {
        const endIndex = Math.min(startIndex + BATCH_SIZE, lines.length);
        let row;
        try {
          if (DEBUGLOG) console.time(`processTSV-${tsvFile}-${startIndex}`);
          for (let index = startIndex; index < endIndex; index++) {
            const values = lines[index]
              .split("\t")
              .map((value) => (value ? value.trim() : ""));
            if (values.length < expectedColumns.length) {
              rowsSkipped++;
              continue;
            }
            row = {};
            headers.forEach((header) => {
              row[header] =
                columnMap[header] < values.length
                  ? values[columnMap[header]]
                  : "";
            });

            if (type === "charities") {
              const charity = {
                filer_ein: row.filer_ein,
                filer_name: row.filer_name || "",
                name: row.filer_name || "",
                xml_name: row.xml_name || "",
                receipt_amt: parseInt(row.receipt_amt || "0", 10) || 0,
                govt_amt: parseInt(row.govt_amt || "0", 10) || 0,
                contrib_amt: parseInt(row.contrib_amt || "0", 10) || 0,
                tax_year: row.tax_year ? parseInt(row.tax_year, 10) : "N/A",
                org_type: row.org_type || null,
                total_assets: row.total_assets
                  ? parseFloat(row.total_assets)
                  : null,
                form_type: row.form_type || null,
                denominator: row.denominator
                  ? parseFloat(row.denominator)
                  : null,
                street: row.street || "",
                city: row.city || "",
                state: row.state || "",
                zip: row.zip || "",
              };
              if (!charity.filer_ein || !isGraphKey(charity.filer_ein)) {
                rowsSkipped++;
                continue;
              }
              if (
                charity.xml_name &&
                charity.org_type !== "backfill" &&
                charity.org_type !== "ghost" &&
                charity.org_type !== "leftover" &&
                !/.*\.xml$|^backfill$|^ghost$|^leftover$/.test(charity.xml_name)
              ) {
                rowsSkipped++;
                continue;
              }
              records.push(charity);
              try {
                Charity.buildCharityFromRow(charity);
              } catch (buildError) {
                rowsSkipped++;
                continue;
              }
              rowsProcessed++;
            } else {
              let grant_ein = row.grant_ein;
              let filer_ein = row.filer_ein;
              if (grant_ein?.length === 7) grant_ein = "0" + grant_ein;
              if (filer_ein?.length === 7) filer_ein = "0" + filer_ein;
              const grant = {
                id: `${filer_ein}~${grant_ein}`,
                filer_ein,
                grant_ein,
                amt: parseInt(row.grant_amt || row.amt || "0", 10) || 0,
                grantType,
                inferred: row.inferred === "1" || row.inferred === "true",
                suggested_ein: row.suggested_ein || "",
              };
              if (
                grant.filer_ein &&
                grant.grant_ein &&
                grant.filer_ein !== grant.grant_ein &&
                isGraphKey(grant.grant_ein)
              ) {
                records.push(grant);
                Grant.loadGrantRow(grant, grantType);
                rowsProcessed++;
              } else {
                rowsSkipped++;
              }
            }
          }
          if (DEBUGLOG) console.timeEnd(`processTSV-${tsvFile}-${startIndex}`);

          if (records.length > 0) {
            const batch = records.splice(0, records.length);
            if (DEBUGLOG) console.time(`storeTSV-${tsvFile}-${startIndex}`);
            try {
              await enqueueWrite(() =>
                storeData(
                  db,
                  type === "charities" ? CHARITY_STORE : GRANT_STORE,
                  batch
                )
              );
            } catch (storeError) {
              console.error(
                `Failed to store ${type} for chunk ${chunkIndex}:`,
                storeError
              );
              throw storeError;
            }
            if (DEBUGLOG) console.timeEnd(`storeTSV-${tsvFile}-${startIndex}`);
          }
          updateStatus(
            `Loaded ${formatNumber(
              Object.keys(Charity.charityLookup).length
            )} charities, ${formatNumber(
              Object.keys(Grant.grantLookup).length
            )} grants`
          );
        } catch (err) {
          console.error(
            `Error in batch for ${tsvFile} at row ${rowsProcessed}:`,
            err
          );
          throw err;
        }
      }
      return { processed: rowsProcessed, skipped: rowsSkipped };
    }

    async function fetchAndProcessChunk(file, type, grantType, chunkIndex) {
      const zipFile = `${file.baseFile}${chunkIndex}.tsv.zip`;
      const tsvFile = `${file.tsvFilePrefix}${chunkIndex}.tsv`;
      try {
        const response = await fetch(zipFile);
        if (!response.ok) {
          if (response.status === 404) {
            return null;
          }
          throw new Error(`HTTP error ${response.status} for ${zipFile}`);
        }
        const zipBlob = await response.blob();
        const zip = await JSZip.loadAsync(zipBlob);
        const tsv = zip.file(tsvFile);
        if (!tsv) {
          return null;
        }
        const tsvText = await tsv.async("text");
        return await processChunk({
          tsvText,
          tsvFile,
          chunkIndex,
          type,
          grantType,
        });
      } catch (error) {
        console.error(`Error fetching ${zipFile}:`, error);
        return null;
      }
    }

    async function runPool(jobs, limit, worker) {
      const results = new Array(jobs.length);
      let next = 0;
      let done = 0;
      const total = jobs.length;
      async function runOne() {
        while (next < jobs.length) {
          const idx = next++;
          results[idx] = await worker(jobs[idx], idx);
          done++;
          if (done === 1 || done % 8 === 0 || done === total) {
            updateStatus(
              `Loading ${bandCutLabel(viewModel?.loadedBand || defaultBandId())}: ${done}/${total} files, ${formatNumber(
                Object.keys(Charity.charityLookup).length
              )} orgs, ${formatNumber(Object.keys(Grant.grantLookup).length)} grants`
            );
          }
        }
      }
      const n = Math.min(limit, jobs.length) || 1;
      await Promise.all(Array.from({ length: n }, () => runOne()));
      return results;
    }

    const jobs = [];
    for (const file of files) {
      const maxChunks = file.chunkCount || 0;
      for (let chunkIndex = 0; chunkIndex < maxChunks; chunkIndex++) {
        jobs.push({ file, chunkIndex });
      }
    }
    {
      const results = await runPool(jobs, MAX_CONCURRENT, ({ file, chunkIndex }) =>
        fetchAndProcessChunk(file, file.type, file.grantType, chunkIndex)
      );
      for (let i = 0; i < results.length; i++) {
        const result = results[i];
        const file = jobs[i].file;
        if (result) {
          if (file.type === "charities") {
            charityRowsProcessed += result.processed;
            charityRowsSkipped += result.skipped;
          } else {
            grantRowsProcessed += result.processed;
            grantRowsSkipped += result.skipped;
          }
        }
      }
    }

    await writeChain;
    return [];
  } catch (error) {
    console.error(`Error processing files:`, error);
    updateStatus(`Error loading data: ${error.message}`, "red", false);
    throw error;
  }
}
/**
 * So this is an M-V-VM architecture.
 * M - Model, deals with the data
 * V = View, displays the data
 * VM = View Model, translates between M and V.
 *
 * I've tried MVC, didn't work. MVVM does.
 */
export class BrowseViewModel {
  #_presetsData = presetsData; // Private field initialized with imported presets

  constructor({
    POWER_LAW = POWER_LAW_RESET,
    GOV_EIN = "001",
    urlAdapter = null,
  } = {}) {
    this.POWER_LAW = POWER_LAW; /** Users can change the scaling on the fly */
    this.GOV_EIN =
      GOV_EIN; /** Had to pick something, it was this or 0000000001  */
    this.GOV_NODE = null; /** keep this around for debugging */

    /**
     * Ok, a lot of the work between the M and the V is about maintaining visibilitiy.
     * Nominally, we start with 100,000 nodes, 660,000 edges.
     * We need to capture things the user wants (showList) and things they don't want
     * hideList. keywords is another way to specify things to show.
     *
     * Strictly speaking, one could argue that its the ViewModels job to maintain
     * visibility, but we have the Model calculate how that propogates.
     */
    this.hideList = {};
    this.showList = {};

    /** this isn't used yet, but the idea is that eventually we'll keep track
     * of the users explorations, so we can replay them to adjust the visibility.
     */
    this.breadCrumbs = [];
    this.focusTip = null;
    this.lastPresetTitle = null;
    this.keywords = {};

    /** Essentially globals */
    this.renderData = null;
    this.dataReady = false;
    this.urlAdapter = urlAdapter;
    this.loadedBand = defaultBandId();
    this.bandLoading = false;
    this.bandPrompt = false;
    this.clickMode = "focus";
    viewModel = this;
    this.resetAll();
  }

  static compareCharities = compareCharities;
  static compareLinks = compareLinks;

  exportDB() {
    window.open("https://www.grumpytechbro.com/irs990.html", "_blank", "noopener");
  }

  clearAll() {
    for (const c of [...Charity.desiredCharities]) c.clearVisibility();
    for (const c of [...Charity.visibleCharities]) c.clearVisibility();
    for (const g of [...Grant.desiredGrants]) g.clearVisibility();
  }

  presets() {
    return this.#_presetsData;
  }

  getBillionaireOrgs() {
    const result = new Set();
    for (p of this.presets()) {
      if (p.title.includes("Billion")) {
        for (e of p.subcategories) {
          result.add(e.eins);
        }
      }
    }
    return result;
  }

  loadPreset(preset, mode) {
    const eins = preset.eins;
    this.lastPresetTitle = preset.title || null;
    const useSink = preset.sink === "patientSubsidies";
    const sinkPlace = (e) => (useSink ? `${e}~0~1` : e);
    if (mode === "replace") {
      this.clearAll();
      this.setShowList(eins.map(sinkPlace));
      this.breadCrumbs = [];
      this.focusTip = { title: preset.title || "Preset" };
      this.computeAndSaveURLParams();
    } else {
      const had = this.getShowList().length;
      for (const e of eins) {
        if (e === "-86") {
          // quick hack.
          clearStorage();
          return;
        }
        const ex = useSink
          ? `${e}~0~1`
          : `${e}~${START_REVEAL}~${START_REVEAL}`;
        this.addToShowList(ex);
      }
      this.focusTip = {
        title:
          !had && this.lastPresetTitle
            ? this.lastPresetTitle
            : this.lastPresetTitle
              ? `${this.lastPresetTitle} +`
              : `${this.getShowList().length} orgs`,
      };
    }
  }

  snapshotTitle(show) {
    const ids = (show || []).map((s) => String(s).split(/[:~]/)[0]);
    if (ids.length === 1) {
      const c = Charity.getCharity(ids[0]);
      return (c && c.name) || ids[0];
    }
    if (this.lastPresetTitle) return this.lastPresetTitle;
    return `${ids.length} orgs`;
  }

  pushFocusSnapshot() {
    const show = this.getShowList();
    if (!show.length) return;
    const key = show
      .map((s) => String(s).split(/[:~]/)[0])
      .sort()
      .join(",");
    const last = this.breadCrumbs[this.breadCrumbs.length - 1];
    if (last && last.key === key) return;
    this.breadCrumbs.push({
      title: this.focusTip?.title || this.snapshotTitle(show),
      key,
      showList: show.slice(),
      hideList: this.getHideList().slice(),
    });
  }

  restoreCrumb(index) {
    const crumb = this.breadCrumbs[index];
    if (!crumb) return false;
    this.breadCrumbs = this.breadCrumbs.slice(0, index);
    this.clearAll();
    this.clearKeywordList();
    this.setShowList(crumb.showList);
    this.setHideList(crumb.hideList || []);
    this.focusTip = { title: crumb.title };
    this.setZoom(null, null, null);
    this.computeAndSaveURLParams();
    return true;
  }

  /**Called when we focus on just one node*/
  resetAll() {
    Object.values(Grant.grantLookup).forEach((g) => {
      g.desiredVisible = false;
      g.impliedVisible = 0;
    });
  }

  /** methods for manipulating the scaling */

  rememberGraphSize(X, Y) {
    this.graphSizeX = X;
    this.graphSizeY = Y;
  }

  static SLOT_SIZE = 200; // graph sizing tweaks
  static COLUMN_SIZE = 500; // graph sizing tweaks
  countGraphRows() {
    const slots = {};
    let maxSlots = 0;
    let minY = 0;
    let maxY = viewModel.graphSizeY;
    for (const c of Charity.visibleCharities) {
      const slot = c.layer + 1;
      slots[slot] = (slots[slot] || 0) + 1;
      if (slots[slot] > maxSlots) maxSlots = slots[slot];
      if (c.y0 && c.y0 < minY) minY = c.y0;
      if (c.y1 && c.y1 > maxY) maxY = c.y1;
    }
    const circularGrants = Grant.visibleGrants.filter((g) => g.circular);
    const nodesHeight = maxY - minY;
    if (circularGrants.length) {
      const topCircles = circularGrants.filter(
        (g) => g.circularLinkType == "top"
      );
      const bottomCircles = circularGrants.filter(
        (g) => g.circularLinkType == "bottom"
      );
      let bottomHeight = 0;
      if (bottomCircles.length)
        bottomHeight =
          d3Array.max(bottomCircles, (d) => d.circularPathData.bottom) - maxY;
      let topHeight = 0;
      if (topCircles.length)
        topHeight =
          -d3Array.min(topCircles, (d) => d.circularPathData.top) - minY;
      const pixels_per_slot = nodesHeight / maxSlots;
      maxSlots += (topHeight + bottomHeight) / pixels_per_slot; // add the effective number of rows of the circular grants
    }
    return maxSlots;
  }

  balanceScales() {
    const xyRatio = this.expandScaleX / this.expandScaleY;
    const graphRatio = this.graphSizeX / this.graphSizeY;
    if (this.expandScaleX > BALANCELIMIT || this.expandScaleY > BALANCELIMIT) {
      if (this.expandScaleX > this.expandScaleY) {
        this.expandScaleX = BALANCELIMIT;
        this.expandScaleY = BALANCELIMIT / xyRatio / graphRatio;
      } else {
        this.expandScaleX = BALANCELIMIT * xyRatio * graphRatio;
        this.expandScaleY = BALANCELIMIT;
      }
    }
  }
  countGraphColumns() {
    let layers =
      d3.max(Array.from(Charity.visibleCharities), (c) => c.layer) + 1;
    if (layers < 2) {
      layers = 2;
      return;
    }
    return layers;
  }

  resetExpandScaleX() {
    this.expandScaleX = this.countGraphColumns() * PER_COL;
    this.balanceScales();
  }

  resetExpandScaleY() {
    const rows = this.countGraphRows() * PER_ROW;
    this.expandScaleY = Math.max(rows, 8);
    this.balanceScales();
  }

  defaultSize() {
    const rows = this.countGraphRows();
    const layers = this.countGraphColumns();
    this.expandScaleX = Math.max(layers * PER_COL, 4);
    this.expandScaleY = Math.max(rows * PER_ROW, 8);
    this.balanceScales();
    /*const aspect = this.graphSizeX / this.graphSizeY;
    let scaleX = this.getExpandScaleX();
    let scaleY = this.getExpandScaleY();
    let ratio = scaleX / scaleY;

    // Adjust for aspect, but cap distortion
    const maxDistort = 4; // e.g., no more than 4x viewport aspect
    if (Math.abs(ratio - aspect) > 0.2) {
      const targetRatio = aspect;
      if (ratio > targetRatio) {
        scaleY = Math.min(MAX_EXPAND_SCALE, scaleY * (ratio / targetRatio));
      } else {
        scaleX = Math.min(MAX_EXPAND_SCALE, scaleX * (targetRatio / ratio));
      }
      ratio = scaleX / scaleY; // Recalc
      if (ratio > maxDistort * aspect) scaleX = scaleY * maxDistort * aspect; // Cap wide
      if (ratio < aspect / maxDistort) scaleY = scaleX / (aspect / maxDistort); // Cap tall
    }
    if (scaleX > MAX_EXPAND_SCALE / 10 || scaleY > MAX_EXPAND_SCALE / 10) {
      const newMax = Math.max(scaleX, scaleY);
      const resetRatio = 10 / newMax;
      scaleX *= resetRatio;
      scaleY *= resetRatio;
    }
    this.setExpandScaleX(scaleX);
    this.setExpandScaleY(scaleY);*/
  }

  setExpandScaleY(scale) {
    this.expandScaleY = scale;
  }

  getExpandScaleY() {
    return this.expandScaleY || 2;
  }

  canExpandUpY() {
    return this.getExpandScaleY() < MAX_EXPAND_SCALE;
  }

  canExpandDownY() {
    return this.getExpandScaleY() > MIN_EXPAND_SCALE;
  }

  expandScaleYUp() {
    this.debugCloneDesired = new Set([...Charity.desiredCharities]);
    this.debugCloneVisible = new Set([...Charity.visibleCharities]);
    this.expandScaleY = Math.min(
      MAX_EXPAND_SCALE,
      this.expandScaleY * EXPAND_FACTOR
    );
  }

  expandScaleYDown() {
    this.expandScaleY = Math.max(
      MIN_EXPAND_SCALE,
      this.expandScaleY / EXPAND_FACTOR
    );
  }

  setExpandScaleX(scale) {
    this.expandScaleX = scale;
  }

  getExpandScaleX() {
    return this.expandScaleX || 2;
  }

  canExpandUpX() {
    return this.getExpandScaleX() < MAX_EXPAND_SCALE;
  }

  canExpandDownX() {
    return this.getExpandScaleX() > MIN_EXPAND_SCALE;
  }

  expandScaleXUp() {
    this.expandScaleX = Math.min(
      MAX_EXPAND_SCALE,
      this.expandScaleX * EXPAND_FACTOR
    );
  }

  expandScaleXDown() {
    this.expandScaleX = Math.max(
      MIN_EXPAND_SCALE,
      this.expandScaleX / EXPAND_FACTOR
    );
  }

  setGraphScale(scale) {
    if (scale != this.POWER_LAW) {
      this.POWER_LAW = scale;
      Charity.disorganzeAll();
    }
  }
  graphScaleDown() {
    this.POWER_LAW++;
    this.computeURLParams(); // update URL
    Charity.disorganzeAll();
  }

  graphScaleUp() {
    this.POWER_LAW--;
    if (this.POWER_LAW < 1) this.POWER_LAW = 1;
    this.computeURLParams(); // update URL
    Charity.disorganzeAll();
  }

  graphScaleReset() {
    this.POWER_LAW = POWER_LAW_RESET;
    this.computeURLParams(); // update URL
    Charity.disorganzeAll();
  }

  /** methods for manipulating the Show List */
  addToShowList(ein) {
    if (ein == "86") {
      clearStorage();
      return;
    }
    if (ein == "99") {
      DEBUGLOG = true; //get smart!
      return;
    }
    const c = Charity.getCharity(ein);
    if (c) {
      let tail = ein.split(/[:~]/).slice(1);
      if (!tail || tail.length == 0) {
        tail = [START_REVEAL, START_REVEAL];
      }
      this.showList[c.ein] = tail;
      if (!c.isVisible) c.place(tail[0], tail[1]);
      else c.desiredVisible = true; // we don't have to place it if its already visible but we do have to record the users desire.
    }
  }

  removeFromShowList(ein) {
    const id = ein.split(/[:~]/)[0];
    delete this.showList[id];
    const c = Charity.getCharity(id);
    if (c) {
      const tests = viewModel.buildSearchRegexes();
      if (tests.length && c.searchMatch(tests))
        // see if this was a keyword match we're getting rid of
        this.addToHideList(id);
      c.clearVisibility();
    }
    this.computeAndSaveURLParams(); // make sure it sticks
  }

  getShowList() {
    const result = Object.entries(this.showList)
      .sort((a, b) => a[0] - b[0]) // sort by key
      .map(
        ([key, value]) =>
          `${key}~${value[0] || START_REVEAL}~${value[1] || START_REVEAL}`
      );
    return result;
  }

  setShowList(list) {
    this.showList = {};
    list.forEach((ein) => this.addToShowList(ein));
    return this.getShowList();
  }

  clearShowList() {
    this.showList = {};
  }

  /** methods for manipulating the hide list */
  addToHideList(ein) {
    const c = Charity.getCharity(ein);
    if (c) {
      this.hideList[ein] = 1;
      c.desiredVisible = false;
    }
  }

  removeFromHideList(ein) {
    delete this.hideList[ein];
    const c = Charity.getCharity(ein);
    if (c) c.desiredVisible = true;
    viewModel.computeImpliedVisibility(c, true, true);
  }

  shouldHide(ein) {
    return this.hideList[ein];
  }

  getHideList() {
    return Object.keys(this.hideList).sort();
  }

  setHideList(list) {
    this.hideList = {};
    list.forEach((ein) => this.addToHideList(ein));
    return this.getHideList();
  }

  clearHideList() {
    this.hideList = {};
  }

  /** bread crumbs, as noted, aspirational at the moment */
  addToBreadCrumbs(crumb) {
    this.breadCrumbs.push(crumb);
  }

  removeFromBreadCrumbs(crumb) {
    this.breadCrumbs = this.breadCrumbs.filter((c) => c !== crumb);
  }

  getBreadCrumbs() {
    return this.breadCrumbs;
  }

  setBreadCrumbs(list) {
    this.breadCrumbs = list;
  }

  /** keep track of search keywords */
  addToKeywords(word) {
    const trimmed = word.trim();
    if (trimmed.startsWith("/") && trimmed.endsWith("/")) {
      this.keywords[trimmed] = 1;
    } else {
      this.keywords[trimmed.toLowerCase()] = 1;
    }
  }

  // Modify removeFromKeywords:
  removeFromKeywords(word) {
    const trimmed = word.trim();
    const key =
      trimmed.startsWith("/") && trimmed.endsWith("/")
        ? trimmed
        : trimmed.toLowerCase();
    delete this.keywords[key];
  }

  clearKeywordList() {
    this.keywords = {};
  }

  getKeywordList() {
    return Object.keys(this.keywords).sort();
  }

  // Modify setKeywordList:
  setKeywordList(list) {
    this.keywords = {};
    list.forEach((kw) => {
      if (kw.startsWith("/") && kw.endsWith("/")) {
        this.keywords[kw] = 1;
      } else {
        this.keywords[kw.toLowerCase()] = 1;
      }
    });
  }

  // Add new method:
  buildSearchRegexes() {
    const stringKws = [];
    const regexKws = [];
    this.getKeywordList().forEach((kw) => {
      if (kw.startsWith("/") && kw.endsWith("/")) {
        const pat = kw.slice(1, -1);
        try {
          regexKws.push(new RegExp(pat, "i"));
        } catch (e) {
          console.warn(`Invalid regex: ${kw}`);
        }
      } else {
        stringKws.push(kw);
      }
    });
    const allRegexes = [...regexKws];
    if (stringKws.length > 0) {
      const pat = stringKws.join("|");
      allRegexes.push(new RegExp(pat, "i"));
    }
    return allRegexes;
  }

  // Add escapeRegExp function if not present (can add globally or in file):
  escapeRegExp(string) {
    return string.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
  }

  /** match Charities against search terms */
  matchKeys() {
    const regexes = this.buildSearchRegexes();
    return Object.values(Charity.charityLookup).filter(
      (c) =>
        !this.shouldHide(c.id) && c.searchMatch(regexes) && !c.desiredVisible
    );
  }

  /**
   * After we expand or compress, we have to reset the EIN in the show list.
   *
   */
  resetEIN(ein) {
    const c = Charity.getCharity(ein);
    if (c) {
      this.addToShowList(c.URLPiece());
    }
  }

  setZoom(zoom_x, zoom_y, zoom_k) {
    this.zoom_k = zoom_k;
    this.zoom_x = zoom_x;
    this.zoom_y = zoom_y;
  }

  setHideCircularLinks(value) {
    this.hideCircularLinks = value;
  }

  getHideCircularLinks() {
    return this.hideCircularLinks;
  }

  /** Given a model in a given state, calculate the minimum URL necessary to replicate that
   * state. Since visibility can be direct (called desired in the model) or implied, we
   * only need to include the desired charities, not the implied.
   */
  computeURLParams() {
    const params = new URLSearchParams();
    let visibleMap = {};
    Charity.desiredCharities.forEach((c) => {
      const p = c.URLPiece();
      if (p) visibleMap[c.ein] = p;
    });
    this.getHideList().forEach((ein) => delete visibleMap[ein]);
    Object.values(visibleMap).forEach((e) => params.append("e", e));
    this.getHideList().forEach((e) => params.append("n", e));
    this.getKeywordList().forEach((k) => {
      let urlK = k;
      if (urlK.startsWith("/") && urlK.endsWith("/")) {
        urlK = `~${urlK.slice(1, -1)}~`;
      }
      params.append("k", urlK);
    });
    params.append("s", this.POWER_LAW);
    params.append("X", this.getExpandScaleX());
    params.append("Y", this.getExpandScaleY());
    if (this.zoom_x && this.zoom_y && this.zoom_k) {
      params.append("zk", this.zoom_k);
      params.append("zx", this.zoom_x);
      params.append("zy", this.zoom_y);
    }
    if (this.getHideCircularLinks()) params.append("hc", 1);
    if (DEBUGLOG) params.append("D", 1); //make it sticky
    if (DEBUGSTOP) params.append("d", 1); //make it sticky
    return params;
  }

  computeAndSaveURLParams() {
    const params = this.computeURLParams();
    if (this.urlAdapter && typeof this.urlAdapter.replace === "function") {
      this.urlAdapter.replace(params);
      return params;
    }
    if (typeof window !== "undefined" && window.history && window.location) {
      const newUrl = window.location.pathname + "?" + params.toString();
      window.history.replaceState({}, "", newUrl);
    }
    return params;
  }

  parseParamsWithOldNew(params, oldName, newName) {
    let parms = params.getAll(newName);
    if (!parms.length) parms = params.getAll(oldName);
    return parms;
  }
  /** given a URL, parse it into our relevant pieces */
  parseQueryParams(params = new URLSearchParams(window.location.search)) {
    this.showList = {};
    this.setShowList(this.parseParamsWithOldNew(params, "ein", "e"));
    this.setHideList(this.parseParamsWithOldNew(params, "nein", "n"));
    const rawKs = this.parseParamsWithOldNew(params, "keywords", "k");
    const processed = rawKs.map((k) => {
      if (k.startsWith("~") && k.endsWith("~")) {
        return `/${k.slice(1, -1)}/`;
      } else {
        return k;
      }
    });
    this.setKeywordList(processed);
    const scale = parseInt(params.get("s") || params.get("scale") || "0", 10);
    if (scale) this.setGraphScale(scale);
    const expandX = parseFloat(
      params.get("X") || params.get("expandX") || "2",
      10
    );
    const expandY = parseFloat(
      params.get("Y") || params.get("expandY") || "2",
      10
    );
    this.setExpandScaleX(expandX);
    this.setExpandScaleY(expandY);
    if (params.get("D")) DEBUGLOG = true; /// set it once, it sticks
  }

  /** Place holder for when we actually parse the breadcrumb data, for
   * now it insures we have a starting point.
   */
  processBreadCrumbs() {
    if (Charity.visibleCharities.length === 0) {
      randomPreset();
    }
  }

  /**
   *  Given our URL, match the model. That means seeding the model with desiredVisible nodes
   * from the showList and the search keywords, then turning that off for the hide List items.
   * This is called "placing" a Node, which makes the node visible and then marks the first
   * START_REVEAL incoming and outgoing edges and nodes as implied visible. The ein in the
   * URL actually encodes the number of visilbe upstream and downstream grants, so we can
   * faithfully reproduce some expansion.
   * @param {The URL} params
   * @returns
   */
  matchURL(params = new URLSearchParams(window.location.search)) {
    this.parseQueryParams(params);
    updateStatus("", "green", false);
    if (DEBUGLOG)
      console.log("ShowList before processing:", this.getShowList());
    let regexes = [];
    let visibleKeywordMatches = 0;
    if (this.getKeywordList().length) {
      regexes = this.buildSearchRegexes();
      visibleKeywordMatches = Array.from(Charity.visibleCharities).filter(
        (c) => !this.shouldHide(c.id) && c.searchMatch(regexes)
      ).length;

      Charity.visibleCharities.forEach((c) => {
        c.desiredVisible = false;
        c.impliedVisible = 0;
      });
      this.getShowList().forEach((ein) => {
        const parts = ein.split(/[:~]/);
        const id = parts[0];
        let ups = parseInt(parts[1] || `${START_REVEAL}`, 10) || START_REVEAL;
        if (parts[1] && parts[1] == "0") ups = 0; // || confuses things
        let downs = parseInt(parts[2] || `${START_REVEAL}`, 10) || START_REVEAL;
        if (parts[2] && parts[2] == "0") downs = 0; // || confuses things
        const charity = Charity.getCharity(id);
        if (charity && !this.shouldHide(id)) {
          if (!(charity.impliedVisible > 1)) charity.place(ups, downs); // circular grants suck
          if (DEBUGLOG)
            console.log(
              `Matched EIN ${ein}, placed ${id}, grants out: ${charity.grants.length}, in: ${charity.grantsIn.length}`
            );
        } else {
          if (DEBUGLOG) console.error(`no match for ${ein} in match`);
        }
      });
      this.getHideList().forEach((ein) => {
        const c = Charity.getCharity(ein);
        if (c) c.desiredVisible = false;
      });

      if (regexes.length) {
        const remainingSlots = Math.max(
          0,
          MAX_KEYWORD_NODES - visibleKeywordMatches
        );

        if (remainingSlots > 0) {
          const invisibleMatches = Charity.invisibleCharities
            .filter(
              (c) =>
                !this.shouldHide(c.id) &&
                c.searchMatch(regexes) &&
                !c.desiredVisible
            )
            .sort((a, b) => b.denominator - a.denominator);

          if (invisibleMatches.length > remainingSlots) {
            updateStatus(
              `<span>Note: Graph limited to ${MAX_KEYWORD_NODES} largest orgs matching keyworks (${visibleKeywordMatches} visible + ${remainingSlots} new)</span>`,
              "orange"
            );
          }
          const limitedMatches = invisibleMatches.slice(0, remainingSlots);

          limitedMatches.forEach((c) => {
            c.place(1, 1); // avoid sankey explosion
          });
        }
      }
    }
    this.computeImpliedVisibility(null, true, true);
    if (DEBUGLOG)
      console.log(
        "Visible Charities after matchURL:",
        Charity.visibleCharities.size,
        Array.from(Charity.visibleCharities).map((c) => c.toString())
      );
    return Charity.visibleCharities.size;
  }

  async buildTheWorld(db) {
    if (!db) {
      throw new Error("Database not provided to buildTheWorld");
    }
    if (!db.objectStoreNames.contains(CHARITY_STORE)) {
      throw new Error(`CHARITY_STORE does not exist in database`);
    }
    if (!db.objectStoreNames.contains(METADATA_STORE)) {
      throw new Error(`METADATA_STORE does not exist in database`);
    }

    updateStatus(
      `Building World from ${Object.keys(iso3166_alpha2).length} countries`,
      "black"
    );
    const countryRecords = [];
    let countriesProcessed = 0;

    for (const [fake_ein, data] of Object.entries(iso3166_alpha2)) {
      try {
        if (!fake_ein || !data || !data.name || !data.code) {
          continue;
        }
        const country_pro = {
          filer_ein: fake_ein,
          filer_name: data.name,
          name: data.name,
          xml_name: `The World${data.code}`,
          receipt_amt: 0,
          govt_amt: 0,
          contrib_amt: 1,
          tax_year: "2025",
          org_type: "Foreign Country",
          total_assets: null,
          form_type: null,
          denominator: null,
        };
        Charity.buildCharityFromRow(country_pro);
        countryRecords.push(country_pro);
        countriesProcessed++;
      } catch (error) {
        console.error(`Error processing country ${fake_ein}:`, error);
        continue;
      }
    }

    updateStatus(`Storing ${countriesProcessed} country records`);
    try {
      if (DEBUGLOG) console.time("storeCountries");
      const storedCount = await storeData(db, CHARITY_STORE, countryRecords);
      if (DEBUGLOG) console.timeEnd("storeCountries");
      if (storedCount !== countryRecords.length) {
        console.warn(
          `Storage mismatch: Prepared ${countryRecords.length} countries, stored ${storedCount}`
        );
      }
    } catch (error) {
      console.error(`Failed to store countries in IndexedDB:`, error);
      if (DEBUGLOG) console.log("Continuing despite storage error");
    }

    try {
      if (DEBUGLOG) console.time("storeMetadata");
      const tx = db.transaction(METADATA_STORE, "readwrite");
      const store = tx.objectStore(METADATA_STORE);
      await Promise.all([
        new Promise((resolve, reject) => {
          const request = store.put({ id: "generated", value: true });
          request.onsuccess = resolve;
          request.onerror = () => reject(request.error);
        }),
        new Promise((resolve, reject) => {
          const request = store.put({
            id: "version",
            value: DATA_FILES.dbVersion,
          });
          request.onsuccess = resolve;
          request.onerror = () => reject(request.error);
        }),
        new Promise((resolve, reject) => {
          const request = store.put({
            id: "band",
            value: this.loadedBand || defaultBandId(),
          });
          request.onsuccess = resolve;
          request.onerror = () => reject(request.error);
        }),
      ]);
      await tx.done;
      if (DEBUGLOG) console.timeEnd("storeMetadata");
    } catch (error) {
      console.error(`Failed to store metadata:`, error);
      console.log("Continuing despite metadata error");
    }
  }

  /**
   *  A Charity that doesn't have any incoming grants I term a root, with the US Govt being
   * the largest. But it seemed intresting to use them as a starting point. This returns
   * all roots, which can then be sliced.
   * @returns
   */
  getRootCharities() {
    if (Charity.rootCharities) return Charity.rootCharities;
    Charity.rootCharities = Object.values(Charity.charityLookup)
      .filter((c) => c.isRoot && !c.govt_amt && !c.isTerminal)
      .filter((c) => !this.shouldHide(c.id))
      .sort((a, b) => b.grantsTotal - a.grantsTotal);
    return Charity.rootCharities;
  }

  /**
   * Clicking on a node toggles its visibility.
   * If it's one of the ones we've specifically chosen to be visible, its
   * now just a regular node. If it was implied (we know its  visible if it was
   * clicked on) its now desired, which has implications for the implied propogation
   * as it will step 1 node farther down the graph.
   */
  setClickMode(mode) {
    if (
      mode === "add" ||
      mode === "inspect" ||
      mode === "focus" ||
      mode === "subtract" ||
      mode === "zoom"
    ) {
      this.clickMode = mode;
    } else {
      this.clickMode = "focus";
    }
    return this.clickMode;
  }

  /** Shift = remove, Alt/Option = inspect, ⌘/Ctrl = add. Plain click uses the mode button. */
  modeFromEvent(event) {
    if (event && event.shiftKey) return "subtract";
    if (event && event.altKey) return "inspect";
    if (event && (event.metaKey || event.ctrlKey)) return "add";
    return this.clickMode || "focus";
  }

  clickNode(event, charity, refreshCallback) {
    const mode = this.modeFromEvent(event);
    if (mode === "subtract") {
      charity.hide();
      if (refreshCallback) refreshCallback();
      return "subtract";
    }
    if (charity.isLeftover) {
      if (DEBUGLOG)
        console.log(
          `See-more stub ${charity.id}; deeper load is the ${bandCutLabel("1M")} notch`
        );
      return "leftover";
    }
    if (mode === "inspect") {
      return "inspect";
    }
    if (mode === "zoom") {
      return "zoom";
    }
    if (mode === "add") {
      this.addToShowList(
        `${charity.ein}~${START_REVEAL}~${START_REVEAL}`
      );
      if (refreshCallback) refreshCallback();
      return "add";
    }
    if (charity.desiredVisible) {
      charity.expandOutflows(NEXT_REVEAL);
      charity.expandInflows(NEXT_REVEAL);
      this.computeImpliedVisibility(charity, true, true);
      this.computeAndSaveURLParams();
      if (refreshCallback) refreshCallback();
      return "expand";
    }
    if (DEBUGLOG) console.log(`Focus node ${charity.id} ${charity.name}`);
    charity.tunnelNode();
    if (refreshCallback) refreshCallback();
    return "focus";
  }

  /**
   * Clicking on the pig emoji recurses upward setting any ndoe on a path to USG colors
   * to desired visible
   */
  porkClick(ein) {
    const c = Charity.getCharity(`${ein}`);
    if (c) return c.porkClick();
    return { depth: 0, reveal: 0 };
  }

  /** Clicking on the Money Bags emoji recurses upstards setting any node on the path
   * to a billionaire influenced charity visible
   */
  billClick(ein) {
    const c = Charity.getCharity(`${ein}`);
    if (c) c.billionarieClick();
  }

  /**
   *  Doubleclicking being the "expand/open" gesture means in this
   * case that we force desiredVisible to true, and add more visible grants.
   * Shift double-click is constract, we force desiredToFalse and remove visible grants
   * @param {*} event
   * @param {*} charity
   */
  doubleClickNode(event, charity) {
    if (event.shiftKey) {
      charity.desiredVisible = false;
      charity.compressOutflows(NEXT_REVEAL);
      charity.compressInflows(NEXT_REVEAL);
      if (DEBUGLOG) console.log(`Compressing ${charity.id} ${charity.name}`);
    } else {
      desiredVisible = true;
      charity.expandOutflows(NEXT_REVEAL);
      charity.expandInflows(NEXT_REVEAL);
      if (DEBUGLOG) console.log(`Expanding ${charity.id} ${charity.name}`);
    }
    this.computeImpliedVisibility(charity, true, true);
  }

  /**
   * Clicking a grant toggles desired visibility. Which is mostly about
   * affecting implied indirectly.
   * @param {*} event
   * @param {*} grant
   */
  clickGrant(event, grant) {
    grant.desiredVisible = !grant.desiredVisible;
    /*TODO Think about what we should do to grant.filer and grant.grantee  */
    if (DEBUGLOG)
      console.log(
        `${grant.desiredVisible ? "Showing" : "Hiding"} grant ${grant.id}`
      );
    this.computeImpliedVisibility(grant.filer, true, false);
    this.computeImpliedVisibility(grant.grantee, false, true);
  }

  /** Double clicking a grant forces both ends of the grang */
  doubleClickGrant(event, grant) {
    if (event.shiftKey) {
      grant.filer.desiredVisible = false;
      grant.grantee.desiredVisible = false;
      if (DEBUGLOG) console.log(`Hiding nodes for grant ${grant.id}`);
    } else {
      grant.filer.desiredVisible = true;
      grant.grantee.desiredVisible = true;
      grant.desiredVisible = true;
      if (DEBUGLOG) console.log(`Showing nodes and grant ${grant.id}`);
    }
    this.computeImpliedVisibility(grant.filer, true, false);
    this.computeImpliedVisibility(grant.grantee, false, true);
  }

  /**
   * Because its natural to want to expand just one direction visually we draw
   * these little hats on either side of a node, clicking on the upstream hat
   * expands that way, clicking on the downstream that way.
   */
  handleUpClick(event, charity, refreshCallback) {
    if (DEBUGLOG)
      console.log(`Expanding inflows for ${charity.id} ${charity.name}`);
    charity.desiredVisible = true;
    charity.expandInflows(NEXT_REVEAL);
    this.computeImpliedVisibility(charity, true, true);
    this.buildSankeyData();
    if (refreshCallback) refreshCallback();
  }

  handleDownClick(event, charity, refreshCallback) {
    if (DEBUGLOG)
      console.log(`Expanding outflows for ${charity.id} ${charity.name}`);
    charity.desiredVisible = true;
    charity.expandOutflows(NEXT_REVEAL);
    this.computeImpliedVisibility(charity, true, true);
    this.buildSankeyData();
    if (refreshCallback) refreshCallback();
  }

  /**
   * Workhorse method for doing all the complicated visiblity shit.
   * If rootCharity is null, we're going to reset everything, start with the
   * desired nodes, then propogate one step from there.
   * If rootCharity is set, we're doing an incremental prop, just need to do
   * one step.
   * @param {*} rootCharity Starting point, or null for all desiredVisible nodes
   * @param {*} inflowsOnly Only go left
   * @param {*} outflowsOnly Only go right
   */
  computeImpliedVisibility(
    rootCharity = null,
    inflowsOnly = false,
    outflowsOnly = false
  ) {
    Charity.desiredCharities.forEach((c) => {
      c.impliedVisible = 1;
    });
    Grant.desiredGrants.forEach((g) => {
      g.impliedVisible = g.desiredVisible;
    });

    /**
     * Ok, so two cases: rootCharity is null, loop over desiredCharities and prop
     * the implied up and down based on existing state. i.e. if no grants are
     * visibile, make START_REVEAL visible, if some are, make NEXT_REVEAL visible.
     *
     * If root charity is not null, as above, but for one charity.
     *
     * I should refactor this to break out ops.
     * Have to go review the existing operations on Charities though.
     */

    if (rootCharity) {
      // incremental case
      /* if (inflowsOnly) {
        for (const grant of rootCharity.invisibleGrantsIn.slice(
          0,
          NEXT_REVEAL
        )) {
          if (!this.shouldHide(grant.filer.ein)) {
            grant.filer.impliedVisible++;
            grant.impliedVisible = true;
            console.log(`  Inflow filer ${grant.filer.ein} set visible`);
          }
        }
      }

      if (outflowsOnly) {
        for (const grant of rootCharity.invisibleGrants.slice(0, NEXT_REVEAL)) {
          if (!this.shouldHide(grant.grantee.ein)) {
            grant.grantee.impliedVisible++;
            grant.impliedVisible = true;
            console.log(`  Outflow grantee ${grant.grantee.ein} set visible`);
          }
        }
      }*/
    } else {
      // brute force whole data model case
      const seeds = Charity.desiredCharities; //handy accessor
      for (const charity of seeds) {
        for (const grant of charity.looseVisibleGrants) {
          if (
            (grant.desiredVisible || charity.desiredVisible) &&
            !this.shouldHide(grant.grantee.ein)
          ) {
            grant.grantee.impliedVisible++;
            grant.impliedVisible = true;
            if (!grant.grantee.isGov || grant.grantee.desiredVisible) {
              if (DEBUGLOG)
                console.log(
                  `  Outflow grantee ${grant.grantee.ein} set visible`
                );
            }
          }
        }
        for (const grant of charity.looseVisibleGrantsIn) {
          if (
            (grant.desiredVisible || charity.desiredVisible) &&
            !this.shouldHide(grant.filer.ein)
          ) {
            grant.filer.impliedVisible++;
            grant.impliedVisible = true;
            if (!grant.filer.isGov || grant.filer.desiredVisible) {
              if (DEBUGLOG)
                console.log(`  Inflow filer ${grant.filer.ein} set visible`);
            }
          }
        }
      }
    }
    this.computeAndSaveURLParams();
  }

  /**
   * Make sure the sankey data is clean
   */
  buildCleanSankeyData(maxallowed = MAX_NODES) {
    function filterHiddenGrant(grant) {
      if (viewModel.shouldHide(grant.filer.ein)) return true;
      if (viewModel.shouldHide(grant.grantee.ein)) return true;
      return false;
    }
    let maxSeeds = maxallowed;
    this.renderData.links = Grant.visibleGrants.filter(
      (g) => !filterHiddenGrant(g)
    );
    this.renderData.nodes = Array.from(Charity.visibleCharities).filter(
      (node) => !this.shouldHide(node.ein)
    );
    const nodeSet = new Set();
    const missingSet = new Set();
    this.renderData.nodes.forEach((node) => nodeSet.add(node.ein));
    this.renderData.links.forEach((grant) => {
      if (!nodeSet.has(grant.filer.ein)) missingSet.add(grant.filer.ein);
      if (!nodeSet.has(grant.grantee.ein)) missingSet.add(grant.grantee.ein);
    });
    // add missing nodes
    for (const ein of missingSet) {
      console.log(`bCSD: adding missing node ${ein}`);
      this.renderData.nodes.push(Charity.getCharity(ein));
    }
  }

  /**
   * Build the data we need for the Sankey. The model is close enough to what it needs that we
   * can draw direclty from the data, though we do have to undo the fact that the sankey code
   * replaces source as EIN with source as object.
   * @returns
   */
  buildSankeyData() {
    let maxSeeds = MAX_NODES;
    this.renderData = { nodes: [], links: [] };
    //this.computeImpliedVisibility();
    this.buildCleanSankeyData(maxSeeds);
    if (this.debugCloneDesired) {
      const differenceD = new Set();
      for (const item of Charity.desiredCharities) {
        if (!this.debugCloneDesired.has(item)) {
          differenceD.add(item);
        }
      }
      const differenceV = new Set();
      for (const item of Charity.visibleCharities) {
        if (!this.debugCloneVisible.has(item)) {
          if (item.impliedVisible > 0) differenceV.add(item);
        }
      }
      console.log("Desired", [...differenceD]);
      console.log("Implied", [...differenceV]);
    }
    /*while (this.renderData.nodes.length > MAX_NODES && maxSeeds > 5) {
      updateStatus(`Too Many Nodes, reducing to ${maxSeeds} seeds`);
      Charity.visibleCharities // reverse sort so largest flows larger get kept
        .sort(
          (a, b) =>
            b.grantsTotal + b.grantsInTotal - (a.grantsTotal + b.grantsInTotal)
        )
        .slice(maxSeeds)
        .forEach((c) => c.clearVisibility());
      this.computeImpliedVisibility(null, true, true);
      this.renderData.nodes = Charity.visibleCharities;
      this.renderData.links = Grant.visibleGrants;
      this.buildCleanSankeyData(maxSeeds);
      maxSeeds /= 2; // try with half as much next time.
    }*/
    console.log(
      `Sankey Data - Nodes: ${this.renderData.nodes.length}, Links: ${this.renderData.links.length}`
    );
    return this.renderData;
  }
  async processGrantsZipFile({ status, zipFile, tsvFile, grantType }) {
    try {
      if (DEBUGLOG)
        console.log(`Starting ${zipFile} at ${new Date().toISOString()}`);
      const db = await initDB();
      if (DEBUGLOG) console.time("Starting grant fetch" + zipFile);

      const records = await fetchAndStoreTSV(db, {
        zipFile,
        tsvFile,
        type: "grants",
        grantType,
        status,
      });
      if (DEBUGLOG) console.timeEnd("Starting grant fetch" + zipFile);

      if (DEBUGLOG) console.time("Starting grant store" + zipFile);
      await storeData(db, GRANT_STORE, records);
      if (DEBUGLOG) console.timeEnd("Starting grant store" + zipFile);
      let totalGrantsRows = records.length;

      for (let i = 0; i < records.length; i += CHUNK_SIZE) {
        const chunk = records.slice(i, i + CHUNK_SIZE);
        for (const row of chunk) {
          Grant.loadGrantRow(row, grantType);
        }
        await new Promise((resolve) => setTimeout(resolve, 0));
        updateStatus(
          `${status}: ${formatNumber(totalGrantsRows)} grants processed`
        );
      }

      if (DEBUGLOG)
        console.log(`Finished ${zipFile}, totalGrantsRows: ${totalGrantsRows}`);
      updateStatus(
        `Processed ${formatNumber(totalGrantsRows)} grants for ${tsvFile}`,
        "green",
        false
      );
      return { rows: totalGrantsRows, grantType };
    } catch (err) {
      console.error(`Error processing ${zipFile}:`, err);
      updateStatus(`Error processing ${tsvFile}: ${err.message}`, "red", false);
      throw err;
    }
  }
  async loadData() {
    if (DEBUGLOG)
      console.log(`Starting loadData at ${new Date().toISOString()}`);
    updateStatus("Loading data...");
    this.dataReady = false;
    Charity.charityLookup = {};
    Grant.grantLookup = {};

    try {
      if (DEBUGLOG) console.log("Initializing IndexedDB...");
      this.db = await initDB();
      if (DEBUGLOG) console.log("IndexedDB initialized");
      if (DEBUGLOG)
        console.log(
          `Database stores: ${Array.from(this.db.objectStoreNames).join(", ")}`
        );

      if (await hasValidData(this.db)) {
        const storedBand =
          (await idbGetMeta(this.db, "band")) || defaultBandId();
        this.loadedBand = storedBand;
        if (typeof window !== "undefined" && window.applyLoadingCopy) {
          window.applyLoadingCopy(this.loadedBand, { fromStore: true });
        }
        updateStatus(
          `Loading ${bandCutLabel(this.loadedBand)} band from local store...`
        );
        const tLoad = typeof performance !== "undefined" ? performance.now() : Date.now();
        if (DEBUGLOG) console.time("loadCharitiesFromDB");
        const charities = await fetchLocalData(this.db, CHARITY_STORE);
        if (DEBUGLOG) console.timeEnd("loadCharitiesFromDB");
        if (DEBUGLOG)
          console.log(`Fetched ${charities.length} charities from IndexedDB`);
        loadingViaDB();
        let chunkSize = 10000;
        const TARGET_CYCLE_TIME = 500;
        const MIN_CHUNK_SIZE = 2500;
        const MAX_CHUNK_SIZE = 40000;
        let processedCharities = 0;

        let i = 0;
        while (i < charities.length) {
          const startTime = performance.now();
          if (DEBUGLOG) console.time(`processCharities-${i}`);
          const chunk = charities.slice(i, i + chunkSize);
          for (const row of chunk) {
            try {
              Charity.buildCharityFromRow(row);
              processedCharities++;
            } catch (error) {
              console.error(`Error processing charity row ${i}:`, error, row);
              continue;
            }
          }
          if (DEBUGLOG) console.timeEnd(`processCharities-${i}`);
          updateStatus(
            `Loading charities: ${formatNumber(
              Object.keys(Charity.charityLookup).length
            )} processed`
          );
          await new Promise((resolve) => setTimeout(resolve, 0));

          const cycleTime = performance.now() - startTime;
          if (
            cycleTime < TARGET_CYCLE_TIME * 0.5 &&
            chunkSize < MAX_CHUNK_SIZE
          ) {
            chunkSize = Math.min(chunkSize * 2, MAX_CHUNK_SIZE);
          } else if (
            cycleTime > TARGET_CYCLE_TIME * 2 &&
            chunkSize > MIN_CHUNK_SIZE
          ) {
            chunkSize = Math.max(Math.floor(chunkSize / 2), MIN_CHUNK_SIZE);
          }
          i += chunk.length;
        }
        if (DEBUGLOG)
          console.log(
            `Processed ${processedCharities} charities, lookup size: ${
              Object.keys(Charity.charityLookup).length
            }`
          );

        if (DEBUGLOG) console.time("loadGrantsFromDB");
        const grants = await fetchLocalData(this.db, GRANT_STORE);
        if (DEBUGLOG) console.timeEnd("loadGrantsFromDB");
        console.log(`Fetched ${grants.length} grants from IndexedDB`);
        if (DEBUGLOG) chunkSize = 10000;
        let processedGrants = 0;
        i = 0;
        while (i < grants.length) {
          const startTime = performance.now();
          if (DEBUGLOG) console.time(`processGrants-${i}`);
          const chunk = grants.slice(i, i + chunkSize);
          for (const row of chunk) {
            try {
              Grant.loadGrantRow(row, row.grantType);
              processedGrants++;
            } catch (error) {
              console.error(`Error processing grant row ${i}:`, error, row);
              continue;
            }
          }
          if (DEBUGLOG) console.timeEnd(`processGrants-${i}`);
          updateStatus(
            `Loading grants: ${formatNumber(
              Object.keys(Grant.grantLookup).length
            )} processed`
          );
          await new Promise((resolve) => setTimeout(resolve, 0));

          const cycleTime = performance.now() - startTime;
          if (
            cycleTime < TARGET_CYCLE_TIME * 0.5 &&
            chunkSize < MAX_CHUNK_SIZE
          ) {
            chunkSize = Math.min(chunkSize * 2, MAX_CHUNK_SIZE);
          } else if (
            cycleTime > TARGET_CYCLE_TIME * 2 &&
            chunkSize > MIN_CHUNK_SIZE
          ) {
            chunkSize = Math.max(Math.floor(chunkSize / 2), MIN_CHUNK_SIZE);
          }
          i += chunk.length;
        }
        if (DEBUGLOG)
          console.log(
            `Processed ${processedGrants} grants, lookup size: ${
              Object.keys(Grant.grantLookup).length
            }`
          );

        const idbMs =
          (typeof performance !== "undefined" ? performance.now() : Date.now()) -
          tLoad;
        recordBandLoadMs(this.loadedBand, "idb", idbMs);
        updateStatus(
          `Loaded ${formatNumber(
            Object.keys(Charity.charityLookup).length
          )} charities, ${formatNumber(
            Object.keys(Grant.grantLookup).length
          )} grants from local storage in ${formatDuration(idbMs)}`,
          "green",
          false
        );
      } else {
        this.loadedBand = defaultBandId();
        updateStatus(
          `Downloading ${bandCutLabel(this.loadedBand)} band (one-time for this data version)...`
        );
        loadingViaWeb();

        try {
          const tWeb = typeof performance !== "undefined" ? performance.now() : Date.now();
          await this.ingestBandFromWeb(this.loadedBand);
          const webMs =
            (typeof performance !== "undefined" ? performance.now() : Date.now()) -
            tWeb;
          recordBandLoadMs(this.loadedBand, "web", webMs);

          updateStatus(
            `Loaded ${formatNumber(
              Object.keys(Charity.charityLookup).length
            )} charities, ${formatNumber(
              Object.keys(Grant.grantLookup).length
            )} grants from server in ${formatDuration(webMs)}`,
            "green",
            false
          );

          await new Promise((resolve) => setTimeout(resolve, 0));
        } catch (error) {
          console.error("Error during server fetch:", error);
          updateStatus(
            `Error during server fetch: ${error.message}`,
            "red",
            false
          );
          throw error;
        }
      }

      if (DEBUGLOG)
        console.log(
          `Grants Net ${formatNumber(Object.keys(Grant.grantLookup).length)}`
        );
      updateStatus("USG & NGOs & grants loaded", "black", false);
      this.dataReady = true;
      if (DEBUGLOG)
        console.log(`loadData completed at ${new Date().toISOString()}`);
      return Object.keys(Grant.grantLookup).length;
    } catch (err) {
      console.error("Error in loadData:", err);
      updateStatus(`Error loading data: ${err.message}`, "red", false);
      this.dataReady = false;
      throw err;
    }
  }

  async ingestBandFromWeb(bandId) {
    const files = filesForBand(bandId);
    if (!files.length) {
      throw new Error(`No files published for ${bandCutLabel(bandId)}`);
    }
    this.loadedBand = bandId;
    if (DEBUGLOG) console.time("buildTheWorld");
    await this.buildTheWorld(this.db);
    if (DEBUGLOG) console.timeEnd("buildTheWorld");

    if (DEBUGLOG) console.time("loadTSVFiles");
    await fetchAndStoreTSV(this.db, files);
    if (DEBUGLOG) console.timeEnd("loadTSVFiles");

    if (DEBUGLOG) console.time("buildGovCharity");
    await this.buildGovCharity(this.db);
    if (DEBUGLOG) console.timeEnd("buildGovCharity");

    const nCharities = Object.keys(Charity.charityLookup).length;
    const nGrants = Object.keys(Grant.grantLookup).length;
    if (nCharities < MIN_LOADED_CHARITIES || nGrants < MIN_LOADED_GRANTS) {
      throw new Error(
        `Incomplete data load: ${nCharities} charities, ${nGrants} grants`
      );
    }

    await idbPutMeta(this.db, {
      generated: true,
      version: DATA_FILES.dbVersion,
      band: bandId,
    });
  }

  /**
   * Opt-in to a deeper dollar band. Returns { status: current|unavailable|loaded, band }.
   * Caller shows the loader; this fetches/replaces IndexedDB when files exist.
   */
  async requestBand(bandId) {
    if (!canUpgradeBand(this.loadedBand, bandId)) {
      return { status: "current", band: this.loadedBand };
    }
    const band = bandById(bandId);
    if (!band) return { status: "unknown", band: bandId };
    if (!bandHasFiles(band)) {
      return { status: "unavailable", band: bandId };
    }
    if (this.bandLoading) {
      return { status: "busy", band: this.loadedBand };
    }
    this.bandLoading = true;
    this.dataReady = false;
    try {
      this.db = this.db || (await initDB());
      Charity.charityLookup = {};
      Grant.grantLookup = {};
      Charity.rootCharities = null;
      await clearGraphStores(this.db);
      loadingViaWeb();
      updateStatus(
        `Downloading ${bandCutLabel(bandId)} band (another wait)...`
      );
      const tWeb = typeof performance !== "undefined" ? performance.now() : Date.now();
      await this.ingestBandFromWeb(bandId);
      const webMs =
        (typeof performance !== "undefined" ? performance.now() : Date.now()) -
        tWeb;
      recordBandLoadMs(bandId, "web", webMs);
      this.loadedBand = bandId;
      this.dataReady = true;
      updateStatus(
        `Loaded ${formatNumber(
          Object.keys(Charity.charityLookup).length
        )} charities, ${formatNumber(
          Object.keys(Grant.grantLookup).length
        )} grants from ${bandCutLabel(bandId)} in ${formatDuration(webMs)}`,
        "green",
        false
      );
      return { status: "loaded", band: bandId };
    } catch (err) {
      console.error("Error loading band", bandId, err);
      updateStatus(`Error loading ${bandCutLabel(bandId)}: ${err.message}`, "red", false);
      this.dataReady = false;
      throw err;
    } finally {
      this.bandLoading = false;
    }
  }
  /*
   * So the NGO data we're parsing calls out how much money each NGO is getting from the Government.
   * That's treated as an implied grant from a virtual NGO, so we generate that by scanning all the
   * NGOs and creating that data. This is technically a model function, but its here now and I'm
   * not religious about any kind of code architecture enough to bother moving it.
   * @returns
   */
  async buildGovCharity(db) {
    if (!db) {
      throw new Error("Database not provided to buildGovCharity");
    }
    updateStatus(
      `Building US Govt from ${
        Object.keys(Charity.charityLookup).length
      } charities`
    );
    const gov_ein = this.GOV_EIN;
    const gov_proto = {
      filer_ein: gov_ein,
      filer_name: "US Government",
      name: "US Government",
      xml_name: "The Beast",
      contrib_amt: 4.6e12,
      tax_year: "2025",
      org_type: "USG",
      receipt_amt: 0,
      govt_amt: 1,
      total_assets: null,
      form_type: null,
      denominator: null,
    };

    // Register US Government charity in lookup first
    try {
      Charity.buildCharityFromRow(gov_proto);
    } catch (error) {
      console.error(
        `Failed to register US Government charity in lookup:`,
        error
      );
      throw error;
    }

    const govChar = Charity.getCharity(gov_ein);
    let govGrants = 0;
    let processList = Object.values(Charity.charityLookup)
      .filter((c) => c.govt_amt)
      .sort((a, b) => b.govt_amt - a.govt_amt);
    const govCount = processList.length;
    let govTotal = 0;
    const totalGrants = processList.reduce((sum, c) => sum + c.govt_amt, 0);
    const grantRecords = [];

    let chunk = processList.slice(0, CHUNK_SIZE);
    processList = processList.slice(CHUNK_SIZE);
    while (chunk.length) {
      chunk.forEach((c) => {
        if (c.govt_amt > 0) {
          const filer = gov_ein;
          const grantee = c.id;
          let amt = c.govt_amt;
          if (isNaN(amt)) amt = 0;
          govGrants++;
          const grant = {
            id: `${filer}~${grantee}`,
            filer_ein: filer,
            grant_ein: grantee,
            amt: amt,
            grantType: "gov",
          };
          Grant.loadGrantRow(grant, "gov");
          grantRecords.push(grant);
          govTotal += amt;
        }
      });
      updateStatus(
        `<span>Gov processing: ${formatNumber(
          Object.keys(Charity.charityLookup).length
        )} charities, ${formatNumber(
          Object.keys(Grant.grantLookup).length
        )} grants</span><span class="text-[13px] opacity-60">${Math.round(
          (govGrants / govCount) * 100
        )}% ${Math.round(
          (govTotal / totalGrants) * 100
        )}% ${govGrants}/${govCount} ${formatNumber(govTotal)}/${formatNumber(
          totalGrants
        )} complete</span>`,
        "green"
      );
      await new Promise((resolve) => setTimeout(resolve, 0));
      chunk = processList.slice(0, CHUNK_SIZE);
      processList = processList.slice(CHUNK_SIZE);
    }

    try {
      if (DEBUGLOG) console.time("storeGovCharity");
      await storeData(db, CHARITY_STORE, [gov_proto]);
      if (DEBUGLOG) console.timeEnd("storeGovCharity");
    } catch (error) {
      console.error(`Failed to store government charity:`, error);
      throw error;
    }

    try {
      if (DEBUGLOG) console.time("storeGovGrants");
      await storeData(db, GRANT_STORE, grantRecords);
      if (DEBUGLOG) console.timeEnd("storeGovGrants");
    } catch (error) {
      console.error(`Failed to store government grants:`, error);
      throw error;
    }

    updateStatus(
      `<span>Gov charity complete: ${formatNumber(
        Object.keys(Charity.charityLookup).length
      )} charities, ${formatNumber(
        Object.keys(Grant.grantLookup).length
      )} grants</span><span class="text-[13px] opacity-60">${
        govChar.grants.length
      } generated, ${formatNumber(govTotal)}</span>`
    );
    govChar.isGov = true;
    this.GOV_NODE = govChar;
    GOV_NODE = govChar;
    return govChar;
  }

  /**
   * So I had to pick smothign ast the starting point, so I place the 5 largest root notes.
   */
  loadDefaultData() {
    const usGov = this.GOV_NODE;
    updateStatus("placing US Government");
    usGov.desiredVisible = true;
    usGov.expandOutflows(TOP_N_INITIAL);
    updateStatus(
      `USG placed adding top ${TOP_N_INITIAL} roots`,
      "green",
      false
    );
    this.getRootCharities()
      .slice(1, TOP_N_INITIAL) // skip USG, already placed.
      .forEach((c) => {
        c.desiredVisible = true;
        c.expandOutflows(START_REVEAL);
      });
    this.computeImpliedVisibility(null, true, true);
  }

  /** So the sankey was messing with the data, so we have to reset the link data post
   * render.
   */
  cleanAfterRender() {
    if (this.renderData && this.renderData.links) {
      this.renderData.links.forEach((link) => link.resetSourceTarget());
    }
  }
}

/**
 * Class to hold an NGO.
 */
export function resetGraph() {
  Charity.charityLookup = {};
  Charity._desiredCharities = new Set();
  Charity._visibleCharities = new Set();
  Charity._organizedCharities = new Set();
  Charity.usgDirect = new Set();
  Grant.grantLookup = {};
  Grant.missingValues = {};
  Grant._desiredGrants = new Set();
}

export class Charity {
  /** charities are stored in an object by EIN for quick lookup */
  static charityLookup = {};
  static _desiredCharities = new Set();
  static _visibleCharities = new Set();
  static _organizedCharities = new Set();
  static usgDirect = new Set();

  toString() {
    return `${this.name} - ${this.ein}`;
  }

  /** Basic methods for puting charites into and out of the lookup */
  static getCharity(ein) {
    if (!ein) return null;
    const parts = ein.split(/[:~]/);
    return Charity.charityLookup[parts[0]];
  }

  static registerCharity(ein, c) {
    Charity.charityLookup[ein] = c;
  }

  /** accessors are convenient */
  static get visibleCharities() {
    return Charity._visibleCharities;
    //return Object.values(Charity.charityLookup).filter((c) => c.isVisible);
  }

  static get invisibleCharities() {
    return Object.values(Charity.charityLookup).filter((c) => !c.isVisible);
  }

  static get allCharities() {
    return Object.values(Charity.charityLookup)
      .filter((c) => !c.isVisible)
      .sort((a, b) => b.denominator - a.denominator);
  }

  static get impliedCharities() {
    return Object.values(Charity.charityLookup).filter(
      (c) => c.impliedVisible > 0
    );
  }

  static get desiredCharities() {
    return Charity._desiredCharities;
    //return Object.values(Charity.charityLookup).filter((c) => c.desiredVisible);
  }

  static get getCharityCount() {
    return Object.keys(Charity.charityLookup).length;
  }

  /**
   * Clear all caches
   */
  static disorganzeAll() {
    Charity._organizedCharities.forEach((c) => (c.isOrganized = false));
  }

  /**
   * Factory for building one from a data file row.
   * @param {} row
   * @returns
   */

  static buildCharityFromRow(row) {
    function titleCase(str) {
      return str
        .toLowerCase()
        .split(" ")
        .map((word) => word.charAt(0).toUpperCase() + word.slice(1))
        .join(" ");
    }
    const ein = row.filer_ein;
    if (!ein) {
      console.warn(`Skipping charity row: missing filer_ein`, row);
      return;
    }
    const name = row.name || row.filer_name || "Unknown Charity";
    let rAmt = parseInt(row.receipt_amt || "0", 10) || 0;
    let gAmt = parseInt(row.govt_amt || "0", 10) || 0;
    let cAmt = parseInt(row.contrib_amt || "0", 10) || 0;
    return new Charity({
      ein,
      name: titleCase(name),
      xml_name: row.xml_name,
      receipt_amt: rAmt,
      govt_amt: gAmt,
      contrib_amt: cAmt,
      tax_year: row.tax_year || "N/A",
      org_type: row.org_type || null,
      total_assets: row.total_assets || null,
      form_type: row.form_type || null,
      denominator: row.denominator || null,
      row,
    });
  }

  static kindFrom(row, ein) {
    return kindFrom(row, ein);
  }

  get isGhost() {
    return this.kind === "ghost";
  }

  get isLeftover() {
    return this.kind === "leftover";
  }

  get isBmfOnly() {
    return this.kind === "bmf";
  }

  get has990Card() {
    return this.kind === "charity" && !this.isGov;
  }

  static TSV_MANUAL_COLUMNS = [
    "tax_year",
    "org_type",
    /*"comp_pct",
    "comp_ptile",
    "travel_pct",
    "travel_ptile",
    "conferences_pct",
    "conferences_ptile",
    "grants_pct",
    "grants_ptile",
    "foreign_expenses_pct",
    "foreign_expenses_ptile",
    "grift_ratio",*/
    "total_assets",
    "form_type",
    "denominator",
    "street",
    "city",
    "state",
    "zip",
    /*"foreign_office",
    "foreign_expenses",
    "grift",*/
  ];
  /** It is what it is. */
  constructor({
    ein,
    name,
    xml_name,
    govt_amt = 0,
    contrib_amt = 0,
    receipt_amt = 0,
    grants = [],
    grantsIn = [],
    desiredVisible = false,
    isOrganized = false,
    row,
  }) {
    this.id = ein; // these 3 are interchangeable
    this.ein = ein;
    this.filer_ein = ein;
    this.name = name;
    this.xml_name = xml_name;
    this.receipt_amt = receipt_amt;
    this.govt_amt = govt_amt;
    this.contrib_amt = contrib_amt;
    this.grants = grants;
    this.grantsIn = grantsIn;
    this._desiredVisible = desiredVisible;
    this._impliedVisible = 0;
    this.isOrganized = isOrganized;
    this.isGov = false;
    this.expanded = false;
    this._valueCache = {};
    this.sourceLinks = [];
    this.targetLinks = [];
    this.govDepth = Infinity;
    this.isGov = this.ein == GOV_EIN;
    this.kind = Charity.kindFrom(row, ein);
    this.suggestedEin = (row && (row.suggested_ein || row.suggestedEin)) || null;
    if (this.govt_amt > 0) {
      Charity.usgDirect.add(this);
      this.govDepth = 0;
    } else {
    }
    Charity.loadExtraData(this, row);
    Charity.registerCharity(ein, this);
  }

  static loadExtraData(obj, raw_row) {
    for (const mkey of Charity.TSV_MANUAL_COLUMNS) {
      if (mkey in raw_row) {
        // Convert numeric fields
        if (
          [
            "tax_year",
            "comp_pct",
            "comp_ptile",
            "travel_pct",
            "travel_ptile",
            "conferences_pct",
            "conferences_ptile",
            "grants_pct",
            "grants_ptile",
            "foreign_expenses_pct",
            "foreign_expenses_ptile",
            "grift_ratio",
            "total_assets",
            "denominator",
            "foreign_expenses",
            "grift",
          ].includes(mkey)
        ) {
          if (
            raw_row.org_type == "backfill" ||
            raw_row.org_type == "ghost" ||
            raw_row.org_type == "leftover"
          ) {
            obj[mkey] = -1;
          } else {
            const value = parseFloat(raw_row[mkey]);
            obj[mkey] = isNaN(value) ? null : value;
          }
        }
        // Convert boolean field
        else if (mkey === "foreign_office") {
          const value =
            typeof raw_row[mkey] === "string"
              ? raw_row[mkey].toLowerCase()
              : raw_row[mkey];
          obj[mkey] =
            value === "true" ||
            value === "yes" ||
            value === "1" ||
            value === true;
        }
        // Strings
        else {
          obj[mkey] = raw_row[mkey];
        }
      } else {
        // Handle missing fields (default or error)
        obj[mkey] = null; // Or throw new Error(`Missing field: ${mkey}`);
      }
    }
  }

  /**
   * Note the OR here, a node is visible if its impliedVisible by a desired node
   * or if it itself is desired.
   */
  get isVisible() {
    return this.impliedVisible > 0 || this.desiredVisible;
  }

  getMaxDepth() {
    return this.maxDepth || 2;
  }

  findAllPaths(startNode, maxDepth = 5) {
    const markedYes = new Set();
    const memo = new Map();
    const depths = new Map();
    // states
    const states = new Map();

    function dfs(node, depth = 0) {
      if (depth > maxDepth) return false;
      const ein = node.ein;
      if (memo.has(ein)) return memo.get(ein);

      if (node.govDepth === Infinity) {
        memo.set(ein, false);
        return false;
      }

      if (node.govDepth > maxDepth - depth) {
        memo.set(ein, false);
        return false;
      }

      let state = states.get(ein) || 0;
      if (state === 1) return false;

      states.set(ein, 1);

      let found = node.govt_amt > 0;

      for (const grant of node.grantsIn) {
        const neighbor = grant.filer;
        if (neighbor.govDepth === Infinity) continue;
        if (neighbor.govDepth > maxDepth - depth - 1) continue;

        const subFound = dfs(neighbor, depth + 1);
        if (subFound) found = true;
      }

      if (found && depth > 0) {
        markedYes.add(ein);
        depths.set(ein, node.govDepth);
      }

      memo.set(ein, found);
      states.set(ein, 2);
      return found;
    }

    dfs(startNode);
    console.log("depths:", depths);
    return markedYes;
  }

  /**
   * Compute all the paths to the USG from this charity, and set them to desired visible
   */
  porkClick() {
    const choices = this.grantsIn.filter(
      (g) => g.filer.govDepth == this.govDepth - 1
    );
    let reveal = 0;
    for (const g of choices) {
      if (!g.filer.desiredVisible) reveal++;
      g.filer.desiredVisible = true;
    }
    this.maxDepth = this.getMaxDepth() + 1;
    return { depth: this.maxDepth, reveal: reveal };
  }

  billionarieClick() {
    const billionaires = viewModel.getBillionaireOrgs();
    const bpaths = this.findAllPaths(
      this,
      (target = (c) => billionaires.has(c.ein))
    );
    for (const p of bpaths) {
      p.desiredVisible = true;
    }
  }

  /**
   * We use this when we're trying to pare down a graph
   */

  clearVisibility() {
    this.desiredVisible = false;
    this.impliedVisible = 0;
    this.visibleGrantsIn.forEach((g) => {
      g.impliedVisible = false;
      g.desiredVisible = false;
    });
    this.visibleGrants.forEach((g) => {
      g.impliedVisible = false;
      g.desiredVisible = false;
    });
  }

  get desiredVisible() {
    return this._desiredVisible;
  }

  set desiredVisible(value) {
    if (this._desiredVisible !== value) {
      this._desiredVisible = value;
      this.isOrganized = false;
      if (value) Charity._desiredCharities.add(this);
      else Charity._desiredCharities.delete(this);
      if (
        value &&
        viewModel.debugCloneDesired &&
        !viewModel.debugCloneDesired.has(this)
      ) {
        if (DEBUGSTOP) debugger;
      }
    }
  }

  get impliedVisible() {
    //if (!this.isOrganized) this.organize(); not necessary
    return this._impliedVisible;
  }

  set impliedVisible(value) {
    if (this._impliedVisible !== value) {
      this._impliedVisible = value;
      this.isOrganized = false;
      if (value || this.desiredVisible) Charity._visibleCharities.add(this);
      else Charity._visibleCharities.delete(this);
      if (
        value &&
        viewModel.debugCloneVisible &&
        !viewModel.debugCloneVisible.has(this)
      ) {
        if (DEBUGSTOP) debugger;
      }
    }
  }

  /**
   * Canonically EIN form
   */
  get longEIN() {
    if (this.isGhost || this.isLeftover) return "";
    if (!this.ein || this.ein.length !== 9) return this.ein || "";
    return `${this.ein.slice(0, 2)}-${this.ein.slice(2)}`;
  }

  get propublica990Id() {
    const matches = this.xml_name.match(/(\d*)_public.xml/);
    return matches ? `${matches[1]}` : "";
  }

  /** can only grow to the left if there are grants to show */
  get canExpandInflows() {
    return this.invisibleGrantsIn.length > 0;
  }

  /** can only grow to the right if there are grants to show */
  get canExpandOutflows() {
    return this.invisibleGrants.length > 0;
  }

  /** can only suck grants back in if there are grants to suck back in */
  get canCompressInflows() {
    return this.visibleGrantsIn.length > 0;
  }

  /** can only suck grants back in if there are grants to suck back in */
  get canCompressOutflows() {
    return this.visibleGrants.length > 0;
  }

  /** an NGO that doesn't make any grants of its own is terminal, either because
   * they've sucked up the money into "adminstraiton" or because they just buy stuff
   * on their own, which we have no way of seeing.
   */
  get isTerminal() {
    return this.grants.length === 0;
  }
  /**
   * An NGO that doesn't get money from the GOVT or another charity is a root.
   */
  get isRoot() {
    return this.grantsIn.length === 0;
  }

  /**
   * Ok, a whole bunch of caching accessors on the various kinds of relation ships and
   * the summed values they have. The only thing tricky is that
   * scaled values are stored with the POWER_LAW they were calculated under
   * so that if the POWER_LAW changes, the values will be automatically
   * updated. Also stored based on the number of visible grants for a similar reason.
   */
  get logGrantsTotal() {
    const cacheKey = `logGrantTotal-${viewModel.POWER_LAW}-${this.grants.length}`;
    if (this._valueCache[cacheKey]) return this._valueCache[cacheKey];
    return (this._valueCache[cacheKey] = scaleValue(this.grantsTotal));
  }

  get logGrantsInTotal() {
    const cacheKey = `logGrantsInTotal-${viewModel.POWER_LAW}-${this.grantsIn.length}`;
    if (this._valueCache[cacheKey]) return this._valueCache[cacheKey];
    return (this._valueCache[cacheKey] = scaleValue(this.grantsInTotal));
  }

  get grantsLogTotal() {
    const vgrants = this.visibleGrants; // use all grants for scaling now
    const cacheKey = `grantsLogTotal-${viewModel.POWER_LAW}-${vgrants.length}`;
    if (this._valueCache[cacheKey]) return this._valueCache[cacheKey];
    if (vgrants.length)
      return (this._valueCache[cacheKey] = vgrants.reduce(
        (total, g) => total + g.value,
        0
      ));
    return 0;
  }

  get grantsInLogTotal() {
    const vgrants = this.visibleGrantsIn; // use all grants for scaling
    const cacheKey = `grantsInLogTotal-${viewModel.POWER_LAW}-${vgrants.length}`;
    if (this._valueCache[cacheKey]) return this._valueCache[cacheKey];
    if (vgrants.length)
      return (this._valueCache[cacheKey] = vgrants.reduce(
        (total, g) => total + g.value,
        0
      ));
    return 0;
  }

  get grantsTotal() {
    const cacheKey = `grantsTotal`;
    if (this._valueCache[cacheKey]) return this._valueCache[cacheKey];
    return (this._valueCache[cacheKey] = this.grants.reduce(
      (total, g) => total + g.amt,
      0
    ));
  }

  get grantsInTotal() {
    const cacheKey = `grantsInTotal`;
    if (this._valueCache[cacheKey]) return this._valueCache[cacheKey];
    return (this._valueCache[cacheKey] = this.grantsIn.reduce(
      (total, g) => total + g.amt,
      0
    ));
  }

  get visibleGrantsTotal() {
    const cacheKey = `visibleGrantsTotal`;
    if (this._valueCache[cacheKey]) return this._valueCache[cacheKey];
    return (this._valueCache[cacheKey] = this.visibleGrants.reduce(
      (total, g) => total + g.amt,
      0
    ));
  }

  get visibleGrantsInTotal() {
    const cacheKey = `visibleGrantsInTotal`;
    if (this._valueCache[cacheKey]) return this._valueCache[cacheKey];
    return (this._valueCache[cacheKey] = this.visibleGrantsIn.reduce(
      (total, g) => total + g.amt,
      0
    ));
  }

  get invisibleGrantsTotal() {
    const cacheKey = `invisibleGrantsTotal`;
    if (this._valueCache[cacheKey]) return this._valueCache[cacheKey];
    return (this._valueCache[cacheKey] = this.invisibleGrants.reduce(
      (total, g) => total + g.amt,
      0
    ));
  }

  /**
   * A grant can only consider itself visible if both its nodes are
   * visible.
   */

  /**
   * Grants only consider themselves visible if both ends are visible, but
   * when propogating visibility, we just need to know if the grants
   * would like to be visible.
   */
  get looseVisibleGrants() {
    if (!this.isOrganized) this.organize();
    const cacheKey = `looseVisibleGrants`;
    if (this._valueCache[cacheKey]) return this._valueCache[cacheKey];
    return (this._valueCache[cacheKey] = this.grants.filter(
      (g) => g.isLooseVisible
    ));
  }

  get looseVisibleGrantsIn() {
    if (!this.isOrganized) this.organize();
    const cacheKey = `looseVisibleGrantsIn`;
    if (this._valueCache[cacheKey]) return this._valueCache[cacheKey];
    return (this._valueCache[cacheKey] = this.grantsIn.filter(
      (g) => g.isLooseVisible
    ));
  }

  get visibleGrants() {
    if (!this.isOrganized) this.organize();
    const cacheKey = `visibleGrants`;
    if (this._valueCache[cacheKey]) return this._valueCache[cacheKey];
    return (this._valueCache[cacheKey] = this.grants.filter(
      (g) => g.isVisible
    ));
  }

  get invisibleGrants() {
    if (!this.isOrganized) this.organize();
    const cacheKey = `invisibleGrants`;
    if (this._valueCache[cacheKey]) return this._valueCache[cacheKey];
    return (this._valueCache[cacheKey] = this.grants.filter(
      (g) => !g.isVisible
    ));
  }

  get visibleGrantsIn() {
    if (!this.isOrganized) this.organize();
    const cacheKey = `visibleGrantsIn`;
    if (this._valueCache[cacheKey]) return this._valueCache[cacheKey];
    return (this._valueCache[cacheKey] = this.grantsIn.filter(
      (g) => g.isVisible
    ));
  }

  get invisibleGrantsIn() {
    if (!this.isOrganized) this.organize();
    const cacheKey = `invisibleGrantsIn`;
    if (this._valueCache[cacheKey]) return this._valueCache[cacheKey];
    return (this._valueCache[cacheKey] = this.grantsIn.filter(
      (g) => !g.isVisible
    ));
  }

  get hasVisibleGrants() {
    return this.visibleGrants.length > 0;
  }

  /** accessor to trash the cache */
  set isOrganized(value) {
    if (this._isOrganized !== value) {
      this._valueCache = {};
      this._isOrganized = value;
      if (value) {
        Charity._organizedCharities.add(this);
      } else {
        Charity._organizedCharities.delete(this);
      }
      this.clearValueCache(); // force regen
    }
  }

  /**
   * Accessors for maingining the root lists, and managing the cache
   */
  addGrant(grant) {
    if (grant instanceof Grant) {
      this.grants.push(grant);
      this.isOrganized = false;
    } else {
      console.error("Error: Can only add Grant objects.");
    }
  }

  addGrantIn(grant) {
    if (grant instanceof Grant) {
      this.grantsIn.push(grant);
      this.isOrganized = false;
      if (grant.filer.govDepth < this.govDepth) {
        this.govDepth = Math.min(this.govDepth, grant.filer.govDepth + 1);
        //console.log(grant.filer.name, "is USG to", this.name);
      }
    } else {
      console.error("Error: Can only add Grant objects.");
    }
  }

  static addGrant(g) {
    const filer = Charity.charityLookup[g.filer_ein];
    const grantee = Charity.charityLookup[g.grant_ein];
    if (filer && grantee) {
      filer.addGrant(g);
      grantee.addGrantIn(g);
    }
  }

  removeGrant(grant) {
    const index = this.grants.indexOf(grant);
    if (index !== -1) {
      this.grants.splice(index, 1);
      this.isOrganized = false;
      this._origOut += grant.amt;
    }
  }

  removeGrantIn(grant) {
    const index = this.grantsIn.indexOf(grant);
    if (index !== -1) {
      this.grantsIn.splice(index, 1);
      this.isOrganized = false;
      this._origIn += grant.amt;
    }
  }

  clearValueCache() {
    this._valueCache = {};
  }

  /** Part of organizing is keeping the grants sorted */
  organize() {
    if (!this.isOrganized) {
      this.grants.sort((a, b) => b.amt - a.amt);
      this.grantsIn.sort((a, b) => b.amt - a.amt);
      this.isOrganized = true;
    }
  }

  /** Mark a grant circular have to tell both sides*/
  static circularGrant(g) {
    g.grantee.circleGrant(g);
    g.filer.circleGrant(g);
    Grant.unregisterGrant(g);
  }

  /** nice when debugging */
  get grantsTotalString() {
    return formatNumber(this.grantsTotal);
  }

  get invisibleTotalString() {
    return formatNumber(this.invisibleGrantsTotal);
  }

  /**
   * A-B-A is a simple circle which we can handle in a filter
   * Might as well.
   */
  simpleCircular() {
    return this.grants.filter((g1) =>
      g1.grantee.grants.some((g2) => g2.grant_ein === this.ein)
    );
  }

  /** This may be DEAD CODE now */
  handleClick(e, count = -1) {
    if (e.altKey) return this.tunnelNode(e);
    if (e.metaKey || this.isTerminal) {
      if (DEBUGLOG) console.log(`Hiding ${this.id} ${this.name}`);
      this.hide();
      return false;
    }
    if (DEBUGLOG) console.log(`Expanding ${this.id} ${this.name}`);
    this.expandDown(NEXT_REVEAL);
    this.expandUp(NEXT_REVEAL);
    return true;
  }

  /** This should be DEAD CODE now */
  handleGrantClick(e, g) {
    g.filer.handleClick(e, -1);
    g.grantee.handleClick(e, -1);
  }

  /**
   * Swim upstream, making grants visible
   * @param {*} count
   */
  expandInflows(count = NEXT_REVEAL) {
    if (!count || count == "0") return;
    const grantsToReveal = this.invisibleGrantsIn.slice(0, count); // count largest
    grantsToReveal.forEach((grant) => {
      grant.desiredVisible = true; // propogates both directions
    });
    viewModel.resetEIN(this.ein);

    this.isOrganized = false;
  }

  /** make some of the upstream grands invisible */
  // do we need a reference count instead of a simple flag?
  compressInflows(count = NEXT_REVEAL) {
    /*const grantsToHide = this.visibleGrantsIn.slice(-count); // count smallest
    grantsToHide.forEach((grant) => {
      grant.clearVisibility();
    });
    viewModel.resetEIN(this.ein);

    this.isOrganized = false;*/
    let newCount = this.visibleGrantsIn.length - count;
    if (newCount < 0) newCount = 0;
    viewModel.addToShowList(
      `${this.ein}~${newCount}~${this.visibleGrants.length}}`
    ); // match URL will do this for us.
  }

  /**
   * Expand downwards
   * @param {*} count
   */
  expandOutflows(count = NEXT_REVEAL) {
    if (!count || count == "0") return;
    const grantsToReveal = this.invisibleGrants.slice(0, count);
    if (DEBUGLOG)
      console.log(
        `Expanding ${grantsToReveal.length} outflows for ${this.id} (total invisible: ${this.invisibleGrants.length})`
      );
    grantsToReveal.forEach((grant) => {
      grant.desiredVisible = true;
      if (DEBUGLOG)
        console.log(
          `  Grant ${grant.id} set visible, grantee ${grant.grantee.id} set visible`
        );
    });
    viewModel.resetEIN(this.ein);
    this.isOrganized = false;
  }

  compressOutflows(count = NEXT_REVEAL) {
    /*const grantsToHide = this.visibleGrants.slice(-count);
    grantsToHide.forEach((grant) => {
      grant.clearVisibility();
    });
    this.isOrganized = false;*/
    let newCount = this.visibleGrants.length - count;
    if (newCount < 0) newCount = 0;
    viewModel.addToShowList(
      `${this.ein}~${this.visibleGrantsIn.length}~${newCount}`
    ); // match URL will do this for us.
  }

  /**
   * These manipulate the Hide and HostLists too
   */

  show() {
    this.desiredVisible = true;
    viewModel.removeFromHideList(this.id);
    viewModel.addToBreadCrumbs(`Show|${this.id}`);
  }

  hide() {
    viewModel.addToBreadCrumbs(`Hide|${this.id}`);
    viewModel.addToHideList(this.id);
    this.desiredVisible = false;
    this.grantsIn.forEach((g) => this.clearVisibility());
    this.grants.forEach((g) => this.clearVisibility());
  }

  /**
   *
   * @returns EIN:numberIncoming:numberOutgoing
   */
  URLPiece() {
    if (!this.desiredVisible) return null;
    return `${this.ein}~${this.visibleGrantsIn.length}~${this.visibleGrants.length}`;
  }

  /**
   * DO these search terms match?
   * @param {*} keywords
   * @returns
   */

  searchMatch(regexes) {
    return regexes.some((r) => r.test(this.name));
  }

  /**
   *   So at one point I was thinking instead of constantly extending the graph
   * I'd provide a way that it would just jump to a new starting point.
   */
  tunnelNode() {
    viewModel.pushFocusSnapshot();
    viewModel.clearAll();
    viewModel.clearKeywordList();
    viewModel.setShowList([this.ein]);
    viewModel.focusTip = { title: this.name || this.ein };
    viewModel.setZoom(null, null, null);
    viewModel.computeAndSaveURLParams();
  }

  /**
   *  "placing a node" means making it desired, and making sure there
   * are the matching number of visible grants.
   * @param {*} upCount
   * @param {*} downCount
   */
  place(upCount = START_REVEAL, downCount = START_REVEAL) {
    this.desiredVisible = true;
    if (this.visibleGrants.length < downCount)
      this.expandOutflows(downCount - this.visibleGrants.length);
    if (this.visibleGrantsIn.length < upCount)
      this.expandInflows(upCount - this.visibleGrantsIn.length);
    this.organize();
    this.expanded = true;
    if (DEBUGLOG)
      console.log(
        `Placed ${this.id}: ${this.visibleGrants.length} outflows visible, ${this.invisibleGrants.length} outflows invisible, ${this.visibleGrantsIn.length} inflows visible`
      );
  }

  get kindCaption() {
    if (this.isGov) return "US Government";
    if (this.ein === PATIENT_SUBSIDY_ID) return "Patient subsidies";
    if (this.isLeftover) return "Below this cut";
    if (this.isGhost) return "Name-only";
    if (this.isBmfOnly) return "BMF only (no 990 here)";
    if (this.has990Card) return "Charity";
    return "Organization";
  }

  get orgShort() {
    if (this.isGhost) return "Name-only (no EIN on the 990)";
    if (this.ein === PATIENT_SUBSIDY_ID)
      return "Name-only (HIPAA-redacted copays / patient assistance)";
    if (this.isLeftover)
      return `Name-only (see more below ${bandCutLabel(
        viewModel?.loadedBand || defaultBandId()
      )})`;
    if (this.isBmfOnly) return "Name-only (no 990 in this set)";
    if (!this.org_type) return "n/a";
    if (this.ein === "001") return "US Government";
    if (this.ein.length == 3) return "Country";
    const orgLookup = ORGANIZATION_TYPES[this.org_type];
    if (!orgLookup) return "???";

    return `${orgLookup.shortDescription} ${this.org_type.replace("501", "")}`;
  }
  usgIndirectGrift() {
    let grift = 0;
    const griftMap = {};
    for (const grant of this.grantsIn) {
      if (grant.filer.govDepth < Infinity && !grant.filer.isGov) {
        grift += grant.amt;
        griftMap[grant.filer.govDepth] =
          (griftMap[grant.filer.govDepth] || 0) + grant.amt;
      }
    }
    return { grift, griftMap };
  }
  /**
   * Technically a VM responsibility, but we just do it here.
   * @returns
   */
  toolTipText() {
    const bacon = "\u{1F953}";
    const stop = "\u{1F6D1}"; //stop sign
    let pork = "\u{1F437}"; // pig emoji
    if (this.govDepth > 0 && this.govDepth != Infinity) {
      pork = `${bacon} ${this.govDepth}`;
    }
    if (this.govDepth == Infinity) pork = stop; // no path to USG

    let outFlows = this.grantsTotal
      ? `\ngrants out: $${formatNumber(this.grantsTotal)}`
      : `\nout: N/A`;
    let inFlows = this.grantsInTotal
      ? `\ngrants in: $${formatNumber(this.grantsInTotal)}`
      : `\nin: N/A`;
    let gov = "";
    if (this.govt_amt > 0) {
      gov = `\nUSG ${formatNumber(this.govt_amt)}`;
      const { grift } = this.usgIndirectGrift();
      if (grift > 0) gov += `\nInd. USG ${formatNumber(grift)}`;
    }

    const idLine = this.longEIN
      ? this.longEIN
      : this.isGhost
        ? "not an IRS EIN"
        : "";
    return `${this.name} (${this.tax_year || "N/A"})\n${this.orgShort}\n${idLine}${gov}${inFlows}${outFlows}\n${pork}`;
  }

  get griftRating() {
    function griftGrade(ptile) {
      if (ptile >= 95) return "F-";
      if (ptile >= 90) return "F";
      if (ptile >= 80) return "D";
      if (ptile >= 70) return "C";
      if (ptile >= 60) return "B";
      if (ptile >= 50) return "A";
      return "-";
    }
    const ptileFields = [
      this.comp_ptile,
      this.travel_ptile,
      this.conferences_ptile,
      this.grants_ptile,
      this.foreign_expenses_ptile,
      this.grift_ratio,
    ];
    const validPtiles = ptileFields.filter((val) => val != null && !isNaN(val));

    const griftiest = validPtiles.length > 0 ? Math.max(...validPtiles) : null;
    return `${griftGrade(griftiest)} - ${griftiest}%`;
  }

  /** links to elsewhere in the site */
  officersLink() {
    return `/officers/?nonprofit_kw=${this.ein}`;
  }

  financialsLink() {
    return `/nonprofit/assets/?filter=${this.ein}`;
  }

  nonprofitsLink() {
    return `/nonprofit/?filter=${this.ein}`;
  }

  propublicaLink(message) {
    return `<a href="https://projects.propublica.org/nonprofits/organizations/${this.ein}/${this.propublica990Id}/full" target="_blank" rel="noopener noreferrer" class="whitespace-nowrap">${message}</a>`;
  }
  googleLink(message) {
    const params = new URLSearchParams();
    const q = this.longEIN ? `${this.longEIN} ${this.name}` : this.name;
    params.set("q", q);
    return `<a href="https://google.com/search?${params.toString()}" target="_blank" rel="noopener noreferrer" class="whitespace-nowrap">${message}</a>`;
  }

  mapsLink(message) {
    const addr = [this.street, this.city, this.state, this.zip]
      .map((p) => (p && String(p).trim()) || "")
      .filter(Boolean)
      .join(", ");
    const q = addr || this.name || this.ein;
    const params = new URLSearchParams();
    params.set("api", "1");
    params.set("query", q);
    return `<a href="https://www.google.com/maps/search/?${params.toString()}" target="_blank" rel="noopener noreferrer" class="whitespace-nowrap">${message}</a>`;
  }

  grokLink(message) {
    const who = this.longEIN
      ? `${this.name} (EIN ${this.longEIN})`
      : this.name;
    const params = new URLSearchParams();
    params.set(
      "q",
      `I want a Grumpy Take on: ${who}\n\nRead and apply fully: https://gist.github.com/twinforces/534d9b662de4a010c1c4ebad934cd99a`
    );
    return `<a href="https://grok.com/?${params.toString()}" target="_blank" rel="noopener noreferrer" class="whitespace-nowrap">${message}</a>`;
  }

  grantSearchLink(message) {
    return `<a href="/award_search/?keywords=${this.longEIN}" target="_blank">${message}</a>`;
  }

  streetViewLink(message) {
    const encodedAddress = encodeURIComponent(node.address);
    // Public Google Maps URL with Street View (layer=c enables Street View)
    return `<a href="https://www.google.com/maps/place/${encodedAddress}?layer=c" target="_blank"><img src=https://www.flaticon.com/free-icons/street-view" title='${message} - icon by Flaticon.com'></a>`;
  }
}

/**
 * The edge as opposed to a Charity node.
 * filer: from
 * grantee: to
 *
 * aliases for source and target for sankey
 */
export class Grant {
  /** so we can find a grant quickly */
  static grantLookup = {};
  static missingValues = {};
  static _desiredGrants = new Set();

  static getGrant(id) {
    return Grant.grantLookup[id];
  }

  static registerGrant(g) {
    Grant.grantLookup[g.id] = g;
  }

  static unregisterGrant(g) {
    delete Grant.grantLookup[g.id];
  }

  /**
   * 600,000 grants, only a few charities visible, have to be visible for
   * grant to show, so we work backwards from visible charities.
   */
  static get visibleGrants() {
    // work backwards from visible charities
    const visibleGrants = new Set();
    for (const c of Charity.visibleCharities) {
      for (const g of c.grants) if (g.isVisible) visibleGrants.add(g.id);
      for (const g of c.grantsIn) if (g.isVisible) visibleGrants.add(g.id);
    }
    let result = [];
    for (const id of visibleGrants) {
      const g = Grant.grantLookup[id];
      if (g) result.push(g);
      else console.error(`Couldn't find grant ${g} in visibleGrants`);
    }
    return result;
  }

  static get desiredGrants() {
    return this._desiredGrants;
  }

  /** Commong pattern */
  static get allGrants() {
    return Object.values(Grant.grantLookup);
  }

  /** used when reading from the file */
  static checkGrantMatch(filer_ein, grant_ein) {
    return (
      filer_ein !== grant_ein &&
      Charity.getCharity(filer_ein) &&
      Charity.getCharity(grant_ein)
    );
  }

  /** grants are unique by filer/grantee */
  static grantIDBuilder(filer_ein, grant_ein) {
    return `${filer_ein}~${grant_ein}`;
  }

  /** factory for the file read */
  static loadGrantRow(row, grantType) {
    let filer_ein = row.filer_ein;
    let grant_ein = row.grant_ein;
    if (filer_ein?.length === 7) filer_ein = "0" + filer_ein;
    if (grant_ein?.length === 7) grant_ein = "0" + grant_ein;
    let amt = parseInt(row.grant_amt || row.amt || "0", 10);
    if (isNaN(amt) || amt === 0) {
      console.warn(`Invalid or zero grant_amt/amt for grant row:`, {
        filer_ein,
        grant_ein,
        grant_amt: row.grant_amt,
        amt: row.amt,
      });
      amt = 0;
    }
    if (
      !filer_ein ||
      !grant_ein ||
      filer_ein === grant_ein ||
      grant_ein === "Unknown" ||
      !isGraphKey(grant_ein)
    ) {
      console.warn(`Invalid EINs for grant row:`, {
        filer_ein,
        grant_ein,
        amt,
      });
      return null;
    }
    if (!Charity.getCharity(filer_ein)) {
      console.warn(`Missing filer_ein ${filer_ein} for grant`, row);
      Grant.missingValues[filer_ein] = "filer";
    }
    if (!Charity.getCharity(grant_ein)) {
      console.warn(
        `Missing grant_ein ${grant_ein} for grant with amount ${amt}`,
        row
      );
      Grant.missingValues[grant_ein] = `grantee-${amt}`;
    }
    const id = Grant.grantIDBuilder(filer_ein, grant_ein);
    const g = Grant.getGrant(id);
    if (g) {
      g.addAmt(amt);
      return g;
    } else {
      return new Grant({
        filer_ein,
        grant_ein,
        amt,
        grantType,
        inferred: !!row.inferred,
        suggested_ein: row.suggested_ein || "",
      });
    }
  }

  /** it is what it is */
  constructor({
    filer_ein,
    grant_ein,
    amt = 0,
    isCircular = false,
    desiredVisible = false,
    grantType = "regular",
    inferred = false,
    suggested_ein = "",
  }) {
    this.registered = false;
    this.amt = amt;
    this.filer_ein = filer_ein;
    this.grant_ein = grant_ein;
    this.inferred = inferred;
    this.suggested_ein = suggested_ein || "";
    this.filer = Charity.getCharity(filer_ein);
    this.grantee = Charity.getCharity(grant_ein);
    if (this.grantee && this.suggested_ein && this.grantee.isGhost) {
      this.grantee.suggestedEin = this.suggested_ein;
    }
    this._desiredVisible = desiredVisible;
    this._impliedVisible = false;
    this._isCircular = isCircular;
    this.sourceLinks = [];
    this.targetLinks = [];
    this._source = null;
    this._target = null;
    Charity.addGrant(this);
    this.registered = true;
    this.grantType = grantType;
    this.buildId();
  }

  /** see Charity for the split visibility explanation */
  get isVisible() {
    return (
      this.isLooseVisible || (this.filer.isVisible && this.grantee.isVisible)
    );
  }

  /** see Charity for the split visibility explanation
   *
   * We need the loose visible when propagating to capture intent.
   */
  get isLooseVisible() {
    return this.desiredVisible || this.impliedVisible; // || this.isVisible;
  }

  /**
   * This is how the visibility propogates, goes one step to filer/grantee
   */
  set isVisible(value) {
    if (value) {
      if (this.filer) {
        this.filer.impliedVisible++;
      }
      if (this.grantee) {
        this.grantee.impliedVisible++;
      }
    } else {
      if (this.filer) {
        this.filer.impliedVisible--;
      }
      if (this.grantee) {
        this.grantee.impliedVisible--;
      }
    }
    // Propagate organization state changes to connected charities
    if (this.filer) this.filer.isOrganized = false;
    if (this.grantee) this.grantee.isOrganized = false;
  }

  /**
   * accessors
   * One nice thing about accessors is it makes it trivial to set breakpoints
   * when things change
   */
  get desiredVisible() {
    return this._desiredVisible;
  }

  set desiredVisible(value) {
    if (this._desiredVisible !== value) {
      this._desiredVisible = value;
      this.disorganize();
      if (value) Grant._desiredGrants.add(this);
      else Grant._desiredGrants.delete(this);
      if (!value) {
        if (this.filer) {
          this.filer.impliedVisible--;
        }
        if (this.grantee) {
          this.grantee.impliedVisible--;
        }
      } else {
        if (this.filer) {
          this.filer.impliedVisible++;
        }
        if (this.grantee) {
          this.grantee.impliedVisible++;
        }
      }
    }
  }

  get impliedVisible() {
    return this._impliedVisible;
  }

  set impliedVisible(value) {
    if (this._impliedVisible != value) {
      this._impliedVisible = value;
      if (!value) {
        if (this.filer) {
          this.filer.impliedVisible--;
        }
        if (this.grantee) {
          this.grantee.impliedVisible--;
        }
      } else {
        if (this.filer) {
          this.filer.impliedVisible++;
        }
        if (this.grantee) {
          this.grantee.impliedVisible++;
        }
      }
      // Propagate organization state changes to connected charities
      if (this.filer) this.filer.isOrganized = false;
      if (this.grantee) this.grantee.isOrganized = false;
    }
  }
  /** accessors to match the sankey API */
  get source() {
    return this._source || this.filer_ein;
  }

  set source(s) {
    this._source = s;
  }

  get target() {
    return this._target || this.grant_ein;
  }

  set target(t) {
    this._target = t;
  }

  /**
   * So we scale the amount so we can see both small and large grants.
   * However, one side effect of this is because sqrt(a+b) != sqrt(a) + sqrt(b)
   */
  get value() {
    return scaleValue(this.amt);
  }

  get scaledAmt() {
    return scaleValue(this.amt);
  }

  /** apsirational code to show what % of grants a particular grant represents */
  get relativeInAmount() {
    return this.amt / (this.filer.grantsTotal + 1);
  }

  get relativeAmount() {
    return this.amt / (this.grantee.grantsTotal + 1);
  }

  toolTipText() {
    const from = (this.filer && this.filer.name) || this.filer_ein || "?";
    const to = (this.grantee && this.grantee.name) || this.grant_ein || "?";
    return `${from} → ${to}\n$${formatNumber(this.amt)}${
      this.circular ? " (circular)" : ""
    }`;
  }

  clearVisibility() {
    this.impliedVisible = false;
    this.desiredVisible = false;
    this.disorganize();
  }

  /** probably aspirational but if either is charity is hidden so are we */
  shouldHide() {
    return (
      viewModel.shouldHide(this.filer_ein) ||
      viewModel.shouldHide(this.grant_ein)
    );
  }

  /** so the way the data load works, different grants betweeen the same two NGOs will
   * appear, so we have to aggregate.
   */
  addAmt(amt) {
    this.amt += amt;
  }

  /**
   * build the ID for this grant, and register it
   * @returns
   */
  buildId() {
    this.id = Grant.grantIDBuilder(this.filer_ein, this.grant_ein);
    Grant.registerGrant(this);
    return this.id;
  }

  /** flow disorganization up to the filer and grantee */
  disorganize() {
    this.filer.isOrganized = false;
    this.grantee.isOrganized = false;
  }

  /**
   * sankey will read the ID, then map that to a Charity, and write it back.
   *
   * Which is ok, except when it fails matching on objects later.
   * Best to reset them back to IDs.
   */
  resetSourceTarget() {
    this._source = null;
    this.sourceLinks = [];
    this._target = null;
    this.targetLinks = [];
  }

  /** Convenience */
  toString() {
    return `${this.id} ${formatNumber(this.amt)} (${this.value})`;
  }

  /**
   * A version of tunneling for grants, show just the two nodes involved.
   */
  tunnelGrant() {
    Charity.desiredCharities.forEach((c) => (c.desiredVisible = false));
    Object.values(Grant.grantLookup).forEach((g) => (g.desiredVisible = false));
    this.desiredVisible = true;
    this.filer_ein.desiredVisible = true;
    this.grant_ein.desiredVisible = true;
  }
}

/**
 * Utility function
 * @param {*} message
 * @param {*} color
 * @param {*} loading
 */
function updateStatus(message, color = "black", loading = true) {
  $("#status").html(`<span class="flex flex-col items-end text-sm">
    ${loading ? "<span>Loading...</span>" : ""}
    ${message}</span>`);
}

viewModel = new BrowseViewModel();

export { viewModel };
