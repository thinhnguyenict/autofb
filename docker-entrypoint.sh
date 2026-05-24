#!/bin/sh
set -eu

cd /app

if [ ! -f config.json ] && [ -f config.json.example ]; then
  cp config.json.example config.json
fi

mkdir -p output

exec php -S "0.0.0.0:${PORT:-8000}" -t web
