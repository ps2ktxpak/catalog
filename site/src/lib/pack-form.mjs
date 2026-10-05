// The pack form's logic, with no DOM so the tests can run it in Node against the real data files.
//
// A pack is data/packs/<key>.yaml. As with creators, an untouched record round-trips byte for byte, a field
// a person sets is locked and given provenance, and every list row keeps the stored item it came from
// (`keep`), so a field the form does not show (a picture's thumbnail, a video's uploader) survives an edit.
//
// A new pack starts hosted: hosting.state published, permission creator_approved. Until the conversion
// pipeline has made a copy there is no archive record, so the pack is published and awaiting conversion.
// "Listed only" files it as withheld instead.
import { SOURCE, githubEdit, githubNew, githubRaw, indexNames, isEmpty, nameKey, normalizeUrl, ordered } from './form-core.mjs';
import { parseSerials, parseYoutubeId } from './vocab.mjs';

export { dumpYaml } from './form-core.mjs';

export const KEY_PATTERN = /^[a-z0-9][a-z0-9-]{2,79}$/;
/** What the form can change, as the paths `locked` and `provenance` use. */
export const FIELDS = ['name', 'game', 'credits', 'type', 'completeness', 'description', 'sources', 'media'];

// Same order as PACK_ORDER in tools/ps2ktxpak/import_legacy.py.
const ORDER = ['key', 'catalog_id', 'name', 'game', 'credits', 'type', 'completeness', 'description', 'sources', 'media',
  'access', 'permission', 'hosting', 'needs_review', 'legacy', 'provenance', 'locked'];

// ---- keys ------------------------------------------------------------------------------------------

/** A free key for a new pack, derived as import_legacy.py derives it: lowest serial, then the lead creator. */
export function newKey(serials, lead, existingKeys) {
  const low = [...serials].sort()[0] ?? 'unknown';
  const base = `${low.toLowerCase()}-${lead || 'unknown'}`.slice(0, 76).replace(/-+$/, '');
  const taken = new Set(existingKeys);
  let key = base;
  for (let n = 2; taken.has(key); n++) key = `${base}-${n}`;
  return key;
}

/** Stored packs that share a serial with these: [{ key, name }], so a duplicate can be noticed. */
export function similarPacks(serials, packs, exceptKey = '') {
  const want = new Set(serials);
  return packs.filter((p) => p.key !== exceptKey && p.serials.some((s) => want.has(s))).map((p) => ({ key: p.key, name: p.name }));
}

// ---- drafts ----------------------------------------------------------------------------------------

export const emptyDraft = () => ({
  key: '', name: '', title: '', serials: '', credits: [], type: 'unknown', completeness: 'unknown', description: '',
  sources: [], cost: 'free', hosting: 'hosted', images: [], videos: [],
});

/** The editable view of a stored record. `creators`: [{ id, name, aliases }] */
export function draftFromPack(rec, creators) {
  const byId = new Map(creators.map((c) => [c.id, c]));
  const nameOf = (id) => byId.get(id)?.name ?? id;
  return {
    key: rec.key,
    name: rec.name ?? '',
    title: rec.game?.title ?? '',
    serials: (rec.game?.serials ?? []).join(', '),
    credits: (rec.credits ?? []).map((c) => ({ who: nameOf(c.creator), id: c.creator, role: c.role ?? 'author', note: c.note ?? '', keep: { ...c } })),
    type: rec.type ?? 'unknown',
    completeness: rec.completeness ?? 'unknown',
    description: rec.description ?? '',
    sources: (rec.sources ?? []).map((s) => ({ kind: s.kind, url: s.url, primary: !!s.primary, note: s.note ?? '', keep: { ...s } })),
    cost: rec.access?.cost ?? 'free',
    hosting: 'hosted',
    images: (rec.media?.images ?? []).map((i) => ({
      url: i.source_url ?? '', alt: i.alt ?? '', caption: i.caption ?? '', who: i.credit ? nameOf(i.credit) : '', id: i.credit ?? '', keep: { ...i },
    })),
    videos: (rec.media?.videos ?? []).map((v) => ({ url: `https://www.youtube.com/watch?v=${v.id}`, title: v.title ?? '', keep: { ...v } })),
  };
}

/** Overlay form values on the stored item: a value that is empty removes the field, anything else sets it in place. */
function overlay(keep, values) {
  const item = { ...(keep ?? {}) };
  for (const [k, v] of Object.entries(values)) {
    if (v === '') delete item[k];
    else item[k] = v;
  }
  return item;
}

/** The draft as it will be stored, plus a problem for everything that cannot be. */
export function cleanDraft(draft, creators) {
  const problems = [];
  const byId = new Map(creators.map((c) => [c.id, c]));
  const owners = indexNames(creators);
  const addr = (field, value) => {
    const r = normalizeUrl(value);
    if (r.error) problems.push({ field, message: r.error });
    return r.url;
  };
  const resolve = (row, field) => {
    const who = String(row.who ?? '').trim();
    if (!who) return '';
    if (row.id && byId.get(row.id)?.name === who) return row.id;
    const c = owners.get(nameKey(who));
    if (c) return c.id;
    problems.push({ field, message: `No creator named “${who}”`, missing: who });
    return '';
  };

  const { serials, bad } = parseSerials(draft.serials);
  for (const b of bad) problems.push({ field: 'serials', message: `“${b}” is not a game serial` });

  const credits = [];
  (draft.credits ?? []).forEach((c, i) => {
    const id = resolve(c, `credits.${i}`);
    if (!id) return;
    if (credits.some((x) => x.creator === id)) {
      problems.push({ field: `credits.${i}`, message: `${byId.get(id).name} is credited twice` });
      return;
    }
    credits.push(overlay(c.keep, { creator: id, role: c.role && c.role !== 'author' ? c.role : '', note: String(c.note ?? '').trim() }));
  });

  const sources = [];
  (draft.sources ?? []).forEach((s, i) => {
    const url = addr(`sources.${i}`, s.url);
    if (!url) return;
    const item = { ...(s.keep ?? {}), kind: s.kind, url };
    if (s.primary) item.primary = true;
    else if ('primary' in item) item.primary = false;
    const note = String(s.note ?? '').trim();
    if (note) item.note = note;
    else delete item.note;
    sources.push(item);
  });

  const images = [];
  (draft.images ?? []).forEach((m, i) => {
    const url = addr(`images.${i}`, m.url);
    const credit = resolve(m, `images.${i}`);
    const item = overlay(m.keep, {
      source_url: url, alt: String(m.alt ?? '').trim(), caption: String(m.caption ?? '').trim(), credit,
    });
    if (item.source_url || item.storage_key) images.push(item);
  });

  const videos = [];
  (draft.videos ?? []).forEach((v, i) => {
    const raw = String(v.url ?? '').trim();
    if (!raw) return;
    const id = parseYoutubeId(raw);
    if (!id) {
      problems.push({ field: `videos.${i}`, message: `“${raw}” is not a YouTube link` });
      return;
    }
    videos.push(overlay(v.keep, { provider: 'youtube', id, title: String(v.title ?? '').trim() }));
  });

  const clean = {
    key: String(draft.key ?? '').trim(),
    name: String(draft.name ?? '').trim(),
    title: String(draft.title ?? '').trim(),
    serials, credits, sources, images, videos,
    type: draft.type, completeness: draft.completeness,
    description: String(draft.description ?? '').trim(),
    cost: draft.cost, hosting: draft.hosting,
  };
  return { clean, problems };
}

// ---- building the record ---------------------------------------------------------------------------

const snapshot = (r) => ({
  name: r?.name ?? '',
  game: r?.game ?? {},
  credits: r?.credits ?? [],
  type: r?.type ?? '',
  completeness: r?.completeness ?? '',
  description: r?.description ?? '',
  sources: r?.sources ?? [],
  media: r?.media ?? {},
});

const orNull = (v) => (isEmpty(v) ? null : v);

/** What a draft says about every field; a field with nothing in it is null. `base` supplies the keys the form does not show. */
export function valuesFromDraft(draft, creators, base = null) {
  const { clean } = cleanDraft(draft, creators);
  const media = {};
  for (const k of [...Object.keys(base?.media ?? {}), 'images', 'videos']) {
    if (k in media) continue;
    const v = k === 'images' ? clean.images : k === 'videos' ? clean.videos : base.media[k];
    if (!isEmpty(v)) media[k] = v;
  }
  return {
    name: clean.name,
    game: { ...(base?.game ?? {}), title: clean.title, serials: clean.serials },
    credits: clean.credits,
    type: clean.type,
    completeness: clean.completeness,
    description: orNull(clean.description),
    sources: orNull(clean.sources),
    media: orNull(media),
  };
}

/** Only what differs from `base` (or, for a new pack, only what is filled in): the body of a submission. */
export function submissionSet({ draft, creators, base = null }) {
  const values = valuesFromDraft(draft, creators, base);
  const before = snapshot(base);
  const set = {};
  for (const f of FIELDS) {
    const changed = base ? JSON.stringify(orNull(before[f])) !== JSON.stringify(orNull(values[f])) : !isEmpty(values[f]) || f === 'credits';
    if (changed) set[f] = values[f];
  }
  return set;
}

/** What a new pack gets that the form does not let an existing pack change: cost, and hosted or listed only. */
export const newFields = (draft) => ({ cost: draft.cost, hosting: draft.hosting });

/**
 * The pack record after `set` (values by field, null clearing one) is applied to `base`, or to a new pack
 * `key` when `base` is null, in which case `creating` ({ cost, hosting }) decides its cost, permission and
 * hosting state. A field that ends up different is locked and given provenance; a field not in `set` is
 * left as it was. The browser previews a submission with this and the workflow applies it with this.
 *
 * Hosted: published, with permission creator_approved on the submitter's statement. Listed only: withheld,
 * permission unknown.
 */
export function applyPack({ base = null, key, set, creating = null, date }) {
  const rec = base ? structuredClone(base) : { key };
  const before = snapshot(base);
  for (const f of FIELDS) {
    if (!(f in set)) continue;
    if (set[f] === null) delete rec[f];
    else rec[f] = set[f];
  }

  const after = snapshot(rec);
  const note = (path, extra = {}) => {
    rec.provenance ??= {};
    rec.provenance[path] = { source: SOURCE, date, ...extra };
  };
  for (const path of FIELDS) {
    if (JSON.stringify(before[path]) === JSON.stringify(after[path])) continue;
    note(path, isEmpty(after[path]) ? { note: 'cleared' } : {});
    rec.locked ??= [];
    if (!rec.locked.includes(path)) rec.locked.push(path);
  }

  if (!base) {
    rec.access = { cost: creating.cost };
    note('access');
    if (creating.hosting === 'hosted') {
      rec.permission = { kind: 'creator_approved', date, note: 'Approval stated by the submitter on the web form.' };
      rec.hosting = { state: 'published', since: date };
    } else {
      rec.permission = { kind: 'unknown' };
      rec.hosting = { state: 'withheld', reason: 'Listed only, at the submitter’s request.', since: date };
    }
    note('permission');
    note('hosting');
  }
  return ordered(rec, ORDER, ['credits']);
}

/** The record for a draft. `base` is the stored record when editing, null for a new pack. */
export function buildPack({ draft, base = null, creators, date }) {
  return applyPack({
    base, key: cleanDraft(draft, creators).clean.key, set: valuesFromDraft(draft, creators, base),
    creating: base ? null : newFields(draft), date,
  });
}

// ---- checking --------------------------------------------------------------------------------------

/**
 * Everything wrong with a draft, as { field, message }. `validate` is a compiled JSON Schema validator for
 * schema/pack.schema.json; `creators` is [{ id, name, aliases }].
 */
export function check({ draft, base = null, creators, validate, date }) {
  const { clean, problems } = cleanDraft(draft, creators);
  const out = [...problems];
  const need = (ok, field, message) => ok || out.push({ field, message });

  need(clean.name, 'name', 'A name is needed');
  need(clean.title, 'title', 'A game title is needed');
  need(clean.serials.length > 0 || out.some((p) => p.field === 'serials'), 'serials', 'At least one game serial is needed');
  need(clean.description.length <= 2000, 'description', 'The description is limited to 2000 characters');
  if (clean.sources.filter((s) => s.primary).length > 1) out.push({ field: 'sources', message: 'Only one source can be the main one' });

  if (!base) {
    need(clean.credits.length > 0 || out.some((p) => p.missing), 'credits', 'At least one creator is needed');
    if (clean.hosting === 'hosted') need(clean.sources.length > 0, 'sources', 'Hosting needs a link to the files');
    need(KEY_PATTERN.test(clean.key), 'key', 'The file name could not be worked out; a serial and a creator are needed');
  }

  if (!out.length && validate) {
    const rec = buildPack({ draft, base, creators, date });
    if (!validate(rec)) {
      for (const e of validate.errors ?? []) out.push({ field: e.instancePath || '/', message: `${e.instancePath || 'record'} ${e.message}` });
    }
  }
  return out;
}

// ---- GitHub ----------------------------------------------------------------------------------------

export const filePath = (key) => `data/packs/${key}.yaml`;
export const rawUrl = (key) => githubRaw(filePath(key));
export const editUrl = (key) => githubEdit(filePath(key));
export const newFileUrl = (key, text) => githubNew(filePath(key), text);
/** The editor on a new file with only the name filled in, for a pack too large to prefill. */
export const emptyNewFileUrl = (key) => githubNew(filePath(key), '');
