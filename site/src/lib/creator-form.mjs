// The creator form's logic, with no DOM so the tests can run it in Node against the real data files.
//
// A creator is data/creators/<id>.yaml. The form turns a draft into that file's text in the same style
// the repository's files are written in, so an untouched record round-trips byte for byte and a pull request
// shows only what changed.
import {
  githubEdit, githubNew, githubRaw, indexNames, isEmpty, nameKey, normalizeUrl, ordered, slugify,
} from './form-core.mjs';

export { BRANCH, REPO, dumpYaml, indexNames, nameKey, normalizeUrl, slugify } from './form-core.mjs';

export const ID_PATTERN = /^[a-z0-9][a-z0-9_-]{0,47}$/;
/** Ids that would collide with a route under /creators/. */
export const RESERVED_IDS = ['edit'];

/** What the form can change, by field path. */
export const FIELDS = ['name', 'aliases', 'links.page', 'links.distribution', 'links.tip', 'links.socials'];

const ORDER = ['id', 'name', 'aliases', 'links', 'avatar', 'identity', 'status'];

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

/** The values of the form's fields, by field path. */
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

const orNull = (v) => (isEmpty(v) ? null : v);

/** What a draft says about every field, by path; a field with nothing in it is null. */
export function valuesFromDraft(draft) {
  const { clean } = cleanDraft(draft);
  return {
    name: clean.name,
    aliases: orNull(clean.aliases),
    'links.page': orNull(clean.links.page),
    'links.distribution': orNull(clean.links.distribution),
    'links.tip': orNull(clean.links.tip),
    'links.socials': orNull(clean.links.socials),
  };
}

/** Only what differs from `base` (or, for a new creator, only what is filled in): the body of a submission. */
export function submissionSet({ draft, base = null }) {
  const values = valuesFromDraft(draft);
  const before = snapshot(base);
  const set = {};
  for (const path of FIELDS) {
    const changed = base ? JSON.stringify(orNull(before[path])) !== JSON.stringify(values[path]) : values[path] !== null;
    if (changed) set[path] = values[path];
  }
  return set;
}

function setPath(rec, path, value) {
  const [head, leaf] = path.split('.');
  if (!leaf) {
    if (value === null) delete rec[head];
    else rec[head] = value;
    return;
  }
  rec[head] ??= {};
  if (value === null) delete rec[head][leaf];
  else rec[head][leaf] = value;
  if (Object.keys(rec[head]).length === 0) delete rec[head];
}

/**
 * The creator record after `set` (values by field path, null clearing one) is applied to `base`, or to a new
 * creator `id` when `base` is null. A field not in `set` is left as it was. The browser previews a submission
 * with this and the workflow applies it with this, so what is previewed is what is filed.
 */
export function applyCreator({ base = null, id, set }) {
  const rec = base ? structuredClone(base) : { id, status: 'active' };
  for (const path of FIELDS) if (path in set) setPath(rec, path, set[path]);
  return ordered(rec, ORDER);
}

/** The record for a draft. `base` is the stored record when editing, null for a new creator. */
export function buildCreator({ draft, base = null }) {
  return applyCreator({ base, id: cleanDraft(draft).clean.id, set: valuesFromDraft(draft) });
}

// ---- checking --------------------------------------------------------------------------------------

/**
 * Everything wrong with a draft, as { field, message, creator? }. `validate` is a compiled JSON Schema
 * validator for schema/creator.schema.json; `creators` is [{ id, name, aliases }] for every stored creator.
 */
export function check({ draft, base = null, creators, validate }) {
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
    const rec = buildCreator({ draft, base });
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
/** The editor on a new file with nothing filled in but its name, for a file too long to prefill. */
export const emptyNewFileUrl = (id) => githubNew(filePath(id), '');
