# ps2ktxpak: conventions

This repo is **public**. Write every file as if a creator, a forum moderator and a lawyer will
read it, because they may.

## Never put in this tree

- Email addresses, private messages, quotations from private conversations, takedown notices'
  contents, or anything about a person that they have not published themselves.
- Credentials of any kind. Publishing keys belong in CI secrets.
- Images or other binaries (avatars, previews, archives). Git history is permanent; keep a
  `storage_key` and put the file in storage.
- Sad Origami's free-mirror links or his Blacklist tab. They are his hosting and his judgement.
- Anything copied from a private repository or private notes.

## Who owns which file

- **People edit:** `data/creators/`, `data/packs/`, `schema/`, `site/`.
- **The conversion pipeline writes** the `archive` block of a pack file. Do not hand-edit it.
- **Everything else is edited directly.** There is one YAML file per pack and nothing else describes a pack: no
  separate listing, match, archive or resolution files. Nothing regenerates the data, so a hand edit is never undone.
- `ps2ktxpak compile catalog` rolls the hosted packs (`published`, with an `archive`) up into the one file apps
  download. A pack that is not hosted never reaches an app.
- The creator and pack forms on the site (`/creators/edit/`, `/packs/edit/`) file a GitHub issue; `.github/workflows/submission.yml`
  applies it and opens a pull request. Their output must keep
  round-tripping the files byte for byte (`tests/test_creator_form.py`). The issue body is untrusted input: the workflow
  must never put it inside a command (`tests/test_submission.py` checks), and `submission.mjs` is an allowlist.
- A new pack from the pack form starts `published` with `permission: creator_approved`
  on the submitter's statement, so a merged pull request is what approves hosting: check the claim before merging.
- Commit messages and pull request text are public: state the fact, never quote a conversation.

## Rules the data keeps

- Ids are immutable. A creator's `id` and a pack's `key` equal their file names and never change. A
  pack's `catalog_id` (inherited, up to 228 characters) is what installed apps know; never change it.
- Never delete a pack. Mark it `withdrawn`. (`listed` packs are known-to-exist records; they are withdrawn the same way.)
- **Never host a paid pack** without the creator's approval written into `permission`. Cost and
  permission are different questions.
- `credits: []` means "no one has named the creator". Never fill it with a guess; use
  `needs_review` for a credit nobody has checked.
- Archive facts (hash, sizes, revision) are written by the conversion pipeline only.
- Old app builds read `textures.json`: keep its shape, never leave `authors` empty, never bump its
  `schemaVersion` for an additive change.

## Before you finish a change

```sh
pytest
ps2ktxpak validate
```

`ps2ktxpak compile catalog` builds the file installed apps download from these files, so a change that
alters what it emits is a change to every installed app: check the diff of `dist/textures.json`.

## Commits

Single-purpose commits that pass the checks above.
