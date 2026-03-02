from fastapi import APIRouter, Header, HTTPException, Request

from app.core import publish_and_response, require_keys, validate_api_key

router = APIRouter()


@router.post("/api/irrigation")
async def backend_mqtt_publisher(request: Request, x_api_key: str = Header(None)):
    validate_api_key(x_api_key)
    payload = await request.json()

    require_keys(payload, ("DN", "FarmID"), "Missing required keys: DN or FarmID")

    if "shelf_id" in payload and "rack_id" in payload:
        payload["shelf_id"] = payload["shelf_id"]
        payload["rack_id"] = payload["rack_id"]

    return publish_and_response(payload)


@router.post("/api/fertigation")
async def backend_mqtt_fertigation(request: Request, x_api_key: str = Header(None)):
    validate_api_key(x_api_key)
    payload = await request.json()

    require_keys(payload, ("DN", "FarmID", "cmd", "eC", "pH"), "Missing required keys")

    if payload["cmd"] != "change_limits":
        raise HTTPException(status_code=400, detail="Invalid cmd. Expected: change_limits")

    required_subkeys = ("LL", "HL")

    if not all(k in payload["eC"] for k in required_subkeys):
        raise HTTPException(status_code=400, detail="Missing LL/HL inside eC")

    if not all(k in payload["pH"] for k in required_subkeys):
        raise HTTPException(status_code=400, detail="Missing LL/HL inside pH")

    payload["eC"]["LL"] = float(payload["eC"]["LL"])
    payload["eC"]["HL"] = float(payload["eC"]["HL"])
    payload["pH"]["LL"] = float(payload["pH"]["LL"])
    payload["pH"]["HL"] = float(payload["pH"]["HL"])

    return publish_and_response(payload)


@router.post("/api/estopirrigation")
async def backend_mqtt_estop_irrigation(request: Request, x_api_key: str = Header(None)):
    validate_api_key(x_api_key)
    payload = await request.json()

    require_keys(payload, ("DN", "FarmID", "DeviceID"), "Missing required keys: DN or FarmID")

    return publish_and_response(payload)


@router.post("/api/acutatorCmd")
async def backend_acutator_cmd(request: Request, x_api_key: str = Header(None)):
    validate_api_key(x_api_key)
    payload = await request.json()

    require_keys(payload, ("DN", "FarmID", "DeviceID"), "Missing required keys: DN or FarmID")

    return publish_and_response(payload)
