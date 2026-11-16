#!/usr/bin/env bash
# Install or upgrade roborock-homekit on a Raspberry Pi (Raspberry Pi OS Bookworm or Trixie).
#
#   sudo ./scripts/install.sh
#
# Safe to re-run: it upgrades the code in place and never overwrites your config
# or login/pairing state.
set -euo pipefail

APP=roborock-homekit
VENV=/opt/$APP
CONFIG_DIR=/etc/$APP
STATE_DIR=/var/lib/$APP
SERVICE_FILE=/etc/systemd/system/$APP.service
WRAPPER=/usr/local/bin/$APP
REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

log() { printf '\n\033[1;34m==> %s\033[0m\n' "$*"; }
die() { printf '\033[1;31mError: %s\033[0m\n' "$*" >&2; exit 1; }

[[ $EUID -eq 0 ]] || die "run with sudo: sudo $0"

PYTHON=$(command -v python3) || die "python3 not found"
"$PYTHON" -c 'import sys; sys.exit(sys.version_info < (3, 11))' \
  || die "Python 3.11+ required (Raspberry Pi OS Bookworm or newer)"

log "Installing system packages"
apt-get update -qq
# python3-venv for the virtualenv; the rest are runtime libraries for the
# prebuilt Pillow wheel from piwheels.
apt-get install -y -qq python3-venv libopenjp2-7 libwebpdemux2 libwebpmux3 liblcms2-2

log "Creating service user"
if ! id -u "$APP" >/dev/null 2>&1; then
  useradd --system --home-dir "$STATE_DIR" --no-create-home --shell /usr/sbin/nologin "$APP"
fi
install -d -o "$APP" -g "$APP" -m 0700 "$STATE_DIR"

log "Creating virtualenv in $VENV"
[[ -x $VENV/bin/python ]] || "$PYTHON" -m venv "$VENV"
"$VENV/bin/pip" install -q --upgrade pip

log "Installing Python dependencies (prebuilt wheels only; this can take ~10 minutes on a Pi Zero)"
"$VENV/bin/pip" install \
  --index-url https://www.piwheels.org/simple \
  --extra-index-url https://pypi.org/simple \
  --only-binary=:all: \
  -r "$REPO_DIR/requirements-pi.txt"

log "Installing $APP"
"$VENV/bin/pip" install -q --no-deps --force-reinstall "$REPO_DIR"
cp "$REPO_DIR/README.md" "$VENV/README.md"

log "Installing config"
install -d -m 0755 "$CONFIG_DIR"
if [[ ! -f $CONFIG_DIR/config.toml ]]; then
  install -m 0644 "$REPO_DIR/config.example.toml" "$CONFIG_DIR/config.toml"
  NEW_CONFIG=1
fi
install -m 0644 "$REPO_DIR/config.example.toml" "$CONFIG_DIR/config.example.toml"

log "Installing '$APP' command"
# Wrapper so every command runs as the service user (who owns the state dir).
cat > "$WRAPPER" <<WRAP
#!/bin/sh
if [ "\$(id -un)" = "$APP" ]; then
  exec $VENV/bin/$APP "\$@"
fi
exec sudo -u $APP $VENV/bin/$APP "\$@"
WRAP
chmod 0755 "$WRAPPER"

log "Installing systemd service"
install -m 0644 "$REPO_DIR/deploy/$APP.service" "$SERVICE_FILE"
systemctl daemon-reload
systemctl enable "$APP" >/dev/null

if systemctl is-active --quiet "$APP"; then
  log "Restarting running service"
  systemctl restart "$APP"
fi

log "Done"
if [[ ${NEW_CONFIG:-0} == 1 ]]; then
  cat <<NEXT

Next steps:
  1. Set your Roborock email:   sudo nano $CONFIG_DIR/config.toml
  2. Log in (emails a code):    $APP login
  3. Check it can see it:       $APP status
  4. Start the bridge:          sudo systemctl start $APP
  5. Pair with Apple Home:      $APP pairing-info
NEXT
fi
