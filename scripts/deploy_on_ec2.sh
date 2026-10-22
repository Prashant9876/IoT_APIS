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

if ! sudo systemctl cat "$SERVICE_NAME" >/dev/null 2>&1; then
  echo "Service ${SERVICE_NAME}.service not found. Run the EC2 bootstrap first."
  exit 1
fi

sudo systemctl restart "$SERVICE_NAME"
sudo systemctl is-active "$SERVICE_NAME"
