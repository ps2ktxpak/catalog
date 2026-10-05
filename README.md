# ps2ktxpak

The data, tooling and site behind ARMSX2's PS2 texture pack browser: which packs exist, who made
them, where each is announced, what it costs, and whether we may host a copy.

The site is published at <https://ps2ktxpak.github.io/catalog/> from `main`.

## What is in here

| Path | What | Edited by |
|---|---|---|
| `data/creators/`, `data/packs/` | Creators and the packs we host | people |
| `data/archives/` | What the conversion pipeline produced (hashes, sizes) | machines |
| `data/listings/`, `data/links/`, `data/resolution/` | Spreadsheet listings, which are packs we host, where their pages lead | machines, with human corrections |
| `data/overrides/` | Hand corrections and title aliases, each with a reason | people |
| `schema/` | JSON Schema for every file type; the creator form validates against it too | people |
| `tools/ps2ktxpak/` | The command line: import, validate, report, compile, resolve | |
| `site/` | The published pack list and creator pages (Astro Starlight) | people |
| `docs/` | How the model, hosting policy and source resolution work; the roadmap | people |

`docs/` (schema, policy, resolving sources, roadmap) describes the model.

## Without git

`/creators/edit/` and `/packs/edit/` on the site are forms that add or change a creator or a pack
(`?id=` or `?key=` to edit one; each creator and hosted pack in the lists has an Edit button). Submitting
opens a GitHub issue with the change filled in; `.github/workflows/submission.yml` applies it to the data
files, checks it, and opens a pull request that credits the submitter. Nobody needs git, a fork or write
access. Fields set through a form are locked and carry `web-form` provenance. A new pack starts hosted (see
`docs/policy.md`). How a submission is read and what it may change: `docs/submissions.md`.

The logic is in `site/src/lib/` (`creator-form.mjs`, `pack-form.mjs`, `submission.mjs`, shared by the page and
the workflow) and `tools/node/apply-submission.mjs`; `tests/test_creator_form.py`, `test_pack_form.py` and
`test_submission.py` run it against the real data and schemas.

The repository needs the setting *Allow GitHub Actions to create and approve pull requests*
(Settings, Actions, General) for the workflow to open pull requests.

## Setup

Python 3.11+ and Node 22.12+.

```sh
python -m venv .venv && . .venv/bin/activate
pip install -e '.[dev,resolve]'        # pyyaml, jsonschema, pytest, yt-dlp
cd site && npm install && cd ..
```

## Everyday commands

```sh
ps2ktxpak validate                     # schemas, cross-references, hosting policy
ps2ktxpak report summary               # counts; also: paid-hosted, unmatched, credits
ps2ktxpak compile catalog              # dist/textures.json (what the app downloads)
ps2ktxpak compile links                # dist/texture-pack-links.json (compatibility overlay)
pytest                                 # includes a byte-for-byte rebuild of the live catalog
cd site && npm run dev                 # the site: the pack list is the home page, with a page per creator
```

The pack list and creator pages are built from `data/` when the site builds (`npm run build`, output in
`site/dist`). The site-wide search box needs Pagefind, which crashes on Linux systems with 16 KB memory
pages (Asahi): build on x86 or in CI to get it. The pack list has its own search and works regardless.

Without installing, run `PYTHONPATH=tools python -m ps2ktxpak <command>`.

## Seeding from scratch

```sh
ps2ktxpak import-sheet                 # downloads the live spreadsheet, writes listings and creators
ps2ktxpak import-legacy                # one-time: packs and archives from the live catalog
ps2ktxpak link-listings                # which listing is which hosted pack
ps2ktxpak validate
```

`import-legacy` is a seed: it never touches a pack file that already exists, so human edits survive.

## Finding the real downloads

```sh
ps2ktxpak resolve-plan                 # which source pages are in scope
ps2ktxpak resolve-fetch                # polite deterministic pass; caches pages under cache/
ps2ktxpak resolve-brief NAME --url ... # evidence file for an agent to judge
ps2ktxpak resolve-apply decisions.json # merge the agent's decisions
```

See `docs/resolving-sources.md` for the rules (public pages only, no downloads, nothing paid).

## Pictures and videos for the site

```sh
ps2ktxpak media-fetch                  # seed each hosted pack's pictures and YouTube ids from its own thread
```

It only records addresses, only for a thread that belongs to one hosted pack, and never touches a pack
that already has `media`. The pictures are mirrored to our storage later (resized, credited); they are
never committed.

## License

MIT (`LICENSE`), data included. Texture pack files, pictures and names belong to their creators and are
not covered by it.
