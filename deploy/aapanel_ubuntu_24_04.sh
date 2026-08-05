#!/usr/bin/env bash
set -Eeuo pipefail

DOMAIN="${DOMAIN:-tool.huongdancauca.com}"
APP_DIR="${APP_DIR:-/www/wwwroot/tool.huongdancauca.com}"
REPO_URL="${REPO_URL:-}"
INSTALL_AAPANEL="${INSTALL_AAPANEL:-0}"
DRY_RUN="${DRY_RUN:-0}"
PYTHON_BIN="${PYTHON_BIN:-python3}"
AUTOFB_API_PORT_WAS_SET="${AUTOFB_API_PORT+x}"
AUTOFB_API_PORT="${AUTOFB_API_PORT:-8001}"

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
port_in_use() {
  local port="$1"
  if command -v ss >/dev/null 2>&1; then
    ss -ltn "sport = :$port" | awk 'NR > 1 { found=1 } END { exit !found }'
    return
  fi
  "$PYTHON_BIN" - "$port" <<'PY'
import socket
import sys

port = int(sys.argv[1])
with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
    sys.exit(0 if sock.connect_ex(("127.0.0.1", port)) == 0 else 1)
PY
}
select_api_port() {
  if [ "$DRY_RUN" = "1" ]; then
    return
  fi
  if ! port_in_use "$AUTOFB_API_PORT"; then
    return
  fi
  if [ -n "$AUTOFB_API_PORT_WAS_SET" ]; then
    echo "AUTOFB_API_PORT=$AUTOFB_API_PORT is already in use. Choose another port, e.g. AUTOFB_API_PORT=8002." >&2
    exit 1
  fi
  local candidate
  for candidate in $(seq 8002 8010); do
    if ! port_in_use "$candidate"; then
      log "Port $AUTOFB_API_PORT is already in use; using 127.0.0.1:$candidate for AutoFB API instead."
      AUTOFB_API_PORT="$candidate"
      return
    fi
  done
  echo "No free local API port found in 8001-8010. Stop the process using 8001 or set AUTOFB_API_PORT." >&2
  exit 1
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

  local common_packages=(ca-certificates curl git make rsync ufw)
  run apt-get install -y "${common_packages[@]}"

  if command -v docker >/dev/null 2>&1 && docker compose version >/dev/null 2>&1; then
    log "Docker and Docker Compose plugin are already installed. Skipping Docker package install."
    run systemctl enable --now docker
    return
  fi

  if apt-cache policy docker-ce 2>/dev/null | awk '/Candidate:/ { found=1; candidate=$2 } END { exit !(found && candidate != "(none)") }'; then
    log "Docker CE repository detected; installing Docker CE packages to avoid docker.io/containerd.io conflicts."
    run apt-get install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin
  else
    log "Docker CE repository not detected; installing Ubuntu docker.io packages."
    run apt-get install -y docker.io docker-compose-plugin
  fi

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
quarantine_untracked_root_index() {
  if [ ! -f "$APP_DIR/index.html" ]; then
    return
  fi
  if [ -d "$APP_DIR/.git" ] && git -C "$APP_DIR" ls-files --error-unmatch index.html >/dev/null 2>&1; then
    return
  fi

  local backup_path
  backup_path="$APP_DIR/index.html.aapanel-backup-$(date +%Y%m%d%H%M%S)"
  log "Moving stale aaPanel root index.html aside so the domain can use the AutoFB reverse proxy: $backup_path"
  run mv "$APP_DIR/index.html" "$backup_path"
}
checkout_or_update_repo() {
  log "Preparing application directory: $APP_DIR"
  run mkdir -p "$(dirname "$APP_DIR")"
  if [ -d "$APP_DIR/.git" ]; then
    run git -C "$APP_DIR" pull --ff-only
    quarantine_untracked_root_index
    return
  fi
  if [ -n "$REPO_URL" ]; then
    if [ ! -d "$APP_DIR" ] || [ -z "$(find "$APP_DIR" -mindepth 1 -maxdepth 1 -print -quit 2>/dev/null)" ]; then
      run git clone "$REPO_URL" "$APP_DIR"
      quarantine_untracked_root_index
      return
    fi

    local clone_dir
    clone_dir="$(mktemp -d)"
    log "$APP_DIR is not empty; preserving its existing files while adding the AutoFB checkout."
    if ! run git clone "$REPO_URL" "$clone_dir/repository"; then
      rm -rf -- "$clone_dir"
      return 1
    fi
    run rsync -a "$clone_dir/repository/" "$APP_DIR/"
    rm -rf -- "$clone_dir"
    quarantine_untracked_root_index
    return
  fi
  if [ -f "docker-compose.yml" ] && [ -f "Dockerfile" ]; then
    log "No REPO_URL provided; copying current directory into $APP_DIR"
    run mkdir -p "$APP_DIR"
    run rsync -a --delete --exclude .git ./ "$APP_DIR/"
    quarantine_untracked_root_index
    return
  fi
  cat >&2 <<MSG
REPO_URL is required when the script is not run from an AutoFB checkout.
Example one-liner:
  curl -fsSL https://raw.githubusercontent.com/YOUR_ORG/YOUR_REPO/main/deploy/aapanel_ubuntu_24_04.sh | sudo env REPO_URL=https://github.com/YOUR_ORG/YOUR_REPO.git DOMAIN=tool.huongdancauca.com APP_DIR=/www/wwwroot/tool.huongdancauca.com bash
  REPO_URL=https://github.com/YOUR_ORG/YOUR_REPO.git bash <(curl -fsSL https://raw.githubusercontent.com/YOUR_ORG/YOUR_REPO/main/deploy/aapanel_ubuntu_24_04.sh)
MSG
  exit 1
}
write_runtime_files() {
  log "Writing .env, config.json and docker-compose.override.yml"
  if [ "$DRY_RUN" = "1" ] && [ ! -d "$APP_DIR" ]; then
    log "DRY_RUN=1 and $APP_DIR does not exist; skipping runtime file writes."
    return
  fi
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
AUTOFB_ENABLE_HSTS=${AUTOFB_ENABLE_HSTS:-1}
AUTOFB_PUBLIC_URL=${AUTOFB_PUBLIC_URL:-https://$DOMAIN}
AUTOFB_MEDIA_BACKEND=${AUTOFB_MEDIA_BACKEND:-local}
AUTOFB_S3_BUCKET=${AUTOFB_S3_BUCKET:-}
AUTOFB_S3_PREFIX=${AUTOFB_S3_PREFIX:-autofb-media}
AUTOFB_S3_ENDPOINT_URL=${AUTOFB_S3_ENDPOINT_URL:-}
AUTOFB_S3_REGION=${AUTOFB_S3_REGION:-}
AWS_ACCESS_KEY_ID=${AWS_ACCESS_KEY_ID:-}
AWS_SECRET_ACCESS_KEY=${AWS_SECRET_ACCESS_KEY:-}
AWS_SESSION_TOKEN=${AWS_SESSION_TOKEN:-}
AUTOFB_OFFSITE_BACKUP_URL=${AUTOFB_OFFSITE_BACKUP_URL:-}
AUTOFB_OFFSITE_BACKUP_TOKEN=${AUTOFB_OFFSITE_BACKUP_TOKEN:-}
AUTOFB_BACKUP_ALERT_URL=${AUTOFB_BACKUP_ALERT_URL:-}
AUTOFB_BACKUP_ALERT_TOKEN=${AUTOFB_BACKUP_ALERT_TOKEN:-}
AUTOFB_ERROR_WEBHOOK_URL=${AUTOFB_ERROR_WEBHOOK_URL:-}
AUTOFB_ERROR_WEBHOOK_TOKEN=${AUTOFB_ERROR_WEBHOOK_TOKEN:-}
AUTOFB_IMAGE_UPLOAD_URL=${AUTOFB_IMAGE_UPLOAD_URL:-}
AUTOFB_IMAGE_UPLOAD_TOKEN=${AUTOFB_IMAGE_UPLOAD_TOKEN:-}
IMGBB_API_KEY=${IMGBB_API_KEY:-}
ENV
    chmod 600 .env
  fi

  ensure_env_value() {
    key="$1"
    value="$2"
    if ! grep -q "^${key}=" .env; then
      printf '%s=%s\n' "$key" "$value" >> .env
    fi
  }
  ensure_env_value DOMAIN "$DOMAIN"
  ensure_env_value META_APP_ID "${META_APP_ID:-}"
  ensure_env_value META_APP_SECRET "${META_APP_SECRET:-}"
  ensure_env_value META_REDIRECT_URI "${META_REDIRECT_URI:-https://$DOMAIN/api/v1/oauth/facebook/callback}"
  ensure_env_value AUTOFB_TOKEN_ENCRYPTION_KEY "$fernet_key"
  ensure_env_value AUTOFB_ENABLE_HSTS "${AUTOFB_ENABLE_HSTS:-1}"
  ensure_env_value AUTOFB_PUBLIC_URL "${AUTOFB_PUBLIC_URL:-https://$DOMAIN}"
  ensure_env_value AUTOFB_MEDIA_BACKEND "${AUTOFB_MEDIA_BACKEND:-local}"
  ensure_env_value AUTOFB_S3_BUCKET "${AUTOFB_S3_BUCKET:-}"
  ensure_env_value AUTOFB_S3_PREFIX "${AUTOFB_S3_PREFIX:-autofb-media}"
  ensure_env_value AUTOFB_S3_ENDPOINT_URL "${AUTOFB_S3_ENDPOINT_URL:-}"
  ensure_env_value AUTOFB_S3_REGION "${AUTOFB_S3_REGION:-}"
  ensure_env_value AWS_ACCESS_KEY_ID "${AWS_ACCESS_KEY_ID:-}"
  ensure_env_value AWS_SECRET_ACCESS_KEY "${AWS_SECRET_ACCESS_KEY:-}"
  ensure_env_value AWS_SESSION_TOKEN "${AWS_SESSION_TOKEN:-}"
  ensure_env_value AUTOFB_OFFSITE_BACKUP_URL "${AUTOFB_OFFSITE_BACKUP_URL:-}"
  ensure_env_value AUTOFB_OFFSITE_BACKUP_TOKEN "${AUTOFB_OFFSITE_BACKUP_TOKEN:-}"
  ensure_env_value AUTOFB_BACKUP_ALERT_URL "${AUTOFB_BACKUP_ALERT_URL:-}"
  ensure_env_value AUTOFB_BACKUP_ALERT_TOKEN "${AUTOFB_BACKUP_ALERT_TOKEN:-}"
  ensure_env_value AUTOFB_ERROR_WEBHOOK_URL "${AUTOFB_ERROR_WEBHOOK_URL:-}"
  ensure_env_value AUTOFB_ERROR_WEBHOOK_TOKEN "${AUTOFB_ERROR_WEBHOOK_TOKEN:-}"
  ensure_env_value AUTOFB_IMAGE_UPLOAD_URL "${AUTOFB_IMAGE_UPLOAD_URL:-}"
  ensure_env_value AUTOFB_IMAGE_UPLOAD_TOKEN "${AUTOFB_IMAGE_UPLOAD_TOKEN:-}"
  ensure_env_value IMGBB_API_KEY "${IMGBB_API_KEY:-}"
  chmod 600 .env

  cat > docker-compose.override.yml <<'YAML'
services:
  autofb-api:
    ports: !override
YAML
  cat >> docker-compose.override.yml <<YAML
      - "127.0.0.1:${AUTOFB_API_PORT}:8001"
YAML
  cat >> docker-compose.override.yml <<'YAML'
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
validate_python_sources() {
  if [ "$DRY_RUN" = "1" ] && [ ! -d "$APP_DIR" ]; then
    return
  fi
  cd "$APP_DIR"
  log "Validating Python source syntax before Docker startup"
  run python3 -m compileall -q autofb tools
}

build_and_start() {
  log "Building and starting AutoFB API + worker"
  if [ "$DRY_RUN" = "1" ] && [ ! -d "$APP_DIR" ]; then
    log "DRY_RUN=1 and $APP_DIR does not exist; skipping Docker Compose startup."
    return
  fi
  cd "$APP_DIR"
  validate_python_sources
  backup_url="$(sed -n 's/^AUTOFB_OFFSITE_BACKUP_URL=//p' .env | tail -n 1)"
  if [ -n "$backup_url" ]; then
    run docker compose --profile backup up -d --build autofb-api autofb-worker autofb-backup
  else
    run docker compose up -d --build autofb-api autofb-worker
    log "Off-site backup service not started; configure AUTOFB_OFFSITE_BACKUP_URL before pilot acceptance."
  fi
}
wait_for_health() {
  if [ "$DRY_RUN" = "1" ]; then
    return
  fi
  log "Waiting for API health check"
  for _ in $(seq 1 30); do
    if curl -fsS "http://127.0.0.1:${AUTOFB_API_PORT}/healthz" >/dev/null 2>&1; then
      log "API is healthy"
      return
    fi
    sleep 2
  done
  echo "API did not become healthy. Check: docker compose logs --tail=200 autofb-api" >&2
  exit 1
}
bootstrap_admin_if_configured() {
  if [ -z "${AUTOFB_ADMIN_EMAIL:-}" ] && [ -z "${AUTOFB_ADMIN_PASSWORD:-}" ]; then
    log "AUTOFB_ADMIN_EMAIL/PASSWORD not set; create the first user in the UI or rerun with admin env vars."
    return
  fi
  if [ -z "${AUTOFB_ADMIN_EMAIL:-}" ] || [ -z "${AUTOFB_ADMIN_PASSWORD:-}" ]; then
    echo "Set both AUTOFB_ADMIN_EMAIL and AUTOFB_ADMIN_PASSWORD to bootstrap the first account." >&2
    exit 1
  fi
  if [ "$DRY_RUN" = "1" ] && [ ! -d "$APP_DIR" ]; then
    log "DRY_RUN=1 and $APP_DIR does not exist; skipping admin bootstrap."
    return
  fi
  log "Bootstrapping first AutoFB admin account"
  cd "$APP_DIR"
  run docker compose exec -T \
    -e AUTOFB_ADMIN_EMAIL \
    -e AUTOFB_ADMIN_PASSWORD \
    -e AUTOFB_ADMIN_DISPLAY_NAME \
    -e AUTOFB_ADMIN_WORKSPACE \
    autofb-api python tools/create_admin.py
}
print_next_steps() {
  cat <<MSG

AutoFB deploy script finished.

Domain: https://$DOMAIN
App dir: $APP_DIR
Local API: http://127.0.0.1:$AUTOFB_API_PORT

In aaPanel, create/reuse website $DOMAIN and add Reverse Proxy:
  Target URL: http://127.0.0.1:$AUTOFB_API_PORT
Then enable Let's Encrypt SSL and Force HTTPS.

Meta OAuth redirect URI:
  https://$DOMAIN/api/v1/oauth/facebook/callback

Optional first-admin bootstrap:
  AUTOFB_ADMIN_EMAIL=admin@example.com AUTOFB_ADMIN_PASSWORD='change-this-strong-password' AUTOFB_ADMIN_WORKSPACE='Main' bash deploy/aapanel_ubuntu_24_04.sh

Useful commands:
  cd $APP_DIR
  docker compose ps
  docker compose logs -f autofb-api
  docker compose logs -f autofb-worker
  docker compose logs -f autofb-backup
  docker compose up -d --build autofb-api autofb-worker
  make check
  docker compose exec -T autofb-api make preflight
  make pilot-acceptance URL=https://$DOMAIN

If Meta OAuth, off-site backup or alert receivers are not configured yet, edit:
  $APP_DIR/.env
then restart:
  cd $APP_DIR && docker compose up -d --build autofb-api autofb-worker
MSG
}
main() {
  require_root
  install_system_packages
  open_firewall_ports
  install_aapanel_if_requested
  checkout_or_update_repo
  select_api_port
  write_runtime_files
  build_and_start
  wait_for_health
  bootstrap_admin_if_configured
  print_next_steps
}
if [[ "${BASH_SOURCE[0]:-$0}" == "$0" ]]; then
  main "$@"
fi
