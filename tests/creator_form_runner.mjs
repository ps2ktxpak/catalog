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
const kinds = await lib('kinds.mjs');

const schema = JSON.parse(fs.readFileSync(path.join(root, 'schema', 'creator.schema.json'), 'utf8'));
const validate = new Ajv2020({ allErrors: true, strict: false }).compile(schema);

const req = JSON.parse(fs.readFileSync(0, 'utf8'));
const date = req.date ?? '2099-01-01';

const ops = {
  // Parse, change nothing, write back: what an untouched record should look like.
  roundtrip: ({ texts }) =>
    texts.map((text) => {
      const base = YAML.parse(text);
      return form.dumpYaml(form.buildCreator({ draft: form.draftFromCreator(base), base, date }));
    }),
  build: ({ cases }) =>
    cases.map(({ draft, base = null, creators = [] }) => {
      const problems = form.check({ draft, base, creators, validate, date });
      const rec = form.buildCreator({ draft, base, date });
      return { yaml: form.dumpYaml(rec), problems };
    }),
  slug: ({ names }) => names.map((n) => form.slugify(n)),
  nameKey: ({ names }) => names.map((n) => form.nameKey(n)),
  newId: ({ cases }) => cases.map(({ name, existing }) => form.newId(name, existing)),
  normalize: ({ inputs }) => inputs.map((s) => form.normalizeUrl(s)),
  detect: ({ urls }) => urls.map((u) => kinds.detectKind(u)),
  newFileUrl: ({ id, text }) => form.newFileUrl(id, text),
  kinds: () => ({ tip: kinds.TIP_KINDS, social: kinds.SOCIAL_KINDS, labels: Object.keys(kinds.KIND_LABELS) }),
};

process.stdout.write(JSON.stringify(ops[req.op](req)));
