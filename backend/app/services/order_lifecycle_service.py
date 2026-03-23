import asyncio
import logging
from datetime import datetime

from sqlalchemy import select

from ..database import SessionLocal
from ..models import Order, OrderStatus

logger = logging.getLogger(__name__)


class OrderLifecycleService:
    AUTO_START_CHECK_INTERVAL_SECONDS = 5

    def __init__(self) -> None:
        self._task: asyncio.Task | None = None

    async def start(self) -> None:
        # 启动后先执行一次，避免到点运单必须等待下一轮轮询才流转。
        await asyncio.to_thread(self._auto_start_due_orders_once)
        if self._task is None or self._task.done():
            self._task = asyncio.create_task(self._auto_start_loop())

    async def stop(self) -> None:
        if self._task is None:
            return
        self._task.cancel()
        try:
            await self._task
        except asyncio.CancelledError:
            pass
        self._task = None

    async def _auto_start_loop(self) -> None:
        while True:
            await asyncio.sleep(self.AUTO_START_CHECK_INTERVAL_SECONDS)
            await asyncio.to_thread(self._auto_start_due_orders_once)

    @staticmethod
    def _auto_start_due_orders_once() -> None:
        now = datetime.now()
        with SessionLocal() as db:
            due_orders = db.scalars(
                select(Order)
                .where(
                    Order.status == OrderStatus.PENDING,
                    Order.planned_start <= now,
                )
                .order_by(Order.planned_start.asc())
                .limit(200)
            ).all()
            if not due_orders:
                return

            device_ids = {order.device_id for order in due_orders}
            active_device_ids = set(
                db.scalars(
                    select(Order.device_id)
                    .where(
                        Order.status == OrderStatus.IN_TRANSIT,
                        Order.device_id.in_(device_ids),
                    )
                    .distinct()
                ).all()
            )

            changed = 0
            for order in due_orders:
                # 同一设备同一时刻仅允许一个运输中运单，避免并发流转导致数据冲突。
                if order.device_id in active_device_ids:
                    continue
                order.status = OrderStatus.IN_TRANSIT
                if order.actual_start is None:
                    order.actual_start = now
                db.add(order)
                changed += 1
                active_device_ids.add(order.device_id)

            if changed > 0:
                db.commit()
                logger.info("Auto started %s order(s) by planned_start", changed)
            else:
                db.rollback()


order_lifecycle_service = OrderLifecycleService()
