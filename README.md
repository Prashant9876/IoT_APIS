# AWS IoT FastAPI Service

This project exposes FastAPI endpoints that validate incoming requests, map payloads to MQTT topics, and publish messages to an MQTT broker.

## Project Structure

```text
AWS_IoT_APIS/
├── requirements.txt
└── app/
    ├── __init__.py
    ├── main.py
    ├── core.py
    └── routers/
        ├── __init__.py
        ├── iot_api.py
        ├── robot_api.py
        └── other_api.py
```

## File-by-File Purpose

### `/Users/prashantsingh/Desktop/innofarm/AWS_IoT_APIS/requirements.txt`
- Python dependencies needed by this service.
- Includes FastAPI, Uvicorn, MQTT client, dotenv, and Mangum.

### `/Users/prashantsingh/Desktop/innofarm/AWS_IoT_APIS/app/__init__.py`
- Marks `app` as a Python package.

### `/Users/prashantsingh/Desktop/innofarm/AWS_IoT_APIS/app/main.py`
- Builds the FastAPI app instance.
- Registers all routers (`iot`, `robot`, `other`).
- Creates Lambda-compatible `handler` using Mangum.

### `/Users/prashantsingh/Desktop/innofarm/AWS_IoT_APIS/app/core.py`
- Shared core logic used by all routers:
- Environment loading (`API_KEY`, MQTT settings).
- MQTT client wrapper with connect/reconnect/publish behavior.
- Common helper functions:
  - `validate_api_key`
  - `require_keys`
  - `get_mqtt_topic`
  - `publish_and_response`

### `/Users/prashantsingh/Desktop/innofarm/AWS_IoT_APIS/app/routers/__init__.py`
- Marks `routers` as a Python package.

### `/Users/prashantsingh/Desktop/innofarm/AWS_IoT_APIS/app/routers/iot_api.py`
- IoT-related API endpoints:
  - `POST /BackendMqttPublisher`
  - `POST /BackendMqttfertigation`
  - `POST /BackendMqttEstopIrrigation`
- Performs route-specific validation and publishes to MQTT through shared core helpers.

### `/Users/prashantsingh/Desktop/innofarm/AWS_IoT_APIS/app/routers/robot_api.py`
- Robot/control endpoint:
  - `POST /BackendAcutatorCmd`
- Validates payload and publishes to MQTT via shared helpers.

### `/Users/prashantsingh/Desktop/innofarm/AWS_IoT_APIS/app/routers/other_api.py`
- Utility/other endpoint:
  - `GET /health`
- Returns MQTT connectivity status.

## Run Locally

```bash
cd /Users/prashantsingh/Desktop/innofarm/AWS_IoT_APIS
pip install -r requirements.txt
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

## Required Environment Variables

- `API_KEY`
- `MQTT_HOST`
- `MQTT_PORT` (default: `1883`)
- `MQTT_USERNAME`
- `MQTT_PASSWORD`
- `MQTT_TLS` (default: `false`)
- `MQTT_KEEPALIVE` (default: `60`)

## CI/CD to EC2 (GitHub Actions)

### Files added for deployment

- `.github/workflows/deploy-ec2.yml`: deploy pipeline on push to `main`
- `scripts/ec2_bootstrap.sh`: one-time EC2 setup
- `scripts/deploy_on_ec2.sh`: deploy script executed on EC2
- `scripts/install_service.sh`: installs/enables `iot-apis` systemd service
- `deploy/ec2/iot-apis.service`: systemd service unit template
- `deploy/nginx/api-iot.innofarms.ai.conf`: Nginx reverse proxy config
- `.env.example`: environment template

### One-time setup on EC2

```bash
cd /opt
sudo git clone https://github.com/Prashant9876/IoT_APIS.git IoT_Apis
cd /opt/IoT_Apis
chmod +x scripts/ec2_bootstrap.sh
./scripts/ec2_bootstrap.sh https://github.com/Prashant9876/IoT_APIS.git ubuntu
```

Then edit:

```bash
nano /opt/IoT_Apis/.env
```

Start service:

```bash
chmod +x scripts/install_service.sh
./scripts/install_service.sh ubuntu
sudo systemctl status iot-apis
```

### Required GitHub Actions secrets

- `EC2_HOST` (Public IP or domain)
- `EC2_USER` (e.g. `ubuntu`)
- `EC2_SSH_KEY` (private key content)
- `EC2_PORT` (usually `22`)

### Deploy flow

- Push any commit to `main`
- GitHub Action SSHes to EC2
- Uploads latest code to `/home/ubuntu/iot_apis_release`
- Syncs code to `/opt/IoT_Apis`
- Installs dependencies (if needed)
- Restarts `iot-apis` systemd service

## Test Cases (CI Gate Before Deploy)

CI now runs tests before deployment. Deployment to EC2 runs only when tests pass.

### Test files

- `tests/conftest.py`: test environment setup
- `tests/test_api.py`: endpoint test cases
- `requirements-dev.txt`: test dependencies (`pytest`, `httpx`)

### Run tests locally

```bash
cd /Users/prashantsingh/Desktop/innofarm/AWS_IoT_APIS
source .venv/bin/activate
pip install -r requirements.txt
pip install -r requirements-dev.txt
pytest -q
```

### CI behavior

- On `pull_request` to `main`: run tests only
- On `push` to `main`: run tests, then deploy to EC2 if tests pass
