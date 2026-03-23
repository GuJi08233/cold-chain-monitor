from fastapi import APIRouter

from .anomalies import router as anomalies_router
from .auth import router as auth_router
from .chain import router as chain_router
from .config import router as config_router
from .dashboard import router as dashboard_router
from .devices import router as devices_router
from .health import router as health_router
from .monitor import router as monitor_router
from .notifications import router as notifications_router
from .orders import router as orders_router
from .tickets import router as tickets_router
from .users import router as users_router

api_router = APIRouter(prefix="/api")
api_router.include_router(health_router)
api_router.include_router(auth_router)
api_router.include_router(users_router)
api_router.include_router(devices_router)
api_router.include_router(orders_router)
api_router.include_router(monitor_router)
api_router.include_router(anomalies_router)
api_router.include_router(notifications_router)
api_router.include_router(chain_router)
api_router.include_router(tickets_router)
api_router.include_router(dashboard_router)
api_router.include_router(config_router)
