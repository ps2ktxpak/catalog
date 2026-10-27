#!/bin/sh
# Deploy the image the scraper-image workflow built from the current commit of main, and restart the run.
#   SCRAPER_URL   the Worker's URL
#   RUN_TOKEN     the Worker's RUN_TOKEN secret
#   CLOUDFLARE_ACCOUNT_ID, and a `wrangler login`
# Packs in progress are lost and start over; finished ones are kept (README.md, "Resuming").
set -eu
cd "$(dirname "$0")"
: "${SCRAPER_URL:?}" "${RUN_TOKEN:?}" "${CLOUDFLARE_ACCOUNT_ID:?}"

full=$(git rev-parse HEAD)
tag=$(git rev-parse --short=7 HEAD)
run=$(gh run list -w "scraper image" -c "$full" -L 1 --json databaseId -q '.[0].databaseId')
[ -n "$run" ] || { echo "no scraper-image build for $tag" >&2; exit 1; }
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
