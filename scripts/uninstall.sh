#!/usr/bin/env bash
# Remove roborock-homekit. Pass --purge to also delete config, login and pairing state.
set -euo pipefail
APP=roborock-homekit

[[ $EUID -eq 0 ]] || { echo "run with sudo: sudo $0 [--purge]" >&2; exit 1; }

systemctl disable --now "$APP" 2>/dev/null || true
rm -f "/etc/systemd/system/$APP.service" "/usr/local/bin/$APP"
systemctl daemon-reload
rm -rf "/opt/$APP"

if [[ ${1:-} == --purge ]]; then
  rm -rf "/etc/$APP" "/var/lib/$APP"
  userdel "$APP" 2>/dev/null || true
  echo "Removed $APP, its config and state."
else
  echo "Removed $APP. Config (/etc/$APP) and state (/var/lib/$APP) kept; use --purge to delete."
fi
