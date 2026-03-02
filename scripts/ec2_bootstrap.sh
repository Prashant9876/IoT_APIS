#!/usr/bin/env bash
set -euo pipefail

APP_DIR="/opt/iot_apis"
SERVICE_NAME="iot-apis"
REPO_URL="${1:-https://github.com/Prashant9876/IoT_APIS.git}"
RUN_USER="${2:-ubuntu}"

sudo apt update
sudo apt install -y python3-venv python3-pip git

sudo mkdir -p "$APP_DIR"
sudo chown -R "$RUN_USER":"$RUN_USER" "$APP_DIR"

if [ ! -d "$APP_DIR/.git" ]; then
  git clone "$REPO_URL" "$APP_DIR"
fi

cd "$APP_DIR"
python3 -m venv .venv
source .venv/bin/activate
pip install --upgrade pip
pip install -r requirements.txt

if [ ! -f .env ]; then
  cp .env.example .env
  echo "Created $APP_DIR/.env. Update it before starting service."
fi

sudo cp deploy/ec2/iot-apis.service /etc/systemd/system/iot-apis.service
sudo sed -i "s|__RUN_USER__|$RUN_USER|g" /etc/systemd/system/iot-apis.service

sudo systemctl daemon-reload
sudo systemctl enable "$SERVICE_NAME"
echo "Bootstrap complete. Run: sudo systemctl start $SERVICE_NAME"
