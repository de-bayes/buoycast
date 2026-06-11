#!/bin/bash
# One-shot provisioning for a fresh Debian/Ubuntu VM (tested mentally against
# GCE e2-medium + Debian 12). Run as root from the repo's deploy/ directory:
#
#   git clone https://github.com/de-bayes/buoycast.git /opt/buoycast
#   cd /opt/buoycast/deploy && sudo bash setup_vps.sh
#
# What it does: system deps, a dedicated user, a venv, systemd timers
# (hourly publish, weekly retrain), optional Caddy for serving, and the
# initial data fetch + train so the site is live before the first timer fires.
set -euo pipefail

REPO=/opt/buoycast

echo "== system packages"
apt-get update -qq
apt-get install -y -qq python3 python3-venv git curl

echo "== user + permissions"
id -u buoycast &>/dev/null || useradd --system --home "$REPO" --shell /usr/sbin/nologin buoycast
chown -R buoycast:buoycast "$REPO"

echo "== python venv"
sudo -u buoycast python3 -m venv "$REPO/venv"
sudo -u buoycast "$REPO/venv/bin/pip" install --quiet --upgrade pip
sudo -u buoycast "$REPO/venv/bin/pip" install --quiet -r "$REPO/requirements.txt"

echo "== systemd units"
cp "$REPO"/deploy/buoycast-publish.{service,timer} /etc/systemd/system/
cp "$REPO"/deploy/buoycast-retrain.{service,timer} /etc/systemd/system/
systemctl daemon-reload
systemctl enable --now buoycast-publish.timer buoycast-retrain.timer

echo "== initial bootstrap (fetch ~10 seasons of data, train, publish; ~30-60 min)"
sudo -u buoycast bash -c "cd $REPO && set -e \
  && venv/bin/python fetch.py \
  && venv/bin/python fetch_weather.py \
  && venv/bin/python train_q.py --refit-full \
  && venv/bin/python backtest.py \
  && venv/bin/python corr.py \
  && venv/bin/python publish.py"

cat <<'EOF'

Done. The forecast regenerates hourly and retrains Sundays.

To serve the site from this VM (Option A in DEPLOY.md):
  apt-get install -y caddy
  cp /opt/buoycast/deploy/Caddyfile /etc/caddy/Caddyfile   # edit the domain first
  systemctl reload caddy

To serve the site from Vercel instead (Option B), see DEPLOY.md.
Check timers:   systemctl list-timers 'buoycast-*'
Check last run: journalctl -u buoycast-publish -n 30
EOF
