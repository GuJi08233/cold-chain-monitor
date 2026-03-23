import argparse
import json
import sys
from pathlib import Path

from sqlalchemy.engine.url import make_url

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from app.config import get_settings
from app.services.init_service import initialize_app_state

import seed_system_config
import tdengine_bootstrap


def _resolve_sqlite_path(database_url: str) -> Path | None:
    try:
        url = make_url(database_url)
    except Exception:  # noqa: BLE001
        return None
    if url.get_backend_name() != "sqlite":
        return None
    db_text = str(url.database or "").strip()
    if not db_text or db_text == ":memory:":
        return None

    if db_text.startswith("/") and len(db_text) > 2 and db_text[2] == ":":
        db_text = db_text[1:]

    db_path = Path(db_text)
    if db_path.is_absolute():
        return db_path
    return (ROOT_DIR / db_path).resolve()


def _delete_sqlite_db(dry_run: bool) -> int:
    settings = get_settings()
    db_path = _resolve_sqlite_path(settings.database_url)
    if db_path is None:
        print("[SKIP] 当前 DATABASE_URL 不是本地 SQLite，跳过删除本地库。")
        return 0

    print(f"[INFO] SQLite 文件: {db_path}")
    if not db_path.exists():
        print("[OK] SQLite 文件不存在，无需删除。")
        return 0

    if dry_run:
        print("[DRY-RUN] 将删除 SQLite 文件。")
        return 0

    try:
        db_path.unlink()
        print("[OK] 已删除 SQLite 文件。")
        return 0
    except Exception as exc:  # noqa: BLE001
        print(f"[FAIL] 删除 SQLite 文件失败: {exc}")
        return 1


def _reset_tdengine(dry_run: bool) -> int:
    settings = get_settings()
    drop_sql = f"DROP DATABASE IF EXISTS {settings.tdengine_db}"
    print(f"[TDengine] REST endpoint: {settings.tdengine_rest_url}")
    print(f"[TDengine] Database: {settings.tdengine_db}")

    if dry_run:
        print(f"[DRY-RUN] 将执行: {drop_sql}")
        print("[DRY-RUN] 将执行 tdengine_bootstrap（创建数据库与超级表）")
        return 0

    result = tdengine_bootstrap.execute_sql(drop_sql)
    if not result.ok:
        print(f"[FAIL] {drop_sql}")
        print(json.dumps(result.payload, ensure_ascii=False, indent=2))
        return 1
    print(f"[OK] {drop_sql}")

    return tdengine_bootstrap.main()


def _recreate_backend_state(dry_run: bool) -> int:
    if dry_run:
        print("[DRY-RUN] 将执行 initialize_app_state（建表 + 初始化超级管理员 + 系统配置键）。")
        return 0
    try:
        initialize_app_state()
        print("[OK] 后端状态已初始化（建表/管理员/配置键）。")
        return 0
    except Exception as exc:  # noqa: BLE001
        print(f"[FAIL] 初始化后端状态失败: {exc}")
        return 1


def _seed_system_config(dry_run: bool) -> int:
    if dry_run:
        print("[DRY-RUN] 将执行 seed_system_config（同步 MQTT/TDengine/ETH 到 system_config）。")
        return 0
    return seed_system_config.main()


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="一键重建开发环境数据：SQLite + TDengine + system_config",
    )
    parser.add_argument(
        "--yes",
        action="store_true",
        help="确认执行危险操作（删除本地 SQLite、清空 TDengine 数据库）",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="仅打印将执行的步骤，不实际修改数据",
    )
    parser.add_argument(
        "--skip-local-db",
        action="store_true",
        help="跳过本地 SQLite 删除",
    )
    parser.add_argument(
        "--skip-tdengine",
        action="store_true",
        help="跳过 TDengine 重建（DROP + CREATE）",
    )
    parser.add_argument(
        "--skip-seed",
        action="store_true",
        help="跳过 system_config 同步",
    )
    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()

    if not args.yes and not args.dry_run:
        print("[ABORT] 此操作会删除开发数据。请加 --yes 明确确认。")
        print("[TIP] 可先执行 --dry-run 预览步骤。")
        return 2

    print("[STEP] 重建后端数据库状态")
    if not args.skip_local_db:
        code = _delete_sqlite_db(dry_run=args.dry_run)
        if code != 0:
            return code
    else:
        print("[SKIP] 按参数跳过本地 SQLite 删除。")

    code = _recreate_backend_state(dry_run=args.dry_run)
    if code != 0:
        return code

    print("[STEP] 重建 TDengine 数据")
    if not args.skip_tdengine:
        code = _reset_tdengine(dry_run=args.dry_run)
        if code != 0:
            return code
    else:
        print("[SKIP] 按参数跳过 TDengine 重建。")

    print("[STEP] 同步 system_config")
    if not args.skip_seed:
        code = _seed_system_config(dry_run=args.dry_run)
        if code != 0:
            return code
    else:
        print("[SKIP] 按参数跳过 system_config 同步。")

    print("[DONE] 一键重建完成。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
