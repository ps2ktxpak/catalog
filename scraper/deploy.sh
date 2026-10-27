#!/bin/sh
# Deploy the image the scraper-image workflow built from main, and restart the run.
#   SCRAPER_URL   the Worker's URL
#   RUN_TOKEN     the Worker's RUN_TOKEN secret
#   CLOUDFLARE_ACCOUNT_ID, and a `wrangler login`
# Packs in progress are lost and start over; finished ones are kept (README.md, "Resuming").
set -eu
cd "$(dirname "$0")"
: "${SCRAPER_URL:?}" "${RUN_TOKEN:?}" "${CLOUDFLARE_ACCOUNT_ID:?}"

# The newest build on main, named for the push's head commit. A push of data only builds nothing, so
# check that the build holds the newest commit that changed the image (the workflow's paths).
changed=$(git log -1 --format=%H -- Dockerfile entry.sh validate_ktx.cpp ../tools ../pyproject.toml)
set -- $(gh run list -w "scraper image" -b main -L 1 --json databaseId,headSha -q '.[0] | "\(.databaseId) \(.headSha)"')
run=${1:-} full=${2:-}
[ -n "$run" ] && git merge-base --is-ancestor "$changed" "$full" ||
	{ echo "no scraper-image build holds $(git rev-parse --short=7 "$changed") yet" >&2; exit 1; }
tag=$(git rev-parse --short=7 "$full")
gh run watch "$run" --exit-status > /dev/null

dir=$(mktemp -d)
trap 'rm -rf "$dir"' EXIT
gh run download "$run" -n scraper-image -D "$dir"
podman load -i "$dir/scraper-image.tar" > /dev/null
podman tag "docker.io/library/ps2ktxpak-scraper:$full" "ps2ktxpak-scraper:$tag"
npx wrangler containers push --path-to-docker podman "ps2ktxpak-scraper:$tag"

post() { curl -sS -m 300 -X POST -H "Authorization: Bearer $RUN_TOKEN" "$SCRAPER_URL/$1"; echo; }
post stop  # kills the containers; a running shard would otherwise keep the old image

sed -i "s|registry.cloudflare.com/ps2ktxpak-scraper:[0-9a-f]*|registry.cloudflare.com/ps2ktxpak-scraper:$tag|" wrangler.jsonc
npx wrangler deploy --containers-rollout=immediate
# A run started before the rollout finishes gets the old image.
app=$(npx wrangler containers list 2>/dev/null | awk -F'│' '/ps2ktxpak-scraper-scraper/ {gsub(/ /, "", $2); print $2}')
until npx wrangler containers info "$app" 2>/dev/null | grep -q "\"image\": \".*:$tag\""; do sleep 15; done
until npx wrangler containers list 2>/dev/null | grep -q "ps2ktxpak-scraper-scraper │ ready"; do sleep 15; done
post run
echo "deployed $tag; commit scraper/wrangler.jsonc"
