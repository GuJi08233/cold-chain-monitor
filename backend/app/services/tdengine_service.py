import base64
import json
import re
from dataclasses import dataclass
from datetime import datetime
from urllib import error, request

from ..config import get_settings


@dataclass
class TdengineResult:
    ok: bool
    payload: dict


class TdengineService:
    def __init__(self) -> None:
        self.settings = get_settings()
        auth_raw = f"{self.settings.tdengine_username}:{self.settings.tdengine_password}"
        self._auth = base64.b64encode(auth_raw.encode("utf-8")).decode("utf-8")
        self._subtable_cache: set[str] = set()

    def execute_sql(self, sql: str) -> TdengineResult:
        req = request.Request(
            self.settings.tdengine_rest_url,
            data=sql.encode("utf-8"),
            method="POST",
            headers={
                "Content-Type": "text/plain; charset=utf-8",
                "Authorization": f"Basic {self._auth}",
            },
        )
        try:
            with request.urlopen(req, timeout=8) as resp:
                body = resp.read().decode("utf-8")
                payload = json.loads(body) if body else {}
                return TdengineResult(ok=int(payload.get("code", 0)) == 0, payload=payload)
        except error.HTTPError as exc:
            body = exc.read().decode("utf-8", errors="ignore")
            try:
                payload = json.loads(body) if body else {}
            except json.JSONDecodeError:
                payload = {"error": body or str(exc)}
            return TdengineResult(ok=False, payload=payload)
        except Exception as exc:  # noqa: BLE001
            return TdengineResult(ok=False, payload={"error": str(exc)})

    @staticmethod
    def payload_to_rows(payload: dict) -> list[dict]:
        columns = [col[0] for col in payload.get("column_meta", [])]
        data = payload.get("data", [])
        return [dict(zip(columns, row, strict=False)) for row in data]

    @staticmethod
    def is_table_not_exists(payload: dict) -> bool:
        code = payload.get("code")
        if code == 9731:
            return True
        desc = str(payload.get("desc") or payload.get("error") or "").lower()
        return "table does not exist" in desc

    @staticmethod
    def _sanitize_identifier(raw_value: str) -> str:
        cleaned = re.sub(r"[^0-9A-Za-z_]", "_", raw_value)
        if not cleaned:
            cleaned = "t"
        if cleaned[0].isdigit():
            cleaned = f"t_{cleaned}"
        return cleaned[:180]

    @staticmethod
    def _escape_text(raw_value: str) -> str:
        return raw_value.replace("\\", "\\\\").replace("'", "\\'")

    def resolve_subtable_name(self, device_id: str, order_id: str) -> str:
        return self._sanitize_identifier(f"{device_id}_{order_id}")

    def ensure_subtable(self, device_id: str, order_id: str) -> tuple[bool, str]:
        subtable = self.resolve_subtable_name(device_id, order_id)
        if subtable in self._subtable_cache:
            return True, subtable

        sql = (
            f"CREATE TABLE IF NOT EXISTS {self.settings.tdengine_db}.{subtable} "
            f"USING {self.settings.tdengine_db}.sensor_data "
            f"TAGS ('{self._escape_text(device_id)}', '{self._escape_text(order_id)}')"
        )
        result = self.execute_sql(sql)
        if result.ok:
            self._subtable_cache.add(subtable)
            return True, subtable
        return False, subtable

    def insert_sensor_data(
        self,
        device_id: str,
        order_id: str,
        ts: datetime,
        temperature: float | None,
        humidity: float | None,
        pressure: float | None,
        gps_lat: float | None,
        gps_lng: float | None,
        uptime: int | None,
    ) -> TdengineResult:
        ok, subtable = self.ensure_subtable(device_id, order_id)
        if not ok:
            return TdengineResult(ok=False, payload={"error": "创建子表失败", "subtable": subtable})

        def to_sql_value(value):
            return "NULL" if value is None else str(value)

        ts_text = ts.strftime("%Y-%m-%d %H:%M:%S")
        sql = (
            f"INSERT INTO {self.settings.tdengine_db}.{subtable} "
            f"(ts, temperature, humidity, pressure, gps_lat, gps_lng, uptime) VALUES "
            f"('{ts_text}', {to_sql_value(temperature)}, {to_sql_value(humidity)}, "
            f"{to_sql_value(pressure)}, {to_sql_value(gps_lat)}, {to_sql_value(gps_lng)}, "
            f"{to_sql_value(uptime)})"
        )
        return self.execute_sql(sql)

    def query_latest_sensor(self, device_id: str, order_id: str) -> TdengineResult:
        subtable = self.resolve_subtable_name(device_id, order_id)
        sql = (
            f"SELECT ts, temperature, humidity, pressure, gps_lat, gps_lng, uptime "
            f"FROM {self.settings.tdengine_db}.{subtable} ORDER BY ts DESC LIMIT 1"
        )
        return self.execute_sql(sql)

    def query_sensor_raw(
        self,
        device_id: str,
        order_id: str,
        start_time: datetime,
        end_time: datetime,
        limit: int = 2000,
    ) -> TdengineResult:
        subtable = self.resolve_subtable_name(device_id, order_id)
        start_text = start_time.strftime("%Y-%m-%d %H:%M:%S")
        end_text = end_time.strftime("%Y-%m-%d %H:%M:%S")
        sql = (
            f"SELECT ts, temperature, humidity, pressure, gps_lat, gps_lng, uptime "
            f"FROM {self.settings.tdengine_db}.{subtable} "
            f"WHERE ts >= '{start_text}' AND ts <= '{end_text}' "
            f"ORDER BY ts LIMIT {limit}"
        )
        return self.execute_sql(sql)

    def query_sensor_batch(
        self,
        device_id: str,
        order_id: str,
        offset: int,
        limit: int,
    ) -> TdengineResult:
        subtable = self.resolve_subtable_name(device_id, order_id)
        sql = (
            f"SELECT ts, temperature, humidity, pressure, gps_lat, gps_lng, uptime "
            f"FROM {self.settings.tdengine_db}.{subtable} "
            f"ORDER BY ts LIMIT {limit} OFFSET {offset}"
        )
        return self.execute_sql(sql)

    def query_sensor_after_ts(
        self,
        device_id: str,
        order_id: str,
        cursor_ts: datetime | None,
        offset: int,
        limit: int,
    ) -> TdengineResult:
        subtable = self.resolve_subtable_name(device_id, order_id)
        where_text = ""
        if cursor_ts is not None:
            where_text = f"WHERE ts >= '{cursor_ts.strftime('%Y-%m-%d %H:%M:%S')}' "
        sql = (
            f"SELECT ts, temperature, humidity, pressure, gps_lat, gps_lng, uptime "
            f"FROM {self.settings.tdengine_db}.{subtable} "
            f"{where_text}"
            f"ORDER BY ts LIMIT {limit} OFFSET {offset}"
        )
        return self.execute_sql(sql)

    def query_sensor_agg(
        self,
        device_id: str,
        order_id: str,
        start_time: datetime,
        end_time: datetime,
        interval: str,
        limit: int = 2000,
    ) -> TdengineResult:
        subtable = self.resolve_subtable_name(device_id, order_id)
        start_text = start_time.strftime("%Y-%m-%d %H:%M:%S")
        end_text = end_time.strftime("%Y-%m-%d %H:%M:%S")
        sql = (
            "SELECT _wstart AS ts, "
            "AVG(temperature) AS temperature_avg, MIN(temperature) AS temperature_min, MAX(temperature) AS temperature_max, "
            "AVG(humidity) AS humidity_avg, MIN(humidity) AS humidity_min, MAX(humidity) AS humidity_max, "
            "AVG(pressure) AS pressure_avg, MIN(pressure) AS pressure_min, MAX(pressure) AS pressure_max "
            f"FROM {self.settings.tdengine_db}.{subtable} "
            f"WHERE ts >= '{start_text}' AND ts <= '{end_text}' "
            f"INTERVAL({interval}) "
            "ORDER BY ts "
            f"LIMIT {limit}"
        )
        return self.execute_sql(sql)

    def query_track(
        self,
        device_id: str,
        order_id: str,
        start_time: datetime | None = None,
        end_time: datetime | None = None,
        limit: int = 5000,
    ) -> TdengineResult:
        subtable = self.resolve_subtable_name(device_id, order_id)
        where = ["gps_lat IS NOT NULL", "gps_lng IS NOT NULL"]
        if start_time is not None:
            where.append(f"ts >= '{start_time.strftime('%Y-%m-%d %H:%M:%S')}'")
        if end_time is not None:
            where.append(f"ts <= '{end_time.strftime('%Y-%m-%d %H:%M:%S')}'")
        where_text = " AND ".join(where)
        sql = (
            f"SELECT ts, gps_lat, gps_lng FROM {self.settings.tdengine_db}.{subtable} "
            f"WHERE {where_text} ORDER BY ts LIMIT {limit}"
        )
        return self.execute_sql(sql)


tdengine_service = TdengineService()
