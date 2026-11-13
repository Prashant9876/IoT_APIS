from fastapi.testclient import TestClient

from app import core
from app.main import app
from app.routers import redis_update


client = TestClient(app)
API_KEY = core.API_KEY


def test_add_timezone_adds_then_updates_farm(monkeypatch):
    values = {}

    def fake_add_farm_to_redis(farm_id, timezone_name):
        field = str(farm_id)
        action = "added" if field not in values else "updated"
        values[field] = timezone_name
        return {
            "success": True,
            "action": action,
            "message": f"Farm {farm_id} {action} with timezone {timezone_name}",
        }

    monkeypatch.setattr(redis_update, "add_farm_to_redis", fake_add_farm_to_redis)

    add_response = client.post(
        "/api/add_timezone",
        headers={"x-api-key": API_KEY},
        json={"farm_id": 125, "timezone": "Asia/Kolkata"},
    )
    update_response = client.post(
        "/api/add_timezone",
        headers={"x-api-key": API_KEY},
        json={"farm_id": 125, "timezone": "Australia/Perth"},
    )

    assert add_response.status_code == 200
    assert add_response.json()["action"] == "added"
    assert update_response.status_code == 200
    assert update_response.json()["action"] == "updated"
    assert values == {"125": "Australia/Perth"}


def test_add_timezone_rejects_missing_or_invalid_timezone(monkeypatch):
    monkeypatch.setattr(redis_update, "add_farm_to_redis", lambda *_args: None)

    missing_response = client.post(
        "/api/add_timezone",
        headers={"x-api-key": API_KEY},
        json={"farm_id": 125},
    )
    invalid_response = client.post(
        "/api/add_timezone",
        headers={"x-api-key": API_KEY},
        json={"farm_id": 125, "timezone": "Invalid/Timezone"},
    )

    assert missing_response.status_code == 400
    assert missing_response.json()["detail"] == "Missing required keys: farm_id or timezone"
    assert invalid_response.status_code == 400
    assert invalid_response.json()["detail"] == "Invalid timezone. Use a valid name such as Asia/Kolkata."
