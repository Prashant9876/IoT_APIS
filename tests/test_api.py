import os

from fastapi.testclient import TestClient

os.environ.setdefault("SKIP_MQTT_CONNECT", "true")

from app.main import app
from app import core
from app.routers import iot_api

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
        "DeviceID": "D01",
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
        "DeviceID": "D01",
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


def test_irrigation_publishes_api_and_device_topics_with_meta(monkeypatch):
    calls = []

    def fake_publish(topic, payload, qos=1, retain=False):
        calls.append((topic, payload))

    monkeypatch.setattr(core.mqtt_client, "publish", fake_publish)

    payload = {"DN": "IDC", "FarmID": "F001", "DeviceID": "D01"}
    response = client.post(
        "/api/irrigation",
        headers={"x-api-key": API_KEY, "x-forwarded-for": "203.0.113.11"},
        json=payload,
    )

    assert response.status_code == 200
    body = response.json()
    assert body["topic"] == "farm/F001/IIrrigation"
    assert "meta" in body["payload"]
    assert body["payload"]["meta"]["forwarded_ip"] == "203.0.113.11"
    assert body["payload"]["Mqtt_topic"] == "farm/F001/IIrrigation"

    assert len(calls) == 2
    assert calls[0][0] == "farm/F001/api"
    assert calls[1][0] == "farm/F001/IIrrigation"
    assert "meta" in calls[0][1]
    assert "Mqtt_topic" in calls[0][1]
    assert "meta" not in calls[1][1]
    assert "Mqtt_topic" not in calls[1][1]


def test_actuator_lcd_newschedule_publishes_after_successful_mongo_update(monkeypatch):
    calls = []

    def fake_publish(topic, payload, qos=1, retain=False):
        calls.append((topic, payload))

    monkeypatch.setattr(core.mqtt_client, "publish", fake_publish)
    monkeypatch.setattr(
        iot_api,
        "update_LCD_Schedule",
        lambda payload: {"ok": True, "updated_fields": ["schedule.L4"], "modified_count": 1},
    )

    payload = {
        "DN": "LCD",
        "FarmID": 120,
        "DeviceID": ["IFLCD2110100001", "IFLCD2110100002"],
        "rack_id": 1,
        "total_shelves": 11,
        "cmd": "newschedule",
        "schedule": {"L4": ["09:15", "20:15"]},
    }
    response = client.post(
        "/api/acutatorCmd",
        headers={"x-api-key": API_KEY},
        json=payload,
    )

    assert response.status_code == 200
    body = response.json()
    assert body["topic"] == "farm/120/SSub"
    assert len(calls) == 2
    assert calls[0][0] == "farm/120/api"
    assert calls[1][0] == "farm/120/SSub"


def test_actuator_lcd_newschedule_returns_error_when_mongo_update_fails(monkeypatch):
    monkeypatch.setattr(
        iot_api,
        "update_LCD_Schedule",
        lambda payload: {
            "ok": False,
            "status_code": 503,
            "detail": "MongoDB Error: timeout",
        },
    )

    payload = {
        "DN": "LCD",
        "FarmID": 120,
        "DeviceID": ["IFLCD2110100001", "IFLCD2110100002"],
        "rack_id": 1,
        "total_shelves": 11,
        "cmd": "newschedule",
        "schedule": {"L4": ["09:15", "20:15"]},
    }
    response = client.post(
        "/api/acutatorCmd",
        headers={"x-api-key": API_KEY},
        json=payload,
    )

    assert response.status_code == 503
    assert response.json() == {"detail": "MongoDB Error: timeout"}
