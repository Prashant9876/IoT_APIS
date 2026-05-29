from fastapi import APIRouter, Header, HTTPException, Request
from datetime import datetime, timezone
from app.core import publish_and_response, require_keys, validate_api_key

router = APIRouter()

@router.post("/api/irrigation")
async def backend_mqtt_publisher(request: Request, x_api_key: str = Header(None)):
    validate_api_key(x_api_key)
    payload = await request.json()

    require_keys(payload, ("DN", "FarmID", "DeviceID"), "Missing required keys: DN/FarmID or DeviceID")

    if "shelf_id" in payload and "rack_id" in payload:
        payload["shelf_id"] = payload["shelf_id"]
        payload["rack_id"] = payload["rack_id"]

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


@router.post("/api/fertigation")
async def backend_mqtt_fertigation(request: Request, x_api_key: str = Header(None)):
    validate_api_key(x_api_key)
    payload = await request.json()

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

    require_keys(payload, ("DN", "FarmID", "cmd", "DeviceID"), "Missing required keys")

    if payload["cmd"] == "change_limits" :
        required_subkeys = ("LL", "HL")
        if not all(k in payload["eC"] for k in required_subkeys):
            raise HTTPException(status_code=400, detail="Missing LL/HL inside eC")

        if not all(k in payload["pH"] for k in required_subkeys):
            raise HTTPException(status_code=400, detail="Missing LL/HL inside pH")
        if payload["FarmID"] == "120":
            payload["DeviceID"] = "IFFNC1190000001"
        
        payload["eC"]["LL"] = float(payload["eC"]["LL"])
        payload["eC"]["HL"] = float(payload["eC"]["HL"])
        payload["pH"]["LL"] = float(payload["pH"]["LL"])
        payload["pH"]["HL"] = float(payload["pH"]["HL"])

        return publish_and_response(payload)
    
    elif payload["cmd"] == "change_calibration":

        # Required keys for calibration
        require_keys(payload, ("calibrationWaterliter", "pH", "eC"),
                     "Missing calibration fields")

        # Validate sub-keys
        required_subkeys = ("up", "dn")

        if not all(k in payload["pH"] for k in required_subkeys):
            raise HTTPException(status_code=400, detail="Missing up/dn inside pH")

        if not all(k in payload["eC"] for k in required_subkeys):
            raise HTTPException(status_code=400, detail="Missing up/dn inside eC")

        try:
            # Convert to proper types
            payload["calibrationWaterliter"] = float(payload["calibrationWaterliter"])

            payload["pH"]["up"] = float(payload["pH"]["up"])
            payload["pH"]["dn"] = float(payload["pH"]["dn"])

            payload["eC"]["up"] = float(payload["eC"]["up"])
            payload["eC"]["dn"] = float(payload["eC"]["dn"])

        except ValueError:
            raise HTTPException(status_code=400, detail="Invalid numeric values in calibration payload")

        return publish_and_response(payload)
    elif payload["cmd"] == "change_Mode":
        require_keys(payload, ( "pH", "eC"),"Missing calibration fields")
        try:
        # Convert to numeric (int or float based on your use case)
            payload["pH"] = int(payload["pH"])
            payload["eC"] = int(payload["eC"])

        except ValueError:
            raise HTTPException(status_code=400, detail="Invalid numeric values in mode payload")

        return publish_and_response(payload)

    else:
        raise HTTPException(status_code=400, detail="Invalid cmd. Expected: change_limits or change_calibration")




@router.post("/api/estopirrigation")
async def backend_mqtt_estop_irrigation(request: Request, x_api_key: str = Header(None)):
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


@router.post("/api/acutatorCmd")
async def backend_acutator_cmd(request: Request, x_api_key: str = Header(None)):
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
