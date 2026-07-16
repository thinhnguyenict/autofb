#!/usr/bin/env bash
set -euo pipefail

: "${FB_APP_ID:?Set FB_APP_ID in the environment}"
: "${FB_APP_SECRET:?Set FB_APP_SECRET in the environment}"
: "${FB_SHORT_LIVED_TOKEN:?Set FB_SHORT_LIVED_TOKEN in the environment}"

curl --fail-with-body --get "https://graph.facebook.com/v25.0/oauth/access_token" \
  --data-urlencode "grant_type=fb_exchange_token" \
  --data-urlencode "client_id=${FB_APP_ID}" \
  --data-urlencode "client_secret=${FB_APP_SECRET}" \
  --data-urlencode "fb_exchange_token=${FB_SHORT_LIVED_TOKEN}"
