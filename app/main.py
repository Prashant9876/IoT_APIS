import os

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from mangum import Mangum

from app.routers.iot_api import router as iot_router
from app.routers.robot_api import router as robot_router
from app.routers.other_api import router as other_router
from app.routers.certificate_api import router as certificate_router

app = FastAPI()

allowed_origins = os.getenv(
    "CORS_ALLOW_ORIGINS",
    ",".join(
        [
            "https://innofarms.ai",
            "https://www.innofarms.ai",
            "http://localhost:3000",
            "http://127.0.0.1:3000",
            "http://localhost:5173",
            "http://127.0.0.1:5173",
        ]
    ),
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
app.include_router(certificate_router)

handler = Mangum(app, lifespan="off")
