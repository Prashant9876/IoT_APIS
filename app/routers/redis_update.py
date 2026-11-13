from starlette.concurrency import run_in_threadpool
from fastapi import APIRouter, Header, HTTPException, Request

from app.core import is_valid_timezone, require_keys, validate_api_key
from app.redis import add_farm_to_redis

router = APIRouter()

@router.post("/api/add_timezone")
async def add_timezone_in_redis(request: Request, x_api_key: str = Header(None)):
    validate_api_key(x_api_key)
    payload = await request.json()

    require_keys(payload, ("farm_id", "timezone"), "Missing required keys: farm_id or timezone")
    is_valid_timezone(payload["timezone"], "Invalid timezone. Use a valid name such as Asia/Kolkata.")

    result = await run_in_threadpool(
        add_farm_to_redis,
        payload["farm_id"],
        payload["timezone"],
    )

    if not result["success"]:
        raise HTTPException(
            status_code=500,
            detail=result["message"],
        )

    return {
        "message": result["message"],
        "action": result["action"],
    }
