# Schema reference

Every file type under data/, its fields, and who may edit it.

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

## Pack: `data/packs/<key>.yaml` (people edit; the pipeline writes `archive`)

One file per pack, and the only file a pack has. A hosted pack, a pack that is held back, and a pack that
is only known to exist are all the same kind of file; `hosting.state` says which.

| Field | Meaning |
|---|---|
| `key` | Immutable file name: lowest serial, then lead creator, e.g. `slus-21410-ckiscxrsed`; for a pack with no serial yet, its game title then the lead creator. Short, so paths work on Windows. |
| `catalog_id` | The id installed apps know, for the 517 inherited packs. Never changed. Absent for newer packs. |
| `name`, `description`, `version` | What the pack is called, what it says about itself, and the version its creator gives it. |
| `game` | `title`, `serials` (the app matches packs to games by serial) and, for a pack with no serial yet, `regions`. |
| `credits` | Creators, lead first, each with a role. **Empty means no one has named the creator.** |
| `listed_credits` | Creators the Texture Packs Archive names when `credits` does not. Shown beside the pack and on their pages; not used for the catalog. |
| `type`, `completeness` | `ai_upscale`, `handcrafted`, `mixed`, `port`, `button_replacement`; `complete`, `in_progress`, `incomplete`, `partial`. |
| `sources` | Pages about the pack (forum thread, creator page, repository, mirror). Never the address of the stored copy. |
| `media` | Example pictures and YouTube videos for the pack's page. A picture has the address where its creator shows it, the resized stored copy once made, a caption and a credit; a video is a YouTube id. Image files are never in git. |
| `access` | What the pack costs the public where its creator distributes it: `free`, `free_with_ads`, `paid`; absent when not known. |
| `permission` | Right to host: `creator_uploaded`, `creator_approved`, `community_mirror`, `unknown`, `revoked`, with evidence. Absent for a pack nobody asked about. |
| `hosting.state` | `published` (hosted), `listed` (known to exist, not hosted), `withheld` (we have it and hold it back), `draft`, `review`, `withdrawn`, `disputed`. A `published` pack needs a game serial. One with no `archive` is accepted for hosting and awaiting conversion: validation warns, and it stays out of the catalog until the pipeline has written its archive. |
| `needs_review` | Credits nobody has checked yet. A person removes an entry once checked. |
| `download` | For a pack that is not hosted: where its files were found by following its source page (`status`, `url`, `host`, `kind`, `confidence`, `note`). An address is recorded only when it was seen on a public page. |
| `archive` | What the conversion pipeline produced: the current revision and, per revision, the storage object, `sha256`, sizes, file count, the download it was converted from, and the converter and its settings. A new revision is appended; an old one is never changed. Never edited by hand. |

## The rollup: `ps2ktxpak compile`

`compile catalog` takes the packs that are `published` and have an `archive`, and writes them into one file,
`textures.json`, which is hosted for the apps. Names come from `credits`, the source link from the primary
source, the licence text from `permission`, and the hashes and sizes from `archive`. `compile links` writes the
overlay file older builds read. Nothing else in the pack files reaches an app.
