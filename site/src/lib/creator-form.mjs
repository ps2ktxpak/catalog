// The creator form's logic, with no DOM so the tests can run it in Node against the real data files.
//
// A creator is data/creators/<id>.yaml. The form turns a draft into that file's text in the same style
// the Python tools write it, so an untouched record round-trips byte for byte and a pull request shows
// only what changed. Fields a person sets are added to `locked` and given a provenance entry, which is
// how the importers know not to overwrite them.
import {
  SOURCE, githubEdit, githubNew, githubRaw, indexNames, isEmpty, nameKey, normalizeUrl, ordered, slugify,
} from './form-core.mjs';

export { BRANCH, REPO, SOURCE, dumpYaml, indexNames, nameKey, normalizeUrl, slugify } from './form-core.mjs';

export const ID_PATTERN = /^[a-z0-9][a-z0-9_-]{0,47}$/;
/** Ids that would collide with a route under /creators/. */
export const RESERVED_IDS = ['edit'];

/** What the form can change, as the paths `locked` and `provenance` use. */
export const FIELDS = ['name', 'aliases', 'links.page', 'links.distribution', 'links.tip', 'links.socials'];

const ORDER = ['id', 'name', 'aliases', 'links', 'avatar', 'identity', 'status', 'provenance', 'locked'];
const LINK_ORDER = ['page', 'distribution', 'tip', 'socials'];

// ---- names -----------------------------------------------------------------------------------------

/** A free id for a new creator, derived the way Creators.ensure() derives it. */
export function newId(name, existingIds) {
  const taken = new Set([...existingIds, ...RESERVED_IDS]);
  const base = (slugify(name) || 'creator').slice(0, 44).replace(/^-+|-+$/g, '') || 'creator';
  let id = base;
  for (let n = 2; taken.has(id); n++) id = `${base}-${n}`;
  return id;
}

// ---- drafts ----------------------------------------------------------------------------------------

export const emptyDraft = () => ({ id: '', name: '', aliases: [], page: '', distribution: '', tip: [], socials: [] });

/** The editable view of a stored record. */
export function draftFromCreator(rec) {
  const links = rec.links ?? {};
  return {
    id: rec.id,
    name: rec.name ?? '',
    aliases: [...(rec.aliases ?? [])],
    page: links.page ?? '',
    distribution: links.distribution ?? '',
    tip: (links.tip ?? []).map((l) => ({ kind: l.kind, url: l.url })),
    socials: (links.socials ?? []).map((l) => ({ kind: l.kind, url: l.url })),
  };
}

/** The draft as it will be stored, plus a problem for every address that cannot be. */
export function cleanDraft(draft) {
  const problems = [];
  const addr = (field, value) => {
    const r = normalizeUrl(value);
    if (r.error) problems.push({ field, message: r.error });
    return r.url;
  };
  const name = String(draft.name ?? '').trim();
  const aliases = [];
  for (const a of draft.aliases ?? []) {
    const t = String(a ?? '').trim();
    if (t && t !== name && !aliases.includes(t)) aliases.push(t);
  }
  const list = (field, items) =>
    (items ?? [])
      .map((l, i) => ({ kind: l.kind, url: addr(`${field}.${i}`, l.url) }))
      .filter((l) => l.url);
  const clean = {
    id: String(draft.id ?? '').trim(),
    name,
    aliases,
    links: {
      page: addr('page', draft.page),
      distribution: addr('distribution', draft.distribution),
      tip: list('tip', draft.tip),
      socials: list('socials', draft.socials),
    },
  };
  return { clean, problems };
}

// ---- building the record ---------------------------------------------------------------------------

/** The values of the form's fields, by the path `locked` uses. */
function snapshot(rec) {
  const l = rec?.links ?? {};
  return {
    name: rec?.name ?? '',
    aliases: rec?.aliases ?? [],
    'links.page': l.page ?? '',
    'links.distribution': l.distribution ?? '',
    'links.tip': l.tip ?? [],
    'links.socials': l.socials ?? [],
  };
}

/**
 * The record for a draft. `base` is the stored record when editing, null for a new creator.
 * A field that differs from `base` is locked and given provenance; everything else is left as it was.
 */
export function buildCreator({ draft, base = null, date }) {
  const { clean } = cleanDraft(draft);
  const rec = base ? structuredClone(base) : { id: clean.id, status: 'active' };
  rec.name = clean.name;
  if (clean.aliases.length) rec.aliases = clean.aliases;
  else delete rec.aliases;

  const links = {};
  for (const k of [...Object.keys(base?.links ?? {}), ...LINK_ORDER]) {
    if (k in links) continue;
    const v = k in clean.links ? clean.links[k] : base.links[k];
    if (!isEmpty(v)) links[k] = v;
  }
  if (Object.keys(links).length) rec.links = links;
  else delete rec.links;

  const before = snapshot(base);
  const after = snapshot(rec);
  for (const path of FIELDS) {
    if (JSON.stringify(before[path]) === JSON.stringify(after[path])) continue;
    rec.provenance ??= {};
    rec.provenance[path] = isEmpty(after[path]) ? { source: SOURCE, date, note: 'cleared' } : { source: SOURCE, date };
    rec.locked ??= [];
    if (!rec.locked.includes(path)) rec.locked.push(path);
  }
  return ordered(rec, ORDER);
}

// ---- checking --------------------------------------------------------------------------------------

/**
 * Everything wrong with a draft, as { field, message, creator? }. `validate` is a compiled JSON Schema
 * validator for schema/creator.schema.json; `creators` is [{ id, name, aliases }] for every stored creator.
 */
export function check({ draft, base = null, creators, validate, date }) {
  const { clean, problems } = cleanDraft(draft);
  const out = [...problems];
  if (!clean.name) out.push({ field: 'name', message: 'A name is needed' });

  if (!base) {
    const ids = new Set(creators.map((c) => c.id));
    if (!ID_PATTERN.test(clean.id)) out.push({ field: 'id', message: 'Lower-case letters, digits, - and _ only, up to 48 characters' });
    else if (RESERVED_IDS.includes(clean.id)) out.push({ field: 'id', message: 'That handle is reserved' });
    else if (ids.has(clean.id)) out.push({ field: 'id', message: 'That handle is taken' });
  }

  // Only names this edit adds can conflict; a clash already in the data is not this edit's to fix.
  const had = new Set([base?.name, ...(base?.aliases ?? [])].filter(Boolean));
  const owners = indexNames(creators.filter((c) => c.id !== clean.id));
  for (const n of [clean.name, ...clean.aliases]) {
    if (!n || had.has(n)) continue;
    const owner = owners.get(nameKey(n));
    if (owner) out.push({ field: n === clean.name ? 'name' : 'aliases', message: `“${n}” already belongs to ${owner.name}`, creator: owner.id });
  }

  if (!out.length && validate) {
    const rec = buildCreator({ draft, base, date });
    if (!validate(rec)) {
      for (const e of validate.errors ?? []) out.push({ field: e.instancePath || '/', message: `${e.instancePath || 'record'} ${e.message}` });
    }
  }
  return out;
}

// ---- GitHub ----------------------------------------------------------------------------------------

export const filePath = (id) => `data/creators/${id}.yaml`;
export const rawUrl = (id) => githubRaw(filePath(id));
export const editUrl = (id) => githubEdit(filePath(id));
export const newFileUrl = (id, text) => githubNew(filePath(id), text);
