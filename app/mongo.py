from datetime import datetime
from typing import Any

import app.core
from pymongo import MongoClient
from pymongo.errors import PyMongoError
from zoneinfo import ZoneInfo


def _normalize_device_ids(device_ids: Any) -> list[str]:
    if isinstance(device_ids, list):
        return [str(device_id) for device_id in device_ids]
    if device_ids is None:
        return []
    return [str(device_ids)]


def _connect_collection():
    if not app.core.MONGO_URI:
        raise RuntimeError("MONGO_URI is missing in environment")

    client = MongoClient(app.core.MONGO_URI, serverSelectionTimeoutMS=5000)
    client.admin.command("ping")
    db = client[app.core.MONGO_DB_NAME]
    return client, db[app.core.MONGO_COLLECTION_NAME]



def update_LCD_Schedule(payload):
    client = None

    try:
        client, collection = _connect_collection()

        farm_id = payload.get("FarmID")
        rack_id = payload.get("rack_id")
        device_ids = _normalize_device_ids(payload.get("DeviceID"))
        total_shelf = payload.get("total_shelves", 0)
        new_schedule = payload.get("schedule", {})

        if not isinstance(new_schedule, dict) or not new_schedule:
            return {"ok": False, "status_code": 400, "detail": "schedule must be a non-empty object"}

        data = collection.find_one(
            {
                "farm_id": farm_id,
                "rack_id": rack_id
            },
            {
                "_id": 0
            }
        )
        if data is None:
            return {"ok": False, "status_code": 404, "detail": "Farm or rack not found"}

        saved_device_ids = _normalize_device_ids(data.get("device_ids", []))
        total_shelves = data.get("total_shelves", 0)
        if set(device_ids) != set(saved_device_ids) or total_shelves != total_shelf:
            return {
                "ok": False,
                "status_code": 409,
                "detail": "Device IDs or total shelves do not match stored LCD configuration",
            }

        update_data = {}
        for light, timing in new_schedule.items():
            if not isinstance(light, str) or not light.startswith("L"):
                continue
            try:
                light_number = int(light[1:])
            except ValueError:
                continue
            if 1 <= light_number <= total_shelves:
                update_data[f"schedule.{light}"] = timing

        if not update_data:
            return {
                "ok": False,
                "status_code": 400,
                "detail": "No valid schedule entries found for the configured shelves",
            }

        update_data["last_updated_at"] = datetime.now(ZoneInfo("UTC")).isoformat()
        result = collection.update_one(
            {
                "farm_id": farm_id,
                "rack_id": rack_id
            },
            {
                "$set": update_data
            }
        )
        if result.matched_count != 1:
            return {"ok": False, "status_code": 404, "detail": "LCD schedule document was not found"}

        return {
            "ok": True,
            "updated_fields": sorted(update_data.keys()),
            "modified_count": result.modified_count,
        }

    except (PyMongoError, RuntimeError) as e:
        return {
            "ok": False,
            "status_code": 503,
            "detail": f"MongoDB Error: {e}",
        }

    finally:
        if client:
            client.close()



def update_LCD_Mode(payload):
    client = None

    try:
        client, collection = _connect_collection()

        farm_id = payload.get("FarmID")
        rack_id = payload.get("rack_id")
        device_ids = _normalize_device_ids(payload.get("DeviceID"))
        total_shelf = payload.get("total_shelves", 0)
        IncomingMode = payload.get("mode", None)

        if IncomingMode is None:
            return {"ok": False, "status_code": 400, "detail": "mode is required for changemode"}

        data = collection.find_one(
            {
                "farm_id": farm_id,
                "rack_id": rack_id
            },
            {
                "_id": 0
            }
        )
        if data is None:
            return {"ok": False, "status_code": 404, "detail": "Farm or rack not found"}

        saved_device_ids = _normalize_device_ids(data.get("device_ids", []))
        total_shelves = data.get("total_shelves", 0)
        mode = data.get("mode", None)
        if set(device_ids) != set(saved_device_ids) or total_shelves != total_shelf:
            return {
                "ok": False,
                "status_code": 409,
                "detail": "Device IDs or total shelves do not match stored LCD configuration",
            }

        if IncomingMode == mode:
            return {
                "ok": True,
                "updated_fields": [],
                "modified_count": 0,
            }

        result = collection.update_one(
            {
                "farm_id": farm_id,
                "rack_id": rack_id
            },
            {
                "$set": {"mode": IncomingMode, "last_updated_at": datetime.now(ZoneInfo("UTC")).isoformat()}
            }
        )
        if result.matched_count != 1:
            return {"ok": False, "status_code": 404, "detail": "LCD mode document was not found"}

        return {
            "ok": True,
            "updated_fields": ["mode", "last_updated_at"],
            "modified_count": result.modified_count,
        }

    except (PyMongoError, RuntimeError) as e:
        return {
            "ok": False,
            "status_code": 503,
            "detail": f"MongoDB Error: {e}",
        }

    finally:
        if client:
            client.close()
 
