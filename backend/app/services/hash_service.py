import hashlib
import json
from datetime import datetime

from ..core.time_utils import normalize_app_datetime, parse_app_datetime
from .tdengine_service import tdengine_service


class HashService:
    @staticmethod
    def _normalize_ts(raw_ts) -> str:
        if isinstance(raw_ts, datetime):
            return normalize_app_datetime(raw_ts).strftime("%Y-%m-%d %H:%M:%S.%f")[:23]

        text = str(raw_ts)
        dt = parse_app_datetime(text)
        if dt is not None:
            return dt.strftime("%Y-%m-%d %H:%M:%S.%f")[:23]
        return text

    @staticmethod
    def _normalize_value(value, precision: int):
        if value is None:
            return "null"
        try:
            return round(float(value), precision)
        except (TypeError, ValueError):
            return "null"

    @staticmethod
    def _normalize_uptime(value):
        if value is None:
            return "null"
        try:
            return int(value)
        except (TypeError, ValueError):
            return "null"

    @staticmethod
    def _parse_ts_to_datetime(raw_ts) -> datetime | None:
        if isinstance(raw_ts, datetime):
            return normalize_app_datetime(raw_ts)
        return parse_app_datetime(str(raw_ts))

    def normalize_record(self, record: dict) -> dict:
        return {
            "gps_lat": self._normalize_value(record.get("gps_lat"), 6),
            "gps_lng": self._normalize_value(record.get("gps_lng"), 6),
            "humidity": self._normalize_value(record.get("humidity"), 2),
            "pressure": self._normalize_value(record.get("pressure"), 2),
            "temperature": self._normalize_value(record.get("temperature"), 2),
            "ts": self._normalize_ts(record.get("ts")),
            "uptime": self._normalize_uptime(record.get("uptime")),
        }

    def compute_hash_from_records(self, records: list[dict]) -> str:
        normalized = [self.normalize_record(row) for row in records]
        text = json.dumps(normalized, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(text.encode("utf-8")).hexdigest()

    def compute_order_hash_streaming(
        self,
        device_id: str,
        order_id: str,
        batch_size: int = 5000,
    ) -> str:
        hasher = hashlib.sha256()
        hasher.update(b"[")
        first = True
        cursor_ts: datetime | None = None
        cursor_ts_text = ""
        cursor_offset = 0

        while True:
            result = tdengine_service.query_sensor_after_ts(
                device_id=device_id,
                order_id=order_id,
                cursor_ts=cursor_ts,
                offset=cursor_offset,
                limit=batch_size,
            )
            if not result.ok:
                if tdengine_service.is_table_not_exists(result.payload):
                    break
                raise RuntimeError(f"TDengine 查询失败: {result.payload}")
            rows = tdengine_service.payload_to_rows(result.payload)
            if not rows:
                break

            for row in rows:
                normalized = self.normalize_record(row)
                chunk = json.dumps(
                    normalized, ensure_ascii=False, sort_keys=True, separators=(",", ":")
                )
                if not first:
                    hasher.update(b",")
                hasher.update(chunk.encode("utf-8"))
                first = False

            last_ts_text = self._normalize_ts(rows[-1].get("ts"))
            tail_same_count = 0
            for row in reversed(rows):
                if self._normalize_ts(row.get("ts")) == last_ts_text:
                    tail_same_count += 1
                else:
                    break

            if cursor_ts is not None and last_ts_text == cursor_ts_text:
                cursor_offset += len(rows)
            else:
                parsed_cursor_ts = self._parse_ts_to_datetime(rows[-1].get("ts"))
                if parsed_cursor_ts is None:
                    raise RuntimeError("无法解析传感器时间戳，哈希计算中断")
                cursor_ts = parsed_cursor_ts
                cursor_ts_text = last_ts_text
                cursor_offset = tail_same_count

        hasher.update(b"]")
        return hasher.hexdigest()


hash_service = HashService()
