#!/usr/bin/env bash
set -Eeuo pipefail

DOMAIN="${DOMAIN:-tool.huongdancauca.com}"
APP_DIR="${APP_DIR:-/www/wwwroot/tool.huongdancauca.com}"
REPO_URL="${REPO_URL:-}"
INSTALL_AAPANEL="${INSTALL_AAPANEL:-0}"
DRY_RUN="${DRY_RUN:-0}"
PYTHON_BIN="${PYTHON_BIN:-python3}"

log() { printf '\n[autofb] %s\n' "$*"; }
run() {
  printf '+ %q' "$@"
  printf '\n'
  if [ "$DRY_RUN" != "1" ]; then
    "$@"
  fi
}
require_root() {
  if [ "${EUID:-$(id -u)}" -ne 0 ]; then
    echo "Please run as root: sudo -i, then run this script again." >&2
    exit 1
  fi
}
generate_fernet_key() {
  "$PYTHON_BIN" - <<'PY'
import base64, os
print(base64.urlsafe_b64encode(os.urandom(32)).decode())
PY
}
install_aapanel_if_requested() {
  if [ "$INSTALL_AAPANEL" != "1" ]; then
    return
  fi
  if command -v bt >/dev/null 2>&1; then
    log "aaPanel already appears to be installed. Skipping."
    return
  fi
  log "Installing aaPanel. You can skip this next time with INSTALL_AAPANEL=0."
  run bash -c 'URL=https://www.aapanel.com/script/install_7.0_en.sh; if command -v curl >/dev/null 2>&1; then curl -ksSO "$URL"; else wget --no-check-certificate -O install_7.0_en.sh "$URL"; fi; bash install_7.0_en.sh aapanel'
}
install_system_packages() {
  log "Installing system packages and Docker Compose plugin"
  run apt-get update
  run apt-get install -y ca-certificates curl git make ufw docker.io docker-compose-plugin
  run systemctl enable --now docker
}
open_firewall_ports() {
  log "Opening HTTP/HTTPS/SSH firewall ports"
  run ufw allow OpenSSH
  run ufw allow 80/tcp
  run ufw allow 443/tcp
  if [ "$INSTALL_AAPANEL" = "1" ]; then
    run ufw allow 7800/tcp
  fi
}
checkout_or_update_repo() {
  log "Preparing application directory: $APP_DIR"
  run mkdir -p "$(dirname "$APP_DIR")"
  if [ -d "$APP_DIR/.git" ]; then
    run git -C "$APP_DIR" pull --ff-only
    return
  fi
  if [ -n "$REPO_URL" ]; then
    run git clone "$REPO_URL" "$APP_DIR"
    return
  fi
  if [ -f "docker-compose.yml" ] && [ -f "Dockerfile" ]; then
    log "No REPO_URL provided; copying current directory into $APP_DIR"
    run mkdir -p "$APP_DIR"
    run rsync -a --delete --exclude .git ./ "$APP_DIR/"
    return
  fi
  cat >&2 <<MSG
REPO_URL is required when the script is not run from an AutoFB checkout.
Example one-liner:
  REPO_URL=https://github.com/YOUR_ORG/YOUR_REPO.git bash <(curl -fsSL https://raw.githubusercontent.com/YOUR_ORG/YOUR_REPO/main/deploy/aapanel_ubuntu_24_04.sh)
MSG
  exit 1
}
write_runtime_files() {
  log "Writing .env, config.json and docker-compose.override.yml"
  cd "$APP_DIR"
  if [ ! -f config.json ] && [ -f config.json.example ]; then
    run cp config.json.example config.json
  fi

  local fernet_key
  fernet_key="${AUTOFB_TOKEN_ENCRYPTION_KEY:-$(generate_fernet_key)}"
  if [ ! -f .env ]; then
    cat > .env <<ENV
DOMAIN=$DOMAIN
META_APP_ID=${META_APP_ID:-}
META_APP_SECRET=${META_APP_SECRET:-}
META_REDIRECT_URI=${META_REDIRECT_URI:-https://$DOMAIN/api/v1/oauth/facebook/callback}
AUTOFB_TOKEN_ENCRYPTION_KEY=$fernet_key
AUTOFB_IMAGE_UPLOAD_URL=${AUTOFB_IMAGE_UPLOAD_URL:-}
AUTOFB_IMAGE_UPLOAD_TOKEN=${AUTOFB_IMAGE_UPLOAD_TOKEN:-}
IMGBB_API_KEY=${IMGBB_API_KEY:-}
ENV
    chmod 600 .env
  fi

  cat > docker-compose.override.yml <<'YAML'
services:
  autofb-api:
    ports:
      - "127.0.0.1:8001:8001"
    environment:
      META_APP_ID: "${META_APP_ID}"
      META_APP_SECRET: "${META_APP_SECRET}"
      META_REDIRECT_URI: "${META_REDIRECT_URI}"
      AUTOFB_TOKEN_ENCRYPTION_KEY: "${AUTOFB_TOKEN_ENCRYPTION_KEY}"
      AUTOFB_IMAGE_UPLOAD_URL: "${AUTOFB_IMAGE_UPLOAD_URL}"
      AUTOFB_IMAGE_UPLOAD_TOKEN: "${AUTOFB_IMAGE_UPLOAD_TOKEN}"
      IMGBB_API_KEY: "${IMGBB_API_KEY}"
  autofb-worker:
    environment:
      META_APP_ID: "${META_APP_ID}"
      META_APP_SECRET: "${META_APP_SECRET}"
      META_REDIRECT_URI: "${META_REDIRECT_URI}"
      AUTOFB_TOKEN_ENCRYPTION_KEY: "${AUTOFB_TOKEN_ENCRYPTION_KEY}"
      AUTOFB_IMAGE_UPLOAD_URL: "${AUTOFB_IMAGE_UPLOAD_URL}"
      AUTOFB_IMAGE_UPLOAD_TOKEN: "${AUTOFB_IMAGE_UPLOAD_TOKEN}"
      IMGBB_API_KEY: "${IMGBB_API_KEY}"
  autofb:
    ports:
      - "127.0.0.1:8000:8000"
YAML
}
build_and_start() {
  log "Building and starting AutoFB API + worker"
  cd "$APP_DIR"
  run docker compose up -d --build autofb-api autofb-worker
}
wait_for_health() {
  if [ "$DRY_RUN" = "1" ]; then
    return
  fi
  log "Waiting for API health check"
  for _ in $(seq 1 30); do
    if curl -fsS http://127.0.0.1:8001/healthz >/dev/null 2>&1; then
      log "API is healthy"
      return
    fi
    sleep 2
  done
  echo "API did not become healthy. Check: docker compose logs --tail=200 autofb-api" >&2
  exit 1
}
print_next_steps() {
  cat <<MSG

AutoFB deploy script finished.

Domain: https://$DOMAIN
App dir: $APP_DIR
Local API: http://127.0.0.1:8001

In aaPanel, create/reuse website $DOMAIN and add Reverse Proxy:
  Target URL: http://127.0.0.1:8001
Then enable Let's Encrypt SSL and Force HTTPS.

Meta OAuth redirect URI:
  https://$DOMAIN/api/v1/oauth/facebook/callback

Useful commands:
  cd $APP_DIR
  docker compose ps
  docker compose logs -f autofb-api
  docker compose logs -f autofb-worker
  docker compose up -d --build
  make check

If Meta OAuth is not configured yet, edit:
  $APP_DIR/.env
then restart:
  cd $APP_DIR && docker compose up -d --build
MSG
}
main() {
  require_root
  install_system_packages
  open_firewall_ports
  install_aapanel_if_requested
  checkout_or_update_repo
  write_runtime_files
  build_and_start
  wait_for_health
  print_next_steps
}
main "$@"
