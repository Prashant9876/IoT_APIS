#!/usr/bin/env bash
set -euo pipefail

APP_DIR="/opt/IoT_Apis"
SERVICE_NAME="iot-apis"

cd "$APP_DIR"
if [ ! -d .venv ]; then
  python3 -m venv .venv
fi

source .venv/bin/activate
pip install -r requirements.txt

if systemctl list-unit-files | grep -q "^${SERVICE_NAME}.service"; then
  sudo systemctl restart "$SERVICE_NAME"
  sudo systemctl is-active "$SERVICE_NAME"
else
  echo "Service ${SERVICE_NAME}.service not found. Skipping restart."
fi
