# ps2ktxpak

The data, tooling and site behind ARMSX2's PS2 texture pack browser: which packs exist, who made
them, where each is announced, what it costs, and whether we may host a copy.

> **Status: draft, local only.** Not pushed anywhere yet. The license for the data is undecided
> (it waits on agreement with Sad Origami, whose Texture Packs Archive this is built on).

## What is in here

| Path | What | Edited by |
|---|---|---|
| `data/creators/`, `data/packs/` | Creators and the packs we host | people |
| `data/archives/` | What the conversion pipeline produced (hashes, sizes) | machines |
| `data/listings/`, `data/links/`, `data/resolution/` | Spreadsheet listings, which are packs we host, where their pages lead | machines, with human corrections |
| `data/overrides/` | Hand corrections and title aliases, each with a reason | people |
| `schema/` | JSON Schema for every file type | people |
| `tools/ps2ktxpak/` | The command line: import, validate, report, compile, resolve | |
| `site/` | The documentation site (Astro Starlight) | people |

The pages in `site/src/content/docs/` (schema, policy, resolving sources) describe the model.

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

See *Resolving sources* on the site for the rules (public pages only, no downloads, nothing paid).

## Pictures and videos for the site

```sh
ps2ktxpak media-fetch                  # seed each hosted pack's pictures and YouTube ids from its own thread
```

It only records addresses, only for a thread that belongs to one hosted pack, and never touches a pack
that already has `media`. The pictures are mirrored to our storage later (resized, credited); they are
never committed.
