import os

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from mangum import Mangum

from app.routers.iot_api import router as iot_router
from app.routers.robot_api import router as robot_router
from app.routers.other_api import router as other_router

app = FastAPI()

allowed_origins = os.getenv(
    "CORS_ALLOW_ORIGINS",
    "https://innofarms.ai,https://www.innofarms.ai",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[origin.strip() for origin in allowed_origins.split(",") if origin.strip()],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(iot_router)
app.include_router(robot_router)
app.include_router(other_router)

handler = Mangum(app, lifespan="off")
