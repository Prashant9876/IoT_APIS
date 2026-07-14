from fastapi import APIRouter, Header, Request
from datetime import datetime, timezone
from app.core import publish_and_response, require_keys, validate_api_key

router = APIRouter()


@router.post("/api/robot")
async def backend_robot_cmd(request: Request, x_api_key: str = Header(None)):
    validate_api_key(x_api_key)
    payload = await request.json()

    require_keys(payload, ("DN", "FarmID", "DeviceID"), "Missing required keys: DN or FarmID")
    # 🔹 Extract request info
    client_ip = request.client.host
    forwarded_for = request.headers.get("x-forwarded-for")
    user_agent = request.headers.get("user-agent")

    # 🔹 Add into payload (NEW)
    payload["meta"] = {
        "client_ip": client_ip or "unknown",
        "forwarded_ip": forwarded_for or "unknown",
        "user_agent": user_agent or "unknown",
        "timestamp":  datetime.now(timezone.utc).isoformat()
    }

    return publish_and_response(payload)
