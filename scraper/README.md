# Scraper

Downloads the free packs listed in the Texture Packs Archive spreadsheet, keeps each download, and
converts it into the archive apps install. It runs as Cloudflare Containers driven by a Worker, and
writes only to a private R2 bucket. It never writes to this repository: a maintainer applies its
results here and commits them.

## What it does with each pack

The packs it takes are the `listed` ones with a resolved `download` link and no `archive`. A pack is
skipped when the creator charges for it: the pack's `access.cost` is `paid`, the spreadsheet's
Restriction column says Paywall, or the link is a shop checkout.

For each pack it takes:

1. It lists what the link holds. In a folder that holds a whole library, it keeps the file named for
   the pack's game.
2. It downloads the file and keeps it, byte for byte, under `sources/` in the bucket.
3. It converts the pack with the same tools and settings as the 517 inherited packs (kram, ASTC 6x6,
   `tar | zstd`).
4. It checks every texture with the app's own KTX parser, and the archive with the app's tar rules.
5. It stores the archive as `packs/<key>.tar.zst` in the same private bucket.

Each pack ends with one of these results, in `results/<key>.json`:

| Result | Meaning |
|---|---|
| `done` | converted and stored |
| `gone` | the host says the file was removed |
| `needs_choice` | the download holds several packs (sizes, variants, games) and a person picks one; the download is kept |
| `empty` | the download has no textures |
| `unsupported` | no downloader for that host or link shape |
| `too_large` | the download does not fit the container's disk with room to convert it |
| `paid` | skipped |
| `failed` | worth another try (quota, network); the next run retries it, up to three times |

A run skips every pack that already has a final result, so starting it again resumes it.

## Getting the results into the repository

```sh
ps2ktxpak scrape apply --shards 4     # fetches results/index-*.json with your wrangler login
git diff --stat data/packs            # look before committing
pytest && ps2ktxpak validate
```

`apply` writes only two kinds of change:

- **A converted pack** becomes `hosting.state: withheld` ("we have it and hold it back") and gets
  its `archive` block. If the pack named no serial, the serial folders found in the download are
  added too.
- **A gone link** gets `download.status: dead`.

`apply` leaves a pack alone if someone has changed it since the run (it is no longer `listed`, or it
already has an archive). It prints everything it did not write: the packs needing a choice, the
failures, and the spreadsheet rows that no pack describes.

Hosting a withheld pack is a separate decision, made per pack:

1. Copy `packs/<key>.tar.zst` from the scraper's bucket to `armsx2-textures`, the public bucket behind
   `dl.ps2ktxpak.net`, and to its Backblaze copy.
2. Set the pack to `published`, with the permission it has.

## Setting it up

Once:

```sh
npx wrangler r2 bucket create ps2ktxpak-scrape     # private: no public domain, no r2.dev
```

Then:

1. In the Cloudflare dashboard (R2, Manage API tokens), make an "Object Read & Write" token for the
   `ps2ktxpak-scrape` bucket only.
2. Set the secrets. Each command prompts for the value, so nothing lands in your shell history:
   ```sh
   cd scraper && npm ci
   for s in R2_ACCOUNT_ID R2_ACCESS_KEY_ID R2_SECRET_ACCESS_KEY MEGA_USERNAME MEGA_PASSWORD RUN_TOKEN; do
     npx wrangler secret put $s
   done
   ```
   `RUN_TOKEN` is any long random string; it guards `/run` and `/stop`. The Mega account is the one
   downloads count against.

## Deploying

The image is built for x86-64 by `.github/workflows/scraper-image.yml` on every push that changes
it, and kept as that run's `scraper-image` artifact. `deploy.sh` waits for the build of the current
commit, pushes the image to Cloudflare's registry, stops the shards, deploys the Worker pointing at
it and starts the run again (its header lists the settings it needs). Commit the `wrangler.jsonc`
it changes.

Deploy only when stopping is acceptable: the packs in progress start over.

On an x86-64 machine with Docker, `"image": "./Dockerfile"` with `"image_build_context": ".."`
and a plain `wrangler deploy` build it locally instead.

## Resuming

Every pack's result is written to the bucket as soon as it ends, and every download is kept there.
A shard that starts again (after `/stop`, a deploy, or Cloudflare restarting its container) skips
what has a final result, retries a failure up to three times in all, and takes a download it
already has from the bucket instead of the host. A pack converted under an older `convert.PARAMS`
is redone without encoding again: its files the emulator never loads are taken out of the finished
pack.

## Running

```sh
curl -X POST -H "Authorization: Bearer $RUN_TOKEN" https://ps2ktxpak-scraper.<subdomain>.workers.dev/run
curl https://ps2ktxpak-scraper.<subdomain>.workers.dev/status
curl -X POST -H "Authorization: Bearer $RUN_TOKEN" https://ps2ktxpak-scraper.<subdomain>.workers.dev/stop
```

- **What `/run` starts.** It starts `SHARDS` containers (`wrangler.jsonc`). Each takes every n-th
  download link, so packs that share one link land in the same shard.
- **The cron.** Every ten minutes it asks each shard for its status. That keeps the shard awake,
  restarts one that stopped before finishing, and stops one that has finished.
- **What a shard reads at start.** It clones this repository fresh, so it works from the pack files as
  they are on `main`. The code it runs is whatever the image was built with.

To try the job on one machine, point `--store` at a directory:

```sh
KRAM=... VALIDATE_KTX=... SEVEN_ZIP=7zz MEGARC=~/.config/ps2ktxpak/megarc \
  ps2ktxpak scrape job --store /tmp/store --work /tmp/work --only <pack key> ...
```
