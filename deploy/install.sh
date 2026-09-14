#!/usr/bin/env bash
# Idempotent install of the Sumaer Research Bot on Ubuntu 24.04 (Hetzner CX32 / GCP e2-standard-2).
# Run as root once; re-run after every deploy (git pull) — it only changes what differs.
set -euo pipefail
APP_USER=eqr
APP_DIR=/opt/eqr
REPO_URL="${EQR_REPO_URL:-https://github.com/sumaer123/research-bot.git}"
DOMAIN="${EQR_DOMAIN:-}"          # optional: public hostname for Caddy TLS

id -u "$APP_USER" >/dev/null 2>&1 || useradd --system --create-home --home-dir /home/$APP_USER --shell /bin/bash "$APP_USER"
apt-get update -qq && apt-get install -y -qq git curl unzip restic ca-certificates >/dev/null
if ! command -v uv >/dev/null; then curl -LsSf https://astral.sh/uv/install.sh | env UV_INSTALL_DIR=/usr/local/bin sh; fi
if [ ! -d "$APP_DIR/.git" ]; then git clone "$REPO_URL" "$APP_DIR"; fi
chown -R "$APP_USER:$APP_USER" "$APP_DIR"
sudo -u "$APP_USER" bash -c "cd $APP_DIR && uv venv --python 3.13 .venv -q && uv pip install --python .venv/bin/python -q -e '.[dev]'"
sudo -u "$APP_USER" bash -c "cd $APP_DIR && [ -f .env ] || cp .env.example .env"
sudo -u "$APP_USER" bash -c "cd $APP_DIR && .venv/bin/eqr init"
install -m 644 "$APP_DIR"/deploy/systemd/*.service "$APP_DIR"/deploy/systemd/*.timer /etc/systemd/system/
systemctl daemon-reload
systemctl enable --now eqr-web.service eqr-refresh.timer eqr-fundamentals.timer eqr-digest.timer eqr-backup.timer
if [ -n "$DOMAIN" ]; then
  if ! command -v caddy >/dev/null; then
    apt-get install -y -qq debian-keyring debian-archive-keyring apt-transport-https >/dev/null
    curl -1sLf 'https://dl.cloudsmith.io/public/caddy/stable/gpg.key' | gpg --dearmor -o /usr/share/keyrings/caddy-stable-archive-keyring.gpg
    curl -1sLf 'https://dl.cloudsmith.io/public/caddy/stable/debian.deb.txt' > /etc/apt/sources.list.d/caddy-stable.list
    apt-get update -qq && apt-get install -y -qq caddy >/dev/null
  fi
  sed "s/__DOMAIN__/$DOMAIN/" "$APP_DIR/deploy/Caddyfile" > /etc/caddy/Caddyfile
  systemctl reload caddy || systemctl restart caddy
fi
sudo -u "$APP_USER" bash -c "cd $APP_DIR && .venv/bin/python -m pytest -q tests/ 2>&1 | tail -1"
echo "eqr installed at $APP_DIR; web on 127.0.0.1:8801; timers: $(systemctl list-timers 'eqr-*' --no-legend | wc -l)"
