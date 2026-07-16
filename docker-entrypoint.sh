#!/bin/sh
set -eu

cd /app

if [ "${AUTOFB_SERVICE:-dashboard}" = "api" ]; then
  exec uvicorn autofb.web.api:app --host 0.0.0.0 --port "${PORT:-8000}"
fi

if [ ! -f config.json ] && [ -f config.json.example ]; then
  cp config.json.example config.json
fi

mkdir -p output

exec php -S "0.0.0.0:${PORT:-8000}" -t web
