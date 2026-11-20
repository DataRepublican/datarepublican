/** Share encodings. Gist raw is CORS-friendly; news and X are not.
 *
 * `#d=` is a URL fragment, so nginx's 4096 limit does not apply. Chrome still
 * chokes around 32k, which is why we refuse rather than silently truncate.
 */

export const FRAGMENT_MAX = 24000;
export const ALLOWED_HOSTS = new Set([
  "gist.githubusercontent.com",
  "raw.githubusercontent.com",
]);

export function isAllowedRemote(url) {
  let u;
  try {
    u = new URL(url);
  } catch {
    return false;
  }
  if (u.protocol !== "https:") return false;
  if (ALLOWED_HOSTS.has(u.hostname)) return true;
  return false;
}

/** Same-origin fixtures and extract files are fine; anything else must be allowlisted. */
export function isAllowedLoadUrl(url, origin = "") {
  if (!url) return false;
  try {
    const u = new URL(url, origin || "https://datarepublican.com");
    if (origin && u.origin === new URL(origin).origin) {
      return u.pathname.startsWith("/sankeybuilder/");
    }
    return isAllowedRemote(u.href);
  } catch {
    return false;
  }
}

function utf8Bytes(str) {
  if (typeof TextEncoder !== "undefined") return new TextEncoder().encode(str);
  return Uint8Array.from(Buffer.from(str, "utf8"));
}

function bytesToB64url(bytes) {
  let bin = "";
  for (let i = 0; i < bytes.length; i++) bin += String.fromCharCode(bytes[i]);
  const b64 =
    typeof btoa === "function"
      ? btoa(bin)
      : Buffer.from(bytes).toString("base64");
  return b64.replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/g, "");
}

function b64urlToBytes(s) {
  const pad = s.length % 4 === 0 ? "" : "=".repeat(4 - (s.length % 4));
  const b64 = s.replace(/-/g, "+").replace(/_/g, "/") + pad;
  if (typeof atob === "function") {
    const bin = atob(b64);
    const out = new Uint8Array(bin.length);
    for (let i = 0; i < bin.length; i++) out[i] = bin.charCodeAt(i);
    return out;
  }
  return Uint8Array.from(Buffer.from(b64, "base64"));
}

export function encodeFragment(doc) {
  const json = JSON.stringify(doc);
  const token = bytesToB64url(utf8Bytes(json));
  if (token.length > FRAGMENT_MAX) return null;
  return token;
}

export function decodeFragment(token) {
  if (!token) throw new Error("empty fragment");
  const bytes = b64urlToBytes(token);
  const json =
    typeof TextDecoder !== "undefined"
      ? new TextDecoder().decode(bytes)
      : Buffer.from(bytes).toString("utf8");
  return JSON.parse(json);
}

export function parseLocationShare(search, hash) {
  const h = String(hash || "");
  const q = new URLSearchParams(String(search || "").replace(/^\?/, ""));
  const dMatch = h.match(/[#&]d=([^&]+)/);
  if (dMatch) return { type: "fragment", value: decodeURIComponent(dMatch[1]) };
  const gMatch = h.match(/[#&]g=([^&]+)/);
  if (gMatch) return { type: "gist", value: decodeURIComponent(gMatch[1]) };
  if (q.get("url")) return { type: "url", value: q.get("url") };
  if (q.get("gist")) return { type: "gist", value: q.get("gist") };
  return null;
}

/** Accept a gist id, a gist page URL, or a raw gist URL. */
export function gistRawUrl(value) {
  const s = String(value || "").trim();
  if (!s) return "";
  if (s.startsWith("https://gist.githubusercontent.com/")) return s;
  const page = s.match(
    /^https:\/\/gist\.github\.com\/([^/]+)\/([0-9a-f]+)(?:\/.*)?$/i,
  );
  if (page) {
    return `https://gist.githubusercontent.com/${page[1]}/${page[2]}/raw`;
  }
  if (/^[0-9a-f]+$/i.test(s) && s.length >= 8) {
    return "";
  }
  return "";
}
