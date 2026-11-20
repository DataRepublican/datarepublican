/** Color from ein || slug. Same hash as browse/models.js hashEIN, duplicated
 * on purpose: importing browse/models.js boots CharityDatabase.
 *
 * Cubehelix matches browse when window.d3 is present; tests stub it.
 */

export function hashId(id) {
  const s = String(id || "node");
  let hash = 2862953042;
  const padded = s.length === 3 ? s.padEnd(9, "0") : s;
  for (let i = 0; i < padded.length; i++) {
    const weight = i < 2 ? 2 : 1;
    hash ^= padded.charCodeAt(i) * weight;
    hash = (hash * 16777619) >>> 0;
  }
  return (hash % 1000000) / 1000000;
}

function interpolateBand(t, baseBrightness, mod_brightness) {
  const abs_diff = Math.abs(t - 0.5);
  const brightness = Math.max(0.05, baseBrightness - mod_brightness * abs_diff);
  const saturation = 1.5 - 1.5 * abs_diff;
  const d3 = globalThis.d3 || (typeof window !== "undefined" && window.d3);
  if (d3 && typeof d3.cubehelix === "function") {
    return d3.cubehelix(360 * t - 65, saturation, brightness);
  }
  const h = ((360 * t - 65) % 360 + 360) % 360;
  const l = Math.round(brightness * 100);
  const s = Math.round(Math.min(100, saturation * 50));
  return `hsl(${h.toFixed(1)} ${s}% ${l}%)`;
}

const brightnessBands = [
  { base: 0.7, mod: 0.8 },
  { base: 0.5, mod: 0.6 },
  { base: 0.4, mod: 0.3 },
  { base: 0.3, mod: 0.2 },
];

const bandOffset = 1;

function colorBandIndex(id) {
  const s = String(id || "0");
  const lastDigit = parseInt(s.slice(-1), 10);
  const n = Number.isFinite(lastDigit) ? lastDigit : s.charCodeAt(s.length - 1);
  return (n + bandOffset) % 4;
}

/** Stable color key: EIN digits when we have them, otherwise the node id. */
export function colorKeyFor(node) {
  if (!node) return "node";
  if (typeof node === "string") return node;
  return node.ein || node.id || slugFallback(node.name);
}

function slugFallback(name) {
  return String(name || "node")
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, "-")
    .replace(/^-+|-+$/g, "") || "node";
}

export function getColorForId(id) {
  const key = String(id || "node");
  const t = hashId(key);
  const band = brightnessBands[colorBandIndex(key)];
  return interpolateBand(t, band.base, band.mod);
}

export function getTextColorForId(id) {
  const key = String(id || "node");
  const t = hashId(key);
  let bandIndex = colorBandIndex(key) + 1;
  bandIndex = Math.min(3, bandIndex);
  const band = brightnessBands[bandIndex];
  return interpolateBand(t, band.base, band.mod);
}

export function colorString(c) {
  return c && typeof c.toString === "function" ? c.toString() : String(c);
}
