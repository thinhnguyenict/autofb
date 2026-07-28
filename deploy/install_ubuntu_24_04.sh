#!/usr/bin/env bash
set -Eeuo pipefail

log() { printf '\n[AutoFB installer] %s\n' "$*"; }
fail() { echo "Error: $*" >&2; exit 1; }

validate_domain() {
  [[ "$1" =~ ^([A-Za-z0-9]([A-Za-z0-9-]{0,61}[A-Za-z0-9])?\.)+[A-Za-z]{2,63}$ ]]
}

validate_port() {
  [[ "$1" =~ ^[0-9]+$ ]] && ((10#$1 >= 1024 && 10#$1 <= 65535))
}

prompt_value() {
  local variable="$1" label="$2" default_value="${3:-}" required="${4:-0}" value value_input
  value="${!variable:-$default_value}"
  while true; do
    if [ -n "$value" ]; then
      read -r -p "$label [$value]: " value_input </dev/tty || fail "Cannot read installer input"
      value="${value_input:-$value}"
    else
      read -r -p "$label: " value </dev/tty || fail "Cannot read installer input"
    fi
    if [ "$required" != "1" ] || [ -n "$value" ]; then
      printf -v "$variable" '%s' "$value"
      export "$variable"
      return
    fi
    echo "$label is required." >&2
  done
}

prompt_secret() {
  local variable="$1" label="$2" required="${3:-0}" value value_input
  value="${!variable:-}"
  while true; do
    if [ -n "$value" ]; then
      read -r -s -p "$label [keep current value]: " value_input </dev/tty || fail "Cannot read installer input"
      echo >&2
      value="${value_input:-$value}"
    else
      read -r -s -p "$label: " value </dev/tty || fail "Cannot read installer input"
      echo >&2
    fi
    if [ "$required" != "1" ] || [ -n "$value" ]; then
      printf -v "$variable" '%s' "$value"
      export "$variable"
      return
    fi
    echo "$label is required." >&2
  done
}

prompt_yes_no() {
  local variable="$1" label="$2" default_value="${3:-0}" answer suffix
  suffix="y/N"
  [ "$default_value" = "1" ] && suffix="Y/n"
  read -r -p "$label [$suffix]: " answer </dev/tty || fail "Cannot read installer input"
  case "${answer,,}" in
    y|yes) printf -v "$variable" 1 ;;
    n|no) printf -v "$variable" 0 ;;
    "") printf -v "$variable" '%s' "$default_value" ;;
    *) echo "Please answer y or n." >&2; prompt_yes_no "$variable" "$label" "$default_value"; return ;;
  esac
  export "$variable"
}

check_host() {
  [ "${EUID:-$(id -u)}" -eq 0 ] || fail "Run the one-line installer as root or with sudo"
  [ -r /etc/os-release ] || fail "Cannot identify this operating system"
  # shellcheck disable=SC1091
  . /etc/os-release
  [ "${ID:-}" = "ubuntu" ] && [ "${VERSION_ID:-}" = "24.04" ] || \
    fail "This installer supports Ubuntu 24.04 only"
  [ -r /dev/tty ] || fail "An interactive terminal is required. Use bash -c \"\$(curl -fsSL URL)\", not curl URL | bash"
}

collect_settings() {
  log "Enter deployment settings. Press Enter to accept a displayed default."
  prompt_value DOMAIN "Application domain (without https://)" "${DOMAIN:-}" 1
  validate_domain "$DOMAIN" || fail "Invalid domain: $DOMAIN"

  prompt_value REPO_URL "Git repository URL" "${REPO_URL:-}" 1
  [[ "$REPO_URL" =~ ^https://|^ssh://|^git@ ]] || fail "Repository URL must use HTTPS or SSH"
  [[ "$REPO_URL" != https://*@* ]] || fail "Repository URL cannot contain credentials; use an SSH deploy key"
  prompt_value APP_DIR "Installation directory" "${APP_DIR:-/www/wwwroot/$DOMAIN}" 1
  [[ "$APP_DIR" =~ ^/[A-Za-z0-9._/-]+$ ]] || fail "Installation directory must be a safe absolute path"
  prompt_value AUTOFB_API_PORT "Local API port" "${AUTOFB_API_PORT:-8001}" 1
  validate_port "$AUTOFB_API_PORT" || fail "API port must be between 1024 and 65535"
  prompt_yes_no INSTALL_AAPANEL "Install aaPanel if it is not present?" "${INSTALL_AAPANEL:-0}"

  log "Meta and first-admin settings may be left blank and configured later in $APP_DIR/.env."
  prompt_value META_APP_ID "Meta App ID (optional)" "${META_APP_ID:-}"
  prompt_secret META_APP_SECRET "Meta App Secret (optional)"
  META_REDIRECT_URI="${META_REDIRECT_URI:-https://$DOMAIN/api/v1/oauth/facebook/callback}"
  AUTOFB_PUBLIC_URL="${AUTOFB_PUBLIC_URL:-https://$DOMAIN}"
  AUTOFB_ENABLE_HSTS="${AUTOFB_ENABLE_HSTS:-1}"
  export META_REDIRECT_URI AUTOFB_PUBLIC_URL AUTOFB_ENABLE_HSTS

  prompt_value AUTOFB_ADMIN_EMAIL "First admin email (optional)" "${AUTOFB_ADMIN_EMAIL:-}"
  if [ -n "$AUTOFB_ADMIN_EMAIL" ]; then
    prompt_secret AUTOFB_ADMIN_PASSWORD "First admin password (minimum 12 characters)" 1
    [ "${#AUTOFB_ADMIN_PASSWORD}" -ge 12 ] || fail "Admin password must contain at least 12 characters"
    prompt_value AUTOFB_ADMIN_WORKSPACE "First workspace name" "${AUTOFB_ADMIN_WORKSPACE:-Main}"
  fi
}

confirm_settings() {
  cat <<SUMMARY

AutoFB installation summary
  Domain:       https://$DOMAIN
  Repository:   $REPO_URL
  Directory:    $APP_DIR
  Local port:   $AUTOFB_API_PORT
  Install panel: $INSTALL_AAPANEL
  Meta App ID:  ${META_APP_ID:-not configured}
  First admin:  ${AUTOFB_ADMIN_EMAIL:-not configured}

Secrets are intentionally not displayed.
SUMMARY
  prompt_yes_no CONFIRMED "Continue installation?" 1
  [ "$CONFIRMED" = "1" ] || fail "Installation cancelled"
}

run_installer() {
  log "Downloading the repository installer"
  apt-get update
  apt-get install -y ca-certificates git
  local bootstrap_dir status
  bootstrap_dir="$(mktemp -d)"
  trap "rm -rf -- '$bootstrap_dir'" EXIT
  git clone --depth 1 "$REPO_URL" "$bootstrap_dir/repository"
  [ -f "$bootstrap_dir/repository/deploy/aapanel_ubuntu_24_04.sh" ] || \
    fail "Repository does not contain deploy/aapanel_ubuntu_24_04.sh"
  bash "$bootstrap_dir/repository/deploy/aapanel_ubuntu_24_04.sh" || status=$?
  status="${status:-0}"
  return "$status"
}

main() {
  check_host
  collect_settings
  confirm_settings
  run_installer
}

if [[ "${BASH_SOURCE[0]}" == "$0" ]]; then
  main "$@"
fi
