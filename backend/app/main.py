from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .api.router import api_router
from .config import get_settings
from .core.exceptions import register_exception_handlers
from .core.response import success_response
from .services.anomaly_engine import anomaly_engine_service
from .services.chain_service import chain_service
from .services.init_service import initialize_app_state
from .services.mqtt_service import mqtt_ingestion_service
from .services.notification_service import notification_service
from .services.order_lifecycle_service import order_lifecycle_service
from .ws.monitor import router as monitor_ws_router
from .ws.notifications import router as notifications_ws_router

settings = get_settings()


@asynccontextmanager
async def lifespan(_: FastAPI):
    # 启动阶段完成建表、超级管理员初始化等基础设施准备。
    initialize_app_state()
    await notification_service.start()
    await chain_service.start()
    await order_lifecycle_service.start()
    await anomaly_engine_service.start()
    await mqtt_ingestion_service.start()
    try:
        yield
    finally:
        await mqtt_ingestion_service.stop()
        await anomaly_engine_service.stop()
        await order_lifecycle_service.stop()
        await chain_service.stop()
        await notification_service.stop()


app = FastAPI(
    title=settings.app_name,
    debug=settings.app_debug,
    lifespan=lifespan,
)

if settings.cors_origins_list:
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins_list,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

register_exception_handlers(app)
app.include_router(api_router)
app.include_router(monitor_ws_router)
app.include_router(notifications_ws_router)


@app.get("/")
def root() -> dict:
    return success_response(
        data={"service": "cold-chain-backend", "env": settings.app_env},
        msg="ok",
    )
