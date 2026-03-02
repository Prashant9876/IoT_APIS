#!/usr/bin/env bash
set -euo pipefail

APP_DIR="/opt/iot_apis"
SERVICE_NAME="iot-apis"

cd "$APP_DIR"
git fetch origin main
git reset --hard origin/main

source .venv/bin/activate
pip install -r requirements.txt

sudo systemctl restart "$SERVICE_NAME"
sudo systemctl is-active "$SERVICE_NAME"
