---
title: Schema reference
description: Every file type under data/, its fields, and who may edit it.
---

The source of truth is the JSON Schema files in `schema/`. `ps2ktxpak validate` checks every file
against them, then checks the files against each other. This page explains them in plain terms.

## Creator: `data/creators/<id>.yaml` (people edit)

| Field | Meaning |
|---|---|
| `id` | Immutable handle; equals the file name. |
| `name` | Display name, spelled as the creator spells it. |
| `aliases` | Other spellings and former names, used to match listings and credits. |
| `links.page` | The page the app opens for them, usually a forum profile. |
| `links.distribution` | A page the creator asked to be linked instead of a mirror. |
| `links.tip`, `links.socials` | Lists of `{kind, url}`. |
| `avatar` | `source_url` (where found) and `storage_key` (the stored copy). The image is never in git. |
| `identity` | `claimed_by` (public GitHub username) and how it was verified. No contact details. |
| `status` | `active` or `withdrawn`. |
| `provenance` | For each field: where it came from, when, and how sure. |
| `locked` | Fields a person set. Importers never overwrite them. |

## Pack: `data/packs/<key>.yaml` (people edit)

| Field | Meaning |
|---|---|
| `key` | Immutable file name: lowest serial, then lead creator, e.g. `slus-21410-ckiscxrsed`. Short, so paths work on Windows. |
| `catalog_id` | The id installed apps know, for the 517 inherited packs. Never changed. Absent for new packs. |
| `name`, `description` | What the pack is called and says about itself. |
| `game` | `title` and `serials`; the app matches packs to games by serial. |
| `credits` | Creators, lead first, each with a role. **Empty means no one has named the creator.** |
| `type`, `completeness` | `ai_upscale`, `handcrafted`, `mixed`, `port`, `button_replacement`; `complete`, `in_progress`, `incomplete`, `partial`. |
| `sources` | Pages about the pack (forum thread, creator page, repository, mirror). Never the address of the stored copy. |
| `media` | Example pictures and YouTube videos for the pack's page. A picture has the address where its creator shows it, the resized stored copy once made, a caption and a credit; a video is a YouTube id. Image files are never in git. |
| `access` | Optional override of what the pack costs the public; normally read from the matched listing. |
| `permission` | Right to host: `creator_uploaded`, `creator_approved`, `community_mirror`, `unknown`, `revoked`, with evidence. |
| `hosting.state` | `draft`, `review`, `published`, `withheld`, `withdrawn`, `disputed`. |
| `needs_review` | Credit questions an importer could not settle. A person removes an entry once checked. |
| `legacy` | The inherited catalog's text, kept for the record and for the byte-for-byte test. Not shown. |

## Archive: `data/archives/<key>.json` (machines write)

What the conversion produced for a pack, per revision: container, storage object name, `sha256`,
sizes, file count, the download it was converted from, and the converter and its settings. A new
revision is appended; an old one is never changed.

## Listing: `data/listings/sad-origami-ps2.jsonl` (importer writes)

One line per spreadsheet row. Carries title, regions, type, completeness, `access.cost` (derived from
the sheet's Restriction column: Paywall is `paid`, Ads is `free_with_ads`, otherwise `free`), the
creators, the row's page, and the sheet's own wording so the derivation can be checked.

## Match: `data/links/listing-pack.jsonl`

Which listing is the same work as which hosted pack, by what method (`thread`, `title`, `alias`,
`close_title`, `manual`) and how sure. A `manual` line is never overwritten.

## Resolution: `data/resolution/<hash>.json`

What following one source page found: candidate links with context, any YouTube videos (with the game
title they sit under, in a library thread) and their uploader's links, and a decision per listing. See [resolving sources](../resolving-sources/).

## Hand corrections: `data/overrides/hand-corrections.yaml`

Facts a person fixed by hand after an import, each with a reason and a date. Applied after every
import, and the fields are locked.
