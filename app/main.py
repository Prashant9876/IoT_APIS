from fastapi import FastAPI
from mangum import Mangum

from app.routers.iot_api import router as iot_router
from app.routers.robot_api import router as robot_router
from app.routers.other_api import router as other_router

app = FastAPI()
app.include_router(iot_router)
app.include_router(robot_router)
app.include_router(other_router)

handler = Mangum(app, lifespan="off")
