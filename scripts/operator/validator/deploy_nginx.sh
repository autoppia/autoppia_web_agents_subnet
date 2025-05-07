#!/usr/bin/env bash
set -euo pipefail

# ensure the script is run as root
if [[ $EUID -ne 0 ]]; then
  echo "Please run as root or with sudo"
  exit 1
fi

# locate this script's directory
BASE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# path to your nginx conf in the submodule
CONF_SRC="$BASE_DIR/autoppia_web_operator/nginx_default.conf"
NGINX_CONF="/etc/nginx/sites-available/default"
BACKUP_CONF="/etc/nginx/sites-available/default.bak.$(date +%Y%m%d%H%M%S)"

# verify source config exists
if [[ ! -f "$CONF_SRC" ]]; then
  echo "Config file not found at $CONF_SRC"
  exit 1
fi

# install nginx if missing
if ! command -v nginx >/dev/null 2>&1; then
  if command -v apt-get >/dev/null 2>&1; then
    apt-get update
    apt-get install -y nginx
  elif command -v yum >/dev/null 2>&1; then
    yum install -y epel-release
    yum install -y nginx
  else
    echo "Neither apt-get nor yum found; install nginx manually."
    exit 1
  fi
fi

# backup existing config
if [[ -f "$NGINX_CONF" ]]; then
  cp "$NGINX_CONF" "$BACKUP_CONF"
  echo "Backed up existing config to $BACKUP_CONF"
fi

# deploy new config
cp "$CONF_SRC" "$NGINX_CONF"
echo "Deployed new nginx config from $CONF_SRC"

# test and reload nginx
nginx -t
if command -v systemctl >/dev/null 2>&1; then
  systemctl reload nginx
else
  service nginx reload
fi

echo "nginx deployed successfully."
