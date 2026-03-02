from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)
API_KEY = "test-api-key"


def test_health_endpoint_returns_mqtt_status_key():
    response = client.get("/health")
    assert response.status_code == 200
    body = response.json()
    assert "mqtt_status" in body
    assert body["mqtt_status"] in {"connected", "disconnected"}


def test_backend_publisher_requires_api_key():
    response = client.post("/api/irrigation", json={"DN": "IDC", "FarmID": "F001"})
    assert response.status_code == 403


def test_backend_publisher_missing_required_keys():
    response = client.post(
        "/api/irrigation",
        headers={"x-api-key": API_KEY},
        json={"DN": "IDC"},
    )
    assert response.status_code == 400


def test_backend_publisher_success():
    payload = {"DN": "IDC", "FarmID": "F001", "DeviceID": "D01"}
    response = client.post(
        "/api/irrigation",
        headers={"x-api-key": API_KEY},
        json=payload,
    )

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "accepted"
    assert body["topic"] == "farm/F001/IIrrigation"
    assert body["payload"]["DeviceID"] == "D01"


def test_fertigation_invalid_cmd_rejected():
    payload = {
        "DN": "FU",
        "FarmID": "F001",
        "cmd": "wrong_cmd",
        "eC": {"LL": 1, "HL": 2},
        "pH": {"LL": 5, "HL": 6},
    }
    response = client.post(
        "/api/fertigation",
        headers={"x-api-key": API_KEY},
        json=payload,
    )
    assert response.status_code == 400


def test_fertigation_success_and_float_conversion():
    payload = {
        "DN": "FU",
        "FarmID": "F001",
        "cmd": "change_limits",
        "eC": {"LL": "1.2", "HL": "2.4"},
        "pH": {"LL": "5.5", "HL": "6.5"},
    }
    response = client.post(
        "/api/fertigation",
        headers={"x-api-key": API_KEY},
        json=payload,
    )

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "accepted"
    assert body["topic"] == "farm/F001/fertigation"
    assert body["payload"]["eC"]["LL"] == 1.2
    assert body["payload"]["pH"]["HL"] == 6.5


def test_robot_endpoint_success():
    payload = {"DN": "RB", "FarmID": "F002", "DeviceID": "R1"}
    response = client.post(
        "/api/robot",
        headers={"x-api-key": API_KEY},
        json=payload,
    )

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "accepted"
    assert body["topic"] == "farm/F002/SSub"
