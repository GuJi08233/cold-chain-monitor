import argparse
import json
import random
import sqlite3
import time
from dataclasses import dataclass, asdict
from datetime import datetime, timedelta
from pathlib import Path
from urllib import error, request

ROOT_DIR = Path(__file__).resolve().parents[1]
ENV_FILE = ROOT_DIR / ".env"
DB_FILE = ROOT_DIR / "cold_chain.db"


@dataclass
class SmokeArtifacts:
    run_tag: str
    username: str
    user_id: int | None = None
    device_id: str | None = None
    order_id: str | None = None
    ticket_id: int | None = None


def load_env(path: Path) -> dict[str, str]:
    data: dict[str, str] = {}
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        data[key.strip()] = value.strip().strip('"').strip("'")
    return data


def parse_json(raw: str):
    try:
        return json.loads(raw)
    except Exception:  # noqa: BLE001
        return {"raw": raw}


def payload_data(resp):
    if isinstance(resp, dict) and "data" in resp:
        return resp["data"]
    return resp


class ApiClient:
    def __init__(self, base_url: str, timeout: int = 20) -> None:
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout

    def call(
        self,
        method: str,
        path: str,
        token: str | None = None,
        payload: dict | None = None,
        expected: tuple[int, ...] = (200,),
    ) -> tuple[dict, int]:
        headers: dict[str, str] = {}
        body = None
        if payload is not None:
            headers["Content-Type"] = "application/json"
            body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        if token:
            headers["Authorization"] = f"Bearer {token}"

        req = request.Request(
            url=f"{self.base_url}{path}",
            data=body,
            headers=headers,
            method=method,
        )
        try:
            with request.urlopen(req, timeout=self.timeout) as resp:
                code = resp.getcode()
                text = resp.read().decode("utf-8", errors="ignore")
                data = parse_json(text) if text else {}
        except error.HTTPError as exc:
            code = exc.code
            text = exc.read().decode("utf-8", errors="ignore")
            data = parse_json(text)
        except Exception as exc:  # noqa: BLE001
            raise RuntimeError(f"{method} {path} 请求异常: {exc}") from exc

        if code not in expected:
            raise RuntimeError(
                f"{method} {path} 期望状态码={expected}，实际={code}，响应={data}"
            )
        return data, code


def cleanup_artifacts(artifacts: SmokeArtifacts) -> dict[str, int]:
    if not DB_FILE.exists():
        return {}

    conn = sqlite3.connect(DB_FILE)
    conn.execute("PRAGMA foreign_keys = ON")
    cur = conn.cursor()

    def in_clause(values: list) -> str:
        return "(" + ",".join(["?"] * len(values)) + ")"

    usernames = [artifacts.username]
    user_ids = []
    for row in cur.execute(
        "SELECT user_id FROM users WHERE username = ?",
        [artifacts.username],
    ).fetchall():
        user_ids.append(row[0])

    device_ids = []
    if artifacts.device_id:
        device_ids.append(artifacts.device_id)
    for row in cur.execute(
        "SELECT device_id FROM devices WHERE device_id LIKE ?",
        [f"SMKDEV{artifacts.run_tag[-6:]}%"],
    ).fetchall():
        if row[0] not in device_ids:
            device_ids.append(row[0])

    order_ids = []
    clauses = []
    params: list = []
    if user_ids:
        clauses.append(f"driver_id IN {in_clause(user_ids)}")
        params.extend(user_ids)
    if device_ids:
        clauses.append(f"device_id IN {in_clause(device_ids)}")
        params.extend(device_ids)
    clauses.append("cargo_name LIKE ?")
    params.append(f"%{artifacts.run_tag}%")
    if clauses:
        query = "SELECT order_id FROM orders WHERE " + " OR ".join(clauses)
        for row in cur.execute(query, params).fetchall():
            if row[0] not in order_ids:
                order_ids.append(row[0])
    if artifacts.order_id and artifacts.order_id not in order_ids:
        order_ids.append(artifacts.order_id)

    anomaly_ids = []
    if order_ids:
        query = f"SELECT anomaly_id FROM anomalies WHERE order_id IN {in_clause(order_ids)}"
        anomaly_ids = [r[0] for r in cur.execute(query, order_ids).fetchall()]

    ticket_ids = []
    ticket_clauses = []
    ticket_params: list = []
    if user_ids:
        ticket_clauses.append(f"submitter_id IN {in_clause(user_ids)}")
        ticket_params.extend(user_ids)
    if order_ids:
        ticket_clauses.append(f"order_id IN {in_clause(order_ids)}")
        ticket_params.extend(order_ids)
    ticket_clauses.append("reason LIKE ?")
    ticket_params.append(f"%{artifacts.run_tag}%")
    if ticket_clauses:
        query = "SELECT ticket_id FROM tickets WHERE " + " OR ".join(ticket_clauses)
        ticket_ids = [r[0] for r in cur.execute(query, ticket_params).fetchall()]
    if artifacts.ticket_id and artifacts.ticket_id not in ticket_ids:
        ticket_ids.append(artifacts.ticket_id)

    deleted = {
        "chain_records": 0,
        "alert_rules": 0,
        "anomalies": 0,
        "tickets": 0,
        "notifications": 0,
        "orders": 0,
        "devices": 0,
        "driver_profiles": 0,
        "users": 0,
    }

    try:
        conn.execute("BEGIN")

        if order_ids or anomaly_ids:
            clauses = []
            params = []
            if order_ids:
                clauses.append(f"order_id IN {in_clause(order_ids)}")
                params.extend(order_ids)
            if anomaly_ids:
                clauses.append(f"anomaly_id IN {in_clause(anomaly_ids)}")
                params.extend(anomaly_ids)
            query = "DELETE FROM chain_records WHERE " + " OR ".join(clauses)
            cur.execute(query, params)
            deleted["chain_records"] = cur.rowcount

        if order_ids:
            query = f"DELETE FROM alert_rules WHERE order_id IN {in_clause(order_ids)}"
            cur.execute(query, order_ids)
            deleted["alert_rules"] = cur.rowcount

            query = f"DELETE FROM anomalies WHERE order_id IN {in_clause(order_ids)}"
            cur.execute(query, order_ids)
            deleted["anomalies"] = cur.rowcount

            query = f"DELETE FROM orders WHERE order_id IN {in_clause(order_ids)}"
            cur.execute(query, order_ids)
            deleted["orders"] = cur.rowcount

        if ticket_ids:
            query = f"DELETE FROM tickets WHERE ticket_id IN {in_clause(ticket_ids)}"
            cur.execute(query, ticket_ids)
            deleted["tickets"] = cur.rowcount

        notif_clauses = []
        notif_params: list = []
        if user_ids:
            notif_clauses.append(f"user_id IN {in_clause(user_ids)}")
            notif_params.extend(user_ids)
        for username in usernames:
            notif_clauses.append("content LIKE ?")
            notif_params.append(f"%{username}%")
        for order_id in order_ids:
            notif_clauses.append("content LIKE ?")
            notif_params.append(f"%{order_id}%")
        for ticket_id in ticket_ids:
            notif_clauses.append("content LIKE ?")
            notif_params.append(f'%\"ticket_id\": {ticket_id}%')
            notif_clauses.append("content LIKE ?")
            notif_params.append(f'%\"ticket_id\":{ticket_id}%')
        if notif_clauses:
            query = "DELETE FROM notifications WHERE " + " OR ".join(notif_clauses)
            cur.execute(query, notif_params)
            deleted["notifications"] = cur.rowcount

        if device_ids:
            query = f"DELETE FROM devices WHERE device_id IN {in_clause(device_ids)}"
            cur.execute(query, device_ids)
            deleted["devices"] = cur.rowcount

        if user_ids:
            query = f"DELETE FROM driver_profiles WHERE driver_id IN {in_clause(user_ids)}"
            cur.execute(query, user_ids)
            deleted["driver_profiles"] = cur.rowcount

            query = f"DELETE FROM users WHERE user_id IN {in_clause(user_ids)}"
            cur.execute(query, user_ids)
            deleted["users"] = cur.rowcount

        conn.commit()
        return deleted
    except Exception:  # noqa: BLE001
        conn.rollback()
        raise
    finally:
        conn.close()


def run_flow(client: ApiClient, artifacts: SmokeArtifacts, admin_user: str, admin_pass: str) -> dict:
    checks: list[dict] = []

    def check(name: str, passed: bool, detail: str = "") -> None:
        checks.append({"name": name, "passed": passed, "detail": detail})
        print(f"[{'PASS' if passed else 'FAIL'}] {name}{' - ' + detail if detail else ''}")
        if not passed:
            raise RuntimeError(f"{name} 失败: {detail}")

    health, _ = client.call("GET", "/api/health")
    check("健康检查", payload_data(health).get("status") == "ok")

    login_admin, _ = client.call(
        "POST",
        "/api/auth/login",
        payload={"username": admin_user, "password": admin_pass},
    )
    admin_token = payload_data(login_admin)["access_token"]
    check("管理员登录", bool(admin_token))

    device_id = f"SMKDEV{artifacts.run_tag[-6:]}"
    artifacts.device_id = device_id
    client.call(
        "POST",
        "/api/devices",
        token=admin_token,
        payload={"device_id": device_id, "name": f"验收冒烟设备-{artifacts.run_tag[-4:]}"},
    )
    check("创建测试设备", True, device_id)

    register, _ = client.call(
        "POST",
        "/api/auth/register",
        payload={
            "username": artifacts.username,
            "password": "Aa123456!",
            "real_name": f"验收司机{artifacts.run_tag[-3:]}",
            "id_card": f"44010119900101{artifacts.run_tag[-4:]}",
            "phone": f"139{artifacts.run_tag[-8:]}",
            "plate_number": f"粤A{artifacts.run_tag[-5:]}",
            "vehicle_type": "冷藏车",
        },
    )
    artifacts.user_id = payload_data(register).get("user_id")
    check("司机注册", artifacts.user_id is not None, f"user_id={artifacts.user_id}")

    _, code = client.call(
        "POST",
        "/api/auth/login",
        payload={"username": artifacts.username, "password": "Aa123456!"},
        expected=(403,),
    )
    check("待审批司机不可登录", code == 403)

    pending, _ = client.call(
        "GET",
        "/api/users?role=driver&status=pending&page=1&page_size=100",
        token=admin_token,
    )
    pending_items = payload_data(pending).get("items", [])
    found = next((x for x in pending_items if x.get("username") == artifacts.username), None)
    check("司机出现在待审批列表", found is not None)
    artifacts.user_id = found["user_id"]

    client.call(
        "PATCH",
        f"/api/users/{artifacts.user_id}/approve",
        token=admin_token,
        payload={"device_id": device_id},
    )
    check("审批司机并绑定设备", True)

    login_driver, _ = client.call(
        "POST",
        "/api/auth/login",
        payload={"username": artifacts.username, "password": "Aa123456!"},
    )
    driver_token = payload_data(login_driver)["access_token"]
    check("司机登录", bool(driver_token))

    planned_local = (datetime.now() + timedelta(minutes=8)).strftime("%Y-%m-%dT%H:%M")
    create_order, _ = client.call(
        "POST",
        "/api/orders",
        token=admin_token,
        payload={
            "device_id": device_id,
            "driver_id": artifacts.user_id,
            "cargo_name": f"验收冒烟货物-{artifacts.run_tag}",
            "cargo_info": {"run_tag": artifacts.run_tag, "case": "acceptance"},
            "origin": "广州A仓",
            "destination": "深圳B仓",
            "planned_start": planned_local,
            "alert_rules": [
                {"metric": "temperature", "min_value": -2, "max_value": 8},
                {"metric": "humidity", "max_value": 85},
            ],
        },
    )
    artifacts.order_id = payload_data(create_order)["order_id"]
    check("创建运单", bool(artifacts.order_id), artifacts.order_id or "")

    detail, _ = client.call(
        "GET",
        f"/api/orders/{artifacts.order_id}",
        token=admin_token,
    )
    planned_backend = payload_data(detail).get("planned_start") or ""
    expected_prefix = planned_local.replace("T", " ")
    check("计划出发时间一致性", planned_backend.startswith(expected_prefix), planned_backend)

    notifications, _ = client.call(
        "GET",
        "/api/notifications?page=1&page_size=20",
        token=driver_token,
    )
    notif_items = payload_data(notifications).get("items", [])
    assigned = next(
        (
            n
            for n in notif_items
            if n.get("type") == "order_assigned"
            and isinstance(n.get("content"), dict)
            and n.get("content", {}).get("order_id") == artifacts.order_id
        ),
        None,
    )
    check("司机收到新运单通知", assigned is not None)

    client.call("PATCH", f"/api/orders/{artifacts.order_id}/start", token=driver_token)
    check("司机提前出发", True)

    client.call("PATCH", f"/api/orders/{artifacts.order_id}/complete", token=driver_token)
    check("司机确认到达", True)

    ticket, _ = client.call(
        "POST",
        "/api/tickets",
        token=driver_token,
        payload={
            "type": "info_change",
            "order_id": None,
            "reason": f"验收冒烟工单-{artifacts.run_tag}",
        },
    )
    artifacts.ticket_id = payload_data(ticket)["ticket_id"]
    check("司机提交工单", artifacts.ticket_id is not None, str(artifacts.ticket_id))

    client.call(
        "PATCH",
        f"/api/tickets/{artifacts.ticket_id}/approve",
        token=admin_token,
        payload={"comment": f"验收通过-{artifacts.run_tag}"},
    )
    check("管理员审批工单", True)

    notifications, _ = client.call(
        "GET",
        "/api/notifications?page=1&page_size=20",
        token=driver_token,
    )
    notif_items = payload_data(notifications).get("items", [])
    ticket_notice = next(
        (
            n
            for n in notif_items
            if n.get("type") == "ticket_result"
            and isinstance(n.get("content"), dict)
            and n.get("content", {}).get("ticket_id") == artifacts.ticket_id
        ),
        None,
    )
    check("司机收到工单审批通知", ticket_notice is not None)

    return {
        "checks": checks,
        "artifacts": asdict(artifacts),
        "planned_local_input": planned_local,
        "planned_backend_value": planned_backend,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="冷链系统全链路验收冒烟脚本")
    parser.add_argument("--base-url", default="http://127.0.0.1:8000", help="后端地址")
    parser.add_argument("--timeout", type=int, default=20, help="请求超时秒数")
    parser.add_argument(
        "--no-cleanup",
        action="store_true",
        help="执行完成后不清理测试数据（默认会清理）",
    )
    parser.add_argument(
        "--output-json",
        default="",
        help="将结果写入 JSON 文件（可选）",
    )
    args = parser.parse_args()

    if not ENV_FILE.exists():
        print(f"[FAIL] 缺少环境文件: {ENV_FILE}")
        return 1

    env = load_env(ENV_FILE)
    admin_user = env.get("SUPER_ADMIN_USERNAME", "").strip()
    admin_pass = env.get("SUPER_ADMIN_PASSWORD", "").strip()
    if not admin_user or not admin_pass:
        print("[FAIL] .env 缺少 SUPER_ADMIN_USERNAME / SUPER_ADMIN_PASSWORD")
        return 1

    run_tag = f"{int(time.time())}{random.randint(100, 999)}"
    artifacts = SmokeArtifacts(
        run_tag=run_tag,
        username=f"accept_driver_{run_tag}",
    )
    client = ApiClient(args.base_url, timeout=args.timeout)

    success = False
    result: dict = {}
    cleanup_result: dict[str, int] = {}
    error_text = ""
    try:
        result = run_flow(client, artifacts, admin_user, admin_pass)
        success = True
    except Exception as exc:  # noqa: BLE001
        error_text = str(exc)
        result = {
            "checks": [],
            "artifacts": asdict(artifacts),
            "error": error_text,
        }
        print(f"[FAIL] 冒烟执行失败: {error_text}")
    finally:
        if not args.no_cleanup:
            try:
                cleanup_result = cleanup_artifacts(artifacts)
                print(f"[CLEANUP] {cleanup_result}")
            except Exception as exc:  # noqa: BLE001
                print(f"[WARN] 清理失败: {exc}")
                if success:
                    success = False
                    error_text = f"执行成功但清理失败: {exc}"

    summary = {
        "success": success,
        "base_url": args.base_url,
        "result": result,
        "cleanup": cleanup_result,
        "error": error_text,
    }
    print("SMOKE_SUMMARY=" + json.dumps(summary, ensure_ascii=False))

    if args.output_json:
        output_path = Path(args.output_json)
        output_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"[DONE] 结果已写入: {output_path}")

    return 0 if success else 1


if __name__ == "__main__":
    raise SystemExit(main())
