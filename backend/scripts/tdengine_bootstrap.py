import base64
import json
from dataclasses import dataclass
from pathlib import Path
import sys
from urllib import error, request

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from app.config import get_settings


@dataclass
class SQLResult:
    ok: bool
    sql: str
    payload: dict


def execute_sql(sql: str) -> SQLResult:
    settings = get_settings()
    auth_token = base64.b64encode(
        f"{settings.tdengine_username}:{settings.tdengine_password}".encode("utf-8")
    ).decode("utf-8")

    req = request.Request(
        settings.tdengine_rest_url,
        data=sql.encode("utf-8"),
        method="POST",
        headers={
            "Content-Type": "text/plain; charset=utf-8",
            "Authorization": f"Basic {auth_token}",
        },
    )

    try:
        with request.urlopen(req, timeout=10) as resp:
            body = resp.read().decode("utf-8")
            payload = json.loads(body) if body else {}
            code = int(payload.get("code", 0))
            return SQLResult(ok=code == 0, sql=sql, payload=payload)
    except error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="ignore")
        try:
            payload = json.loads(body) if body else {}
        except json.JSONDecodeError:
            payload = {"error": body or str(exc)}
        return SQLResult(ok=False, sql=sql, payload=payload)
    except Exception as exc:  # noqa: BLE001
        return SQLResult(ok=False, sql=sql, payload={"error": str(exc)})


def main() -> int:
    settings = get_settings()
    statements = [
        f"CREATE DATABASE IF NOT EXISTS {settings.tdengine_db} KEEP 365",
        """
CREATE STABLE IF NOT EXISTS {db}.sensor_data (
    ts TIMESTAMP,
    temperature FLOAT,
    humidity FLOAT,
    pressure FLOAT,
    gps_lat DOUBLE,
    gps_lng DOUBLE,
    uptime INT
) TAGS (
    device_id NCHAR(64),
    order_id NCHAR(64)
)
        """.strip().format(db=settings.tdengine_db),
    ]

    print(f"[TDengine] REST endpoint: {settings.tdengine_rest_url}")
    print(f"[TDengine] Database: {settings.tdengine_db}")
    for sql in statements:
        result = execute_sql(sql)
        if result.ok:
            print(f"[OK] {sql}")
            continue

        print(f"[FAIL] {sql}")
        print(json.dumps(result.payload, ensure_ascii=False, indent=2))
        return 1

    print("[DONE] TDengine 数据库与超级表已就绪。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
