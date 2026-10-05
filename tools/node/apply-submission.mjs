// Apply a submission issue to the data files. Run by .github/workflows/submission.yml, and by the tests.
//
//   node tools/node/apply-submission.mjs --body-file body.md --result-file result.json [--root <repo>] [--date YYYY-MM-DD]
//
// The issue body is untrusted. It is read from a file, parsed as JSON, checked against an allowlist and the
// schemas, and only then written, to a path built from an identifier that matched a strict pattern.
// Exit 0 and { ok: true, ... } in the result file when a file was written, exit 1 and { ok: false, errors } when not.
import fs from 'node:fs';
import { createRequire } from 'node:module';
import path from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';

const repo = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..', '..');
const arg = (name, fallback) => {
  const i = process.argv.indexOf(`--${name}`);
  return i > 0 ? process.argv[i + 1] : fallback;
};
const root = path.resolve(arg('root', repo));
const bodyFile = arg('body-file');
const resultFile = arg('result-file');
const date = arg('date', new Date().toISOString().slice(0, 10));
if (!bodyFile || !resultFile) {
  console.error('usage: apply-submission.mjs --body-file <file> --result-file <file> [--root <dir>] [--date <date>]');
  process.exit(2);
}

const site = createRequire(path.join(repo, 'site', 'package.json'));
const Ajv2020 = site('ajv/dist/2020').default;
const YAML = site('yaml');
const submission = await import(pathToFileURL(path.join(repo, 'site', 'src', 'lib', 'submission.mjs')).href);

const clean = (m) => String(m).replace(/\s+/g, ' ').slice(0, 300);
const finish = (result, code) => {
  fs.writeFileSync(resultFile, JSON.stringify(result));
  if (!result.ok) for (const e of result.errors) console.error(e);
  process.exit(code);
};

try {
  const stored = (dir) =>
    fs.existsSync(path.join(root, dir))
      ? fs.readdirSync(path.join(root, dir)).filter((f) => f.endsWith('.yaml')).map((f) => YAML.parse(fs.readFileSync(path.join(root, dir, f), 'utf8')))
      : [];
  const creators = stored('data/creators').map((c) => ({ id: c.id, name: c.name, aliases: c.aliases ?? [] }));

  const validators = Object.fromEntries(
    ['creator', 'pack'].map((kind) => {
      const schema = JSON.parse(fs.readFileSync(path.join(root, 'schema', `${kind}.schema.json`), 'utf8'));
      return [kind, new Ajv2020({ allErrors: true, strict: false }).compile(schema)];
    }),
  );
  const validate = (kind, rec) =>
    validators[kind](rec) ? [] : validators[kind].errors.map((e) => `${e.instancePath || 'record'} ${e.message}`);

  const read = (kind, id) => {
    const file = path.join(root, submission.pathFor(kind, id));
    return fs.existsSync(file) ? YAML.parse(fs.readFileSync(file, 'utf8')) : null;
  };

  const sub = submission.parseIssueBody(fs.readFileSync(bodyFile, 'utf8'));
  const out = submission.applySubmission(sub, { read, creators, validate, date });
  const target = path.join(root, out.path);
  fs.mkdirSync(path.dirname(target), { recursive: true });
  fs.writeFileSync(target, out.text);
  finish({ ok: true, kind: out.kind, op: out.op, id: out.id, path: out.path }, 0);
} catch (e) {
  finish({ ok: false, errors: (e.errors ?? [`Unexpected error: ${e.message}`]).map(clean) }, 1);
}
