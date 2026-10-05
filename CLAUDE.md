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

- **People edit:** `data/creators/`, `data/packs/`, `data/overrides/`, `schema/`, `site/`.
- **Machines write:** `data/archives/`, `data/listings/`, `data/resolution/`, and `data/links/` apart
  from `method: manual` lines. Do not hand-edit them; change the tool or the input.
- The creator form on the site (`/creators/edit/`) writes creator files with `web-form` provenance and locks the
  fields it sets; its output must keep round-tripping the files byte for byte (`tests/test_creator_form.py`).
- A human edit to a creator or pack field goes through `data/overrides/hand-corrections.yaml` or is
  added to that file's `locked` list, so the next import cannot undo it. Reasons are public: state the
  fact, never quote a conversation.

## Rules the data keeps

- Ids are immutable. A creator's `id` and a pack's `key` equal their file names and never change. A
  pack's `catalog_id` (inherited, up to 228 characters) is what installed apps know; never change it.
- Never delete a pack. Mark it `withdrawn`.
- **Never host a paid pack** without the creator's approval written into `permission`. Cost and
  permission are different questions.
- `credits: []` means "no one has named the creator". Never fill it with a guess; use
  `needs_review` for a credit an importer could not settle.
- Archive facts (hash, sizes, revision) are written by the conversion pipeline only.
- Old app builds read `textures.json`: keep its shape, never leave `authors` empty, never bump its
  `schemaVersion` for an additive change.

## Before you finish a change

```sh
pytest                    # includes a byte-for-byte rebuild of the live catalog (needs cache/live)
ps2ktxpak validate
```

`ps2ktxpak compile catalog --mode faithful` must keep reproducing the published catalog exactly. If
that test fails, the data model lost something: find out what before changing the test.

## Web access

Pages are requested politely (about one request per 1.5 seconds per host), public pages only, with a
user agent that names this project. No logins, no downloads of pack files, nothing behind a paywall.
Cached under `cache/`, which is gitignored.

## Commits

Single-purpose commits that pass the checks above.
