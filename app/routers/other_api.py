from fastapi import APIRouter

from app.core import mqtt_client

router = APIRouter()


@router.get("/health")
async def health():
    status = "connected" if mqtt_client.connected else "disconnected"
    return {"mqtt_status": status}
