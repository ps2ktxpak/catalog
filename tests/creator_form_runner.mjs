// Runs the creator form's logic (site/src/lib/creator-form.mjs) for the Python tests: reads one JSON
// request on stdin, writes one JSON response on stdout. Dependencies resolve from site/node_modules.
import fs from 'node:fs';
import { createRequire } from 'node:module';
import path from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const site = createRequire(path.join(root, 'site', 'package.json'));
const Ajv2020 = site('ajv/dist/2020').default;
const YAML = site('yaml');
const lib = (name) => import(pathToFileURL(path.join(root, 'site', 'src', 'lib', name)).href);
const form = await lib('creator-form.mjs');
const pack = await lib('pack-form.mjs');
const vocab = await lib('vocab.mjs');
const submission = await lib('submission.mjs');
const kinds = await lib('kinds.mjs');

const schema = JSON.parse(fs.readFileSync(path.join(root, 'schema', 'creator.schema.json'), 'utf8'));
const validate = new Ajv2020({ allErrors: true, strict: false }).compile(schema);
const packSchema = JSON.parse(fs.readFileSync(path.join(root, 'schema', 'pack.schema.json'), 'utf8'));
const validatePack = new Ajv2020({ allErrors: true, strict: false }).compile(packSchema);
const storedCreators = () =>
  fs.readdirSync(path.join(root, 'data', 'creators')).map((f) => {
    const c = YAML.parse(fs.readFileSync(path.join(root, 'data', 'creators', f), 'utf8'));
    return { id: c.id, name: c.name, aliases: c.aliases ?? [] };
  });

const req = JSON.parse(fs.readFileSync(0, 'utf8'));
const date = req.date ?? '2099-01-01';

const ops = {
  // Parse, change nothing, write back: what an untouched record should look like.
  roundtrip: ({ texts }) =>
    texts.map((text) => {
      const base = YAML.parse(text);
      return form.dumpYaml(form.buildCreator({ draft: form.draftFromCreator(base), base }));
    }),
  build: ({ cases }) =>
    cases.map(({ draft, base = null, creators = [] }) => {
      const problems = form.check({ draft, base, creators, validate });
      const rec = form.buildCreator({ draft, base });
      return { yaml: form.dumpYaml(rec), problems };
    }),
  packRoundtrip: ({ texts }) => {
    const creators = storedCreators();
    return texts.map((text) => {
      const base = YAML.parse(text);
      return pack.dumpYaml(pack.buildPack({ draft: pack.draftFromPack(base, creators), base, creators, date }));
    });
  },
  packBuild: ({ cases }) => {
    const stored = storedCreators();
    return cases.map(({ draft, base = null, creators = stored }) => {
      const problems = pack.check({ draft, base, creators, validate: validatePack, date });
      return { yaml: pack.dumpYaml(pack.buildPack({ draft, base, creators, date })), problems };
    });
  },
  packDraft: ({ text }) => pack.draftFromPack(YAML.parse(text), storedCreators()),
  newKey: ({ cases }) => cases.map(({ serials, lead, existing }) => pack.newKey(serials, lead, existing)),
  similar: ({ serials, packs, exceptKey }) => pack.similarPacks(serials, packs, exceptKey),
  serials: ({ texts }) => texts.map((s) => vocab.parseSerials(s)),
  youtube: ({ inputs }) => inputs.map((s) => vocab.parseYoutubeId(s)),
  sourceKind: ({ urls }) => urls.map((u) => vocab.detectSourceKind(u)),
  vocabularies: () => ({
    type: Object.keys(vocab.TYPE_LABELS), completeness: Object.keys(vocab.COMPLETENESS_LABELS), cost: Object.keys(vocab.COST_LABELS),
    role: Object.keys(vocab.ROLE_LABELS), source: Object.keys(vocab.SOURCE_KIND_LABELS),
  }),
  // What a form files for a draft: the issue body the workflow will read, and the preview the page shows.
  submit: ({ kind, draft, base = null }) => {
    const creators = storedCreators();
    let sub, preview;
    if (kind === 'creator') {
      const set = form.submissionSet({ draft, base });
      sub = submission.makeSubmission({ kind, op: base ? 'update' : 'create', id: draft.id, set });
      preview = form.dumpYaml(form.buildCreator({ draft, base }));
    } else {
      const set = pack.submissionSet({ draft, creators, base });
      sub = submission.makeSubmission({ kind, op: base ? 'update' : 'create', id: draft.key, set, creating: base ? null : pack.newFields(draft) });
      preview = pack.dumpYaml(pack.buildPack({ draft, base, creators, date }));
    }
    const body = `### Submission\n\n\`\`\`json\n${JSON.stringify(sub)}\n\`\`\`\n\n### Who is submitting\n\nSomeone\n`;
    return { sub, body, preview, url: submission.issueUrl(sub), title: submission.titleFor(sub) };
  },
  packFileUrl: ({ key, text }) => pack.newFileUrl(key, text),
  slug: ({ names }) => names.map((n) => form.slugify(n)),
  nameKey: ({ names }) => names.map((n) => form.nameKey(n)),
  newId: ({ cases }) => cases.map(({ name, existing }) => form.newId(name, existing)),
  normalize: ({ inputs }) => inputs.map((s) => form.normalizeUrl(s)),
  detect: ({ urls }) => urls.map((u) => kinds.detectKind(u)),
  newFileUrl: ({ id, text }) => form.newFileUrl(id, text),
  kinds: () => ({ tip: kinds.TIP_KINDS, social: kinds.SOCIAL_KINDS, labels: Object.keys(kinds.KIND_LABELS) }),
};

process.stdout.write(JSON.stringify(ops[req.op](req)));
