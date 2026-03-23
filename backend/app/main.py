from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.staticfiles import StaticFiles

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
FRONTEND_DIST_DIR = Path(__file__).resolve().parent / "static"
FRONTEND_INDEX_FILE = FRONTEND_DIST_DIR / "index.html"
SPA_EXCLUDED_PREFIXES = ("api", "ws", "docs", "redoc", "openapi.json")


class SPAStaticFiles(StaticFiles):
    async def get_response(self, path: str, scope):
        try:
            response = await super().get_response(path, scope)
        except StarletteHTTPException as exc:
            if exc.status_code != 404 or not self._should_fallback(path):
                raise
            return await super().get_response("index.html", scope)

        if response.status_code == 404 and self._should_fallback(path):
            return await super().get_response("index.html", scope)
        return response

    @staticmethod
    def _should_fallback(path: str) -> bool:
        if not FRONTEND_INDEX_FILE.exists():
            return False
        normalized = path.strip("/")
        if not normalized:
            return True
        if normalized in SPA_EXCLUDED_PREFIXES:
            return False
        if any(normalized.startswith(f"{prefix}/") for prefix in SPA_EXCLUDED_PREFIXES):
            return False
        return "." not in Path(normalized).name


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
def root():
    if FRONTEND_INDEX_FILE.exists():
        return FileResponse(FRONTEND_INDEX_FILE)
    return success_response(
        data={"service": "cold-chain-backend", "env": settings.app_env},
        msg="ok",
    )


if FRONTEND_DIST_DIR.exists():
    app.mount("/", SPAStaticFiles(directory=FRONTEND_DIST_DIR, html=True), name="frontend")
