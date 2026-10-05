// A submission is what the creator and pack forms file as a GitHub issue. It carries only the field values
// the person changed; the workflow in .github/workflows/submission.yml applies them to the stored file with
// the same functions the page previews with, and works out permission and hosting itself.
// Nothing in a submission is trusted: it is checked against an allowlist of fields and then against the schema.
import { REPO, dumpYaml, indexNames, nameKey, normalizeUrl } from './form-core.mjs';
import { FIELDS as CREATOR_FIELDS, ID_PATTERN, RESERVED_IDS, applyCreator } from './creator-form.mjs';
import { FIELDS as PACK_FIELDS, KEY_PATTERN, applyPack } from './pack-form.mjs';

export const TEMPLATE = 'submission.yml';
export const LABEL = 'submission';
export const MAX_BYTES = 65536;
/** GitHub refuses a prefilled issue address from 8192 bytes; this leaves room for the rest of the address. */
export const MAX_LINK = 7500;

const COSTS = ['free', 'free_with_ads', 'paid', 'unknown'];
const HOSTING = ['hosted', 'listed'];

export class SubmissionError extends Error {
  constructor(errors) {
    super(errors.join('; '));
    this.errors = errors;
  }
}

export const dirFor = (kind) => (kind === 'creator' ? 'data/creators' : 'data/packs');
export const pathFor = (kind, id) => `${dirFor(kind)}/${id}.yaml`;

// ---- filing ----------------------------------------------------------------------------------------

export const makeSubmission = ({ kind, op, id, set, creating = null }) => ({
  v: 1, kind, op, id, set, ...(creating ? { new: creating } : {}),
});

export const titleFor = (sub) => `${sub.op === 'create' ? 'Add' : 'Edit'} ${sub.kind} ${sub.id}`;

/** The address of the issue form with the submission filled in. */
export function issueUrl(sub) {
  return `https://github.com/${REPO}/issues/new?template=${TEMPLATE}&title=${encodeURIComponent(titleFor(sub))}` +
    `&payload=${encodeURIComponent(JSON.stringify(sub))}`;
}

// ---- reading ---------------------------------------------------------------------------------------

/** The submission inside an issue body made by the issue form (a fenced json block under "Submission"). */
export function parseIssueBody(body) {
  const m = /^###[ \t]+Submission[ \t]*(?:\r?\n)+```json[ \t]*\r?\n([\s\S]*?)\r?\n```/m.exec(String(body ?? ''));
  if (!m) throw new SubmissionError(['No submission was found in the issue']);
  if (m[1].length > MAX_BYTES) throw new SubmissionError(['The submission is too large']);
  try {
    return JSON.parse(m[1]);
  } catch {
    throw new SubmissionError(['The submission is not valid JSON']);
  }
}

const isObject = (v) => v !== null && typeof v === 'object' && !Array.isArray(v);

function* strings(value, path = '') {
  if (typeof value === 'string') yield [path, value];
  else if (Array.isArray(value)) for (const [i, v] of value.entries()) yield* strings(v, `${path}[${i}]`);
  else if (isObject(value)) for (const [k, v] of Object.entries(value)) yield* strings(v, path ? `${path}.${k}` : k);
}

/**
 * Check a submission and apply it. ctx: { read(kind, id) -> stored record or null, creators: [{ id, name, aliases }],
 * validate(kind, record) -> [message], date }. Returns { path, kind, op, id, rec, text }; throws SubmissionError.
 */
export function applySubmission(sub, ctx) {
  const errors = [];
  const fail = (m) => errors.push(m);
  if (!isObject(sub)) throw new SubmissionError(['The submission is not an object']);
  for (const k of Object.keys(sub)) if (!['v', 'kind', 'op', 'id', 'set', 'new'].includes(k)) fail(`Unknown field “${k}”`);
  if (sub.v !== 1) fail('Unsupported submission version');
  if (!['creator', 'pack'].includes(sub.kind)) fail('The kind is not creator or pack');
  if (!['create', 'update'].includes(sub.op)) fail('The operation is not create or update');
  if (errors.length) throw new SubmissionError(errors);

  const { kind, op, id } = sub;
  const idOk = kind === 'creator' ? ID_PATTERN.test(id) : KEY_PATTERN.test(id);
  if (typeof id !== 'string' || !idOk) throw new SubmissionError(['The identifier is not valid']);
  if (kind === 'creator' && RESERVED_IDS.includes(id)) throw new SubmissionError(['That handle is reserved']);

  const fields = kind === 'creator' ? CREATOR_FIELDS : PACK_FIELDS;
  if (!isObject(sub.set)) throw new SubmissionError(['The changes are missing']);
  for (const k of Object.keys(sub.set)) if (!fields.includes(k)) fail(`“${k}” cannot be changed by a submission`);
  if (Object.keys(sub.set).length === 0) fail('There is nothing to change');

  const wantsNew = kind === 'pack' && op === 'create';
  if (wantsNew) {
    if (!isObject(sub.new) || !COSTS.includes(sub.new.cost) || !HOSTING.includes(sub.new.hosting) || Object.keys(sub.new).length !== 2) {
      fail('A new pack needs a cost and hosted or listed only');
    }
  } else if ('new' in sub) fail('“new” applies only to a new pack');

  for (const [path, s] of strings(sub.set)) {
    if (/[\u0000-\u001f\u007f]/.test(s)) fail(`${path}: control characters are not accepted`);
    if (/^https?:\/\//i.test(s)) {
      const r = normalizeUrl(s);
      if (r.error) fail(`${path}: ${r.error}`);
    }
  }
  if (errors.length) throw new SubmissionError(errors);

  const base = ctx.read(kind, id);
  if (op === 'create' && base) throw new SubmissionError([`${kind} “${id}” already exists`]);
  if (op === 'update' && !base) throw new SubmissionError([`There is no ${kind} “${id}” to change`]);

  // An image's stored copy is made by the pipeline; a submission can keep one that exists but not name another.
  if (kind === 'pack') {
    const have = new Set((base?.media?.images ?? []).map((i) => i.storage_key).filter(Boolean));
    for (const i of sub.set.media?.images ?? []) if (i?.storage_key && !have.has(i.storage_key)) fail('A picture cannot name a stored copy');
    if (errors.length) throw new SubmissionError(errors);
  }

  const rec = kind === 'creator'
    ? applyCreator({ base, id, set: sub.set })
    : applyPack({ base, key: id, set: sub.set, creating: wantsNew ? sub.new : null, date: ctx.date });

  // Shapes are only trusted once the schema has passed them.
  errors.push(...ctx.validate(kind, rec));
  if (errors.length) throw new SubmissionError(errors);

  const known = new Set(ctx.creators.map((c) => c.id));
  if (kind === 'pack') {
    for (const c of rec.credits ?? []) if (!known.has(c.creator)) fail(`credits: no creator “${c.creator}”`);
    for (const i of rec.media?.images ?? []) if (i.credit && !known.has(i.credit)) fail(`pictures: no creator “${i.credit}”`);
    if (wantsNew && (rec.credits ?? []).length === 0) fail('credits: a new pack needs at least one creator');
  } else {
    const had = new Set([base?.name, ...(base?.aliases ?? [])].filter(Boolean));
    const owners = indexNames(ctx.creators.filter((c) => c.id !== id));
    for (const n of [rec.name, ...(rec.aliases ?? [])]) {
      const owner = n && !had.has(n) ? owners.get(nameKey(n)) : null;
      if (owner) fail(`“${n}” already belongs to ${owner.name}`);
    }
  }
  if (errors.length) throw new SubmissionError(errors);

  return { path: pathFor(kind, id), kind, op, id, rec, text: dumpYaml(rec) };
}
