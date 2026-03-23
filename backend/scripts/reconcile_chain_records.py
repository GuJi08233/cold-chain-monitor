from __future__ import annotations

import argparse
import asyncio
from dataclasses import dataclass
from pathlib import Path
import sys

from sqlalchemy import select

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from app.database import SessionLocal
from app.models import ChainRecord, ChainRecordStatus, ChainRecordType
from app.services.chain_service import chain_service


@dataclass
class FailedRecord:
    record_id: int
    record_type: ChainRecordType
    anomaly_id: int | None


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="补偿失败的上链记录")
    parser.add_argument(
        "--record-id",
        type=int,
        default=None,
        help="仅补偿指定 record_id，不传则补偿全部 failed 记录",
    )
    parser.add_argument(
        "--timeout",
        type=int,
        default=120,
        help="补偿等待超时秒数（默认 120）",
    )
    return parser.parse_args()


def load_failed_records(target_record_id: int | None = None) -> list[FailedRecord]:
    with SessionLocal() as db:
        stmt = select(ChainRecord).where(ChainRecord.status == ChainRecordStatus.FAILED)
        if target_record_id is not None:
            stmt = stmt.where(ChainRecord.record_id == target_record_id)
        rows = db.scalars(stmt.order_by(ChainRecord.record_id.asc())).all()
        return [
            FailedRecord(
                record_id=row.record_id,
                record_type=row.type,
                anomaly_id=row.anomaly_id,
            )
            for row in rows
        ]


def get_record_status(record_id: int) -> ChainRecordStatus | None:
    with SessionLocal() as db:
        row = db.get(ChainRecord, record_id)
        if row is None:
            return None
        return row.status


def has_confirmed_start(anomaly_id: int) -> bool:
    with SessionLocal() as db:
        record_id = db.scalar(
            select(ChainRecord.record_id)
            .where(
                ChainRecord.type == ChainRecordType.ANOMALY_START,
                ChainRecord.anomaly_id == anomaly_id,
                ChainRecord.status == ChainRecordStatus.CONFIRMED,
            )
            .limit(1)
        )
        return record_id is not None


async def wait_records_finished(record_ids: list[int], timeout: int) -> bool:
    if not record_ids:
        return True
    loop = asyncio.get_running_loop()
    deadline = loop.time() + timeout
    while loop.time() < deadline:
        all_done = True
        for record_id in record_ids:
            status = get_record_status(record_id)
            if status == ChainRecordStatus.PENDING:
                all_done = False
                break
        if all_done:
            return True
        await asyncio.sleep(1.5)
    return False


async def reconcile_once(target_record_id: int | None, timeout: int) -> int:
    failed_records = load_failed_records(target_record_id)
    if not failed_records:
        print("[INFO] 没有需要补偿的 failed 记录")
        return 0

    await chain_service.start()
    try:
        created_start_record_ids: list[int] = []
        for item in failed_records:
            if item.record_type != ChainRecordType.ANOMALY_END or item.anomaly_id is None:
                continue
            if has_confirmed_start(item.anomaly_id):
                continue
            start_record_id = chain_service.submit_anomaly_start(item.anomaly_id)
            if start_record_id is not None:
                created_start_record_ids.append(start_record_id)
                print(
                    f"[INFO] anomaly_id={item.anomaly_id} 创建补偿 start 记录: {start_record_id}"
                )

        if created_start_record_ids:
            ok = await wait_records_finished(created_start_record_ids, timeout=timeout)
            if not ok:
                print("[WARN] 等待 anomaly_start 补偿超时，继续执行 retry")

        for item in failed_records:
            try:
                chain_service.retry_record(item.record_id)
                print(f"[INFO] 触发重试 record_id={item.record_id}")
            except Exception as exc:  # noqa: BLE001
                print(f"[FAIL] record_id={item.record_id} 重试提交失败: {exc}")

        target_ids = [item.record_id for item in failed_records]
        await wait_records_finished(target_ids, timeout=timeout)

        unresolved = 0
        for record_id in target_ids:
            status = get_record_status(record_id)
            print(f"[RESULT] record_id={record_id} status={status}")
            if status != ChainRecordStatus.CONFIRMED:
                unresolved += 1
        return unresolved
    finally:
        await chain_service.stop()


async def main_async() -> int:
    args = parse_args()
    unresolved = await reconcile_once(args.record_id, args.timeout)
    if unresolved > 0:
        print(f"[DONE] 补偿结束，仍有未恢复记录: {unresolved}")
        return 1
    print("[DONE] 补偿结束，failed 记录已恢复")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main_async()))
