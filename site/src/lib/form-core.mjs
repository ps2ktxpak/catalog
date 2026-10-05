// What the creator and pack forms share: address checks, the YAML style of the Python tools, name matching
// and the GitHub links. No DOM, so the tests can run it in Node.
import YAML from 'yaml';

export const REPO = 'ps2ktxpak/catalog';
export const BRANCH = 'main';

const MAX_URL = 2048;

export const isEmpty = (v) =>
  v == null || v === '' || (Array.isArray(v) && v.length === 0) || (typeof v === 'object' && !Array.isArray(v) && Object.keys(v).length === 0);

/** rec with its keys in `order` first (the rest after), and empty values dropped, as ordered() in common.py. */
export function ordered(rec, order, keep = []) {
  const drop = (k, v) => isEmpty(v) && !keep.includes(k);
  const out = {};
  for (const k of order) if (k in rec && !drop(k, rec[k])) out[k] = rec[k];
  for (const [k, v] of Object.entries(rec)) if (!(k in out) && !drop(k, v)) out[k] = v;
  return out;
}

// ---- names -----------------------------------------------------------------------------------------

/** Same rules as slugify() in tools/ps2ktxpak/common.py. */
export function slugify(s) {
  return s
    .normalize('NFKD')
    .replace(/[^\x00-\x7f]/g, '')
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, '-')
    .replace(/-{2,}/g, '-')
    .replace(/^-+|-+$/g, '');
}

/** Same rules as name_key() in common.py: what two spellings of one name have in common. */
export function nameKey(s) {
  return s.toLowerCase().replace(/[^a-z0-9]/g, '');
}

/** Which creator each name or alias belongs to, matched ignoring case and punctuation. creators: [{ id, name, aliases }] */
export function indexNames(creators) {
  const owners = new Map();
  for (const c of creators) {
    for (const n of [c.name, ...(c.aliases ?? [])]) {
      const k = nameKey(n);
      if (k && !owners.has(k)) owners.set(k, c);
    }
  }
  return owners;
}

// ---- addresses -------------------------------------------------------------------------------------

/** { url } for an address that can be stored, { url, error } for one that cannot. A bare host gets https://. */
export function normalizeUrl(input) {
  const s = String(input ?? '').trim();
  if (!s) return { url: '' };
  if (/\s/.test(s)) return { url: s, error: 'Addresses cannot contain spaces' };
  if (/^[^/@:]+@[^/@:]+\.[^/@:]+$/.test(s)) return { url: s, error: 'An email address is not accepted' };
  let url = s;
  if (/^https:\/\//i.test(s)) {
    // as typed
  } else if (/^http:\/\//i.test(s)) {
    return { url: s, error: 'Addresses must start with https://' };
  } else if (/^[a-z][a-z0-9+.-]*:\/\//i.test(s) || /^(mailto|javascript|data|tel):/i.test(s)) {
    return { url: s, error: 'Only https:// addresses are accepted' };
  } else {
    url = `https://${s}`;
  }
  let parsed;
  try {
    parsed = new URL(url);
  } catch {
    return { url, error: 'Not a valid address' };
  }
  if (parsed.username || parsed.password) return { url, error: 'Addresses cannot contain a username or password' };
  if (!parsed.hostname.includes('.')) return { url, error: 'Not a valid address' };
  if (url.length > MAX_URL) return { url, error: 'Address is too long' };
  return { url };
}

// ---- YAML ------------------------------------------------------------------------------------------

const STYLE = { version: '1.1', indentSeq: false, lineWidth: 0, singleQuote: true };

/**
 * YAML in the style of the Python dumper: sequences flush with their key, single quotes, no folding. The
 * library prefers double quotes for a string with an apostrophe; the Python side writes single quotes, so a
 * quoted string with an apostrophe is forced to match and an untouched file round-trips.
 */
export function dumpYaml(obj) {
  const doc = new YAML.Document(obj, { version: STYLE.version });
  YAML.visit(doc, {
    Scalar(_key, node) {
      if (typeof node.value === 'string' && node.value.includes("'") && !node.value.includes('"')) {
        if (YAML.stringify(node.value, STYLE).startsWith('"')) node.type = 'QUOTE_SINGLE';
      }
    },
  });
  return doc.toString(STYLE);
}

// ---- GitHub ----------------------------------------------------------------------------------------

export const githubRaw = (path) => `https://raw.githubusercontent.com/${REPO}/${BRANCH}/${path}`;
/** The web editor on an existing file. It cannot be prefilled; the text goes in by paste. */
export const githubEdit = (path) => `https://github.com/${REPO}/edit/${BRANCH}/${path}`;
/** The web editor on a new file, prefilled. Without write access GitHub forks the repository and opens a pull request. */
export const githubNew = (path, text) =>
  `https://github.com/${REPO}/new/${BRANCH}?filename=${encodeURIComponent(path)}&value=${encodeURIComponent(text)}`;
