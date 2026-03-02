from fastapi import APIRouter, Header, Request

from app.core import publish_and_response, require_keys, validate_api_key

router = APIRouter()


@router.post("/api/robot")
async def backend_robot_cmd(request: Request, x_api_key: str = Header(None)):
    validate_api_key(x_api_key)
    payload = await request.json()

    require_keys(payload, ("DN", "FarmID", "DeviceID"), "Missing required keys: DN or FarmID")

    return publish_and_response(payload)
