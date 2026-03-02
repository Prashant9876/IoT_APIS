#!/usr/bin/env bash
set -euo pipefail

APP_DIR="/opt/IoT_Apis"
SERVICE_NAME="iot-apis"
RUN_USER="${1:-ubuntu}"

sudo cp "$APP_DIR/deploy/ec2/iot-apis.service" "/etc/systemd/system/${SERVICE_NAME}.service"
sudo sed -i "s|__RUN_USER__|${RUN_USER}|g" "/etc/systemd/system/${SERVICE_NAME}.service"
sudo systemctl daemon-reload
sudo systemctl enable "$SERVICE_NAME"
sudo systemctl restart "$SERVICE_NAME"
sudo systemctl is-active "$SERVICE_NAME"
