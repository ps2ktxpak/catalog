#!/bin/sh
# Start one scraper shard. The Worker passes the settings and secrets as environment variables:
#   R2_ACCOUNT_ID, R2_ACCESS_KEY_ID, R2_SECRET_ACCESS_KEY   the bucket, through its S3 API
#   MEGA_USERNAME, MEGA_PASSWORD                           the Mega account downloads count against
#   MEDIAFIRE_EMAIL, MEDIAFIRE_PASSWORD                    the MediaFire account that gets direct links
#   SCRAPE_SHARD (i/n), SCRAPE_STORE, SCRAPE_MAX_SOURCE_GB
set -eu

# The pack files come from the public repository as it is now; the code is what this image was built with.
rm -rf /work/catalog
git clone --quiet --depth 1 https://github.com/ps2ktxpak/catalog /work/catalog
export PS2KTXPAK_ROOT=/work/catalog

if [ -n "${MEGA_USERNAME:-}" ]; then
	umask 077
	printf '[Login]\nUsername = %s\nPassword = %s\n' "$MEGA_USERNAME" "$MEGA_PASSWORD" > /run/megarc
	export MEGARC=/run/megarc
fi

export RCLONE_CONFIG_R2_TYPE=s3 RCLONE_CONFIG_R2_PROVIDER=Cloudflare RCLONE_CONFIG_R2_NO_CHECK_BUCKET=true
export RCLONE_CONFIG_R2_ACCESS_KEY_ID="$R2_ACCESS_KEY_ID" RCLONE_CONFIG_R2_SECRET_ACCESS_KEY="$R2_SECRET_ACCESS_KEY"
export RCLONE_CONFIG_R2_ENDPOINT="https://$R2_ACCOUNT_ID.r2.cloudflarestorage.com"
export SEVEN_ZIP=7zz SCRAPE_WORK=/work/packs PORT=8080

exec ps2ktxpak scrape job
