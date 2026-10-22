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

    
def _connect_collection(DB_NAME: str, COLLECTION_NAME: str):
    if not app.core.MONGO_URI:
        raise RuntimeError("MONGO_URI is missing in environment")

    client = MongoClient(app.core.MONGO_URI, serverSelectionTimeoutMS=5000)
    client.admin.command("ping")
    db = client[DB_NAME]
    return client, db[COLLECTION_NAME]



def update_LCD_Schedule(payload):
    client = None

    try:
        client, collection = _connect_collection(app.core.MONGO_SCHEDULE_DB__NAME, app.core.MONGO_LIGHT_COLLECTION_NAME)

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
        client, collection = _connect_collection(app.core.MONGO_SCHEDULE_DB__NAME, app.core.MONGO_LIGHT_COLLECTION_NAME)

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
 



def update_FNC_Schedule(payload):
    client = None
    
    try:
        client, collection = _connect_collection(app.core.MONGO_SCHEDULE_DB__NAME, app.core.MONGO_FAN_COLLECTION_NAME)

        farm_id = payload.get("FarmID")
        device_ids = _normalize_device_ids(payload.get("DeviceID"))
        new_schedule = payload.get("schedule", {})
        DN = payload.get("DN", None)

        if not isinstance(new_schedule, dict) or not new_schedule:
            return {"ok": False, "status_code": 400, "detail": "schedule must be a non-empty object"}
        
        required_fields = [
            "on_duration_min",
            "off_duration_min"
        ]

        for field in required_fields:
            if field not in new_schedule:
                return {
                    "ok": False,
                    "status_code": 400,
                    "detail": f"{field} is required in schedule"
                }

            if not isinstance(new_schedule[field], (int, float)):
                return {
                    "ok": False,
                    "status_code": 400,
                    "detail": f"{field} must be a number"
                }

            if new_schedule[field] < 0:
                return {
                    "ok": False,
                    "status_code": 400,
                    "detail": f"{field} cannot be negative"
                }

        data = collection.find_one(
            {
                "farm_id": farm_id,
                "DN": DN
            },
            {
                "_id": 0
            }
        )
        if data is None:
            return {"ok": False, "status_code": 404, "detail": "Farm or not found"}

        saved_device_ids = _normalize_device_ids(data.get("device_ids", []))
        if set(device_ids) != set(saved_device_ids):
            return {
                "ok": False,
                "status_code": 409,
                "detail": "Device IDs or total shelves do not match stored LCD configuration",
            }

        update_data = {
            "schedule": {
                "on_duration_min": new_schedule["on_duration_min"],
                "off_duration_min": new_schedule["off_duration_min"]
            },
            "last_updated_at": datetime.now(
                ZoneInfo("UTC")
            ).isoformat()
        }
        result = collection.update_one(
            {
                "farm_id": farm_id,
                "DN": DN
            },
            {
                "$set": update_data
            }
        )
        if result.matched_count != 1:
            return {
                "ok": False,
                "status_code": 404,
                "detail": "FNC schedule document was not found"
            }

        return {
            "ok": True,
            "updated_fields": [
                "schedule.on_duration_min",
                "schedule.off_duration_min",
                "last_updated_at"
            ],
            "modified_count": result.modified_count
        }

    except (PyMongoError, RuntimeError) as e:
        return {
            "ok": False,
            "status_code": 503,
            "detail": f"MongoDB Error: {e}"
        }

    finally:
        if client:
            client.close()



def update_FNC_Mode(payload):
    client = None

    try:
        client, collection = _connect_collection(app.core.MONGO_SCHEDULE_DB__NAME, app.core.MONGO_FAN_COLLECTION_NAME)

        farm_id = payload.get("FarmID")
        device_ids = _normalize_device_ids(payload.get("DeviceID"))
        IncomingMode = payload.get("mode")
        DN = payload.get("DN")

        # ---------------- VALIDATION ---------------- #

        if farm_id is None:
            return {"ok": False, "status_code": 400, "detail": "FarmID is required"}

        if IncomingMode is None:
            return {"ok": False, "status_code": 400, "detail": "mode is required"}

        if DN is None:
            return {"ok": False, "status_code": 400, "detail": "DN is required"}

        # Optional: restrict supported modes
        if IncomingMode not in [0, 1]:
            return {"ok": False, "status_code": 400, "detail": "mode must be 0 or 1"}

        # ---------------- FETCH DOCUMENT ---------------- #

        data = collection.find_one(
            {
                "farm_id": farm_id,
                "DN": DN
            },
            {
                "_id": 0
            }
        )

        if data is None:
            return {"ok": False, "status_code": 404, "detail": "FNC configuration not found for this farm"}

        # ---------------- DEVICE VALIDATION ---------------- #

        saved_device_ids = _normalize_device_ids(
            data.get("device_ids", [])
        )

        if set(device_ids) != set(saved_device_ids):
            return {"ok": False, "status_code": 409, "detail": "Device IDs do not match stored FNC configuration"}

        current_mode = data.get("mode")

        # Already in requested mode
        if IncomingMode == current_mode:
            return {"ok": True, "updated_fields": [], "modified_count": 0 }

        # ---------------- UPDATE ONLY MODE ---------------- #

        update_data = {
            "mode": IncomingMode,
            "last_updated_at": datetime.now(
                ZoneInfo("UTC")
            ).isoformat()
        }

        result = collection.update_one(
            {
                "farm_id": farm_id,
                "DN": DN
            },
            {
                "$set": update_data
            }
        )

        if result.matched_count != 1:
            return {"ok": False, "status_code": 404, "detail": "FNC mode document was not found" }

        return {
            "ok": True,
            "updated_fields": [
                "mode",
                "last_updated_at"
            ],
            "modified_count": result.modified_count
        }

    except (PyMongoError, RuntimeError) as e:
        return {"ok": False, "status_code": 503, "detail": f"MongoDB Error: {e}"}

    finally:
        if client:
            client.close()