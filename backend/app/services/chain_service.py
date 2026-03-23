import asyncio
import hashlib
import json
import logging
import threading
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from importlib import resources

from sqlalchemy import select

from ..config import get_settings
from ..database import SessionLocal
from ..models import (
    Anomaly,
    ChainRecord,
    ChainRecordStatus,
    ChainRecordType,
    DriverProfile,
    Order,
    User,
)
from .crypto_service import crypto_service
from .system_config_service import system_config_service

logger = logging.getLogger(__name__)


class ChainServiceError(RuntimeError):
    pass


class ChainConfigError(ChainServiceError):
    pass


class ChainWriteError(ChainServiceError):
    pass


class ChainRetryLater(ChainServiceError):
    pass


@dataclass
class ChainConfig:
    rpc_url: str
    private_key: str
    contract_address: str


@dataclass
class ChainTxResult:
    tx_hash: str
    block_number: int | None
    chain_anomaly_id: int | None = None
    data_hash_mode: str | None = None


def _enum_value(value) -> str:
    return value.value if hasattr(value, "value") else str(value)


def _to_unix_seconds(value: datetime) -> int:
    return int(value.replace(tzinfo=timezone.utc).timestamp())


def _safe_parse_json(raw_value: str) -> dict:
    try:
        data = json.loads(raw_value)
        return data if isinstance(data, dict) else {}
    except Exception:  # noqa: BLE001
        return {}


def _stable_payload_text(payload: dict) -> str:
    return json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _payload_hash(payload: dict) -> str:
    return hashlib.sha256(_stable_payload_text(payload).encode("utf-8")).hexdigest()


def _sha256_hex(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _normalize_secret(value: str | None) -> str:
    text = (value or "").strip()
    if len(text) >= 2 and text[0] == text[-1] and text[0] in {"'", '"'}:
        text = text[1:-1].strip()
    return text


def _normalize_hash_hex(value: str) -> str:
    text = value.strip().lower()
    if text.startswith("0x"):
        text = text[2:]
    if len(text) != 64:
        raise ChainWriteError("data_hash 必须是 64 位 hex")
    int(text, 16)
    return text


def _bytes32_to_hex_text(value) -> str:
    if value is None:
        return ""
    if isinstance(value, (bytes, bytearray)):
        raw = bytes(value).hex()
    else:
        raw = str(value).strip().lower()
        if raw.startswith("0x"):
            raw = raw[2:]
    if len(raw) < 64:
        raw = raw.rjust(64, "0")
    if len(raw) > 64:
        raw = raw[-64:]
    return raw


def _clear_retry_metadata(payload: dict) -> dict:
    payload.pop("last_error", None)
    payload.pop("last_error_at", None)
    return payload


class ChainService:
    BUNDLED_ABI_PACKAGE = "app.contracts"
    BUNDLED_ABI_FILE = "cold_chain_monitor_v3_abi.json"
    TX_RECEIPT_TIMEOUT_SECONDS = 180

    def __init__(self) -> None:
        self._loop: asyncio.AbstractEventLoop | None = None
        self._worker_task: asyncio.Task | None = None
        self._queue: asyncio.Queue[int] | None = None
        self._abi_cache: list | None = None
        self._lock = threading.RLock()

    async def start(self) -> None:
        self._loop = asyncio.get_running_loop()
        self._queue = asyncio.Queue()
        if self._worker_task is None or self._worker_task.done():
            self._worker_task = asyncio.create_task(self._worker_loop())
        pending_ids = await asyncio.to_thread(self._load_pending_record_ids)
        for record_id in pending_ids:
            self._enqueue_record(record_id)

    async def stop(self) -> None:
        if self._worker_task is not None:
            self._worker_task.cancel()
            try:
                await self._worker_task
            except asyncio.CancelledError:
                pass
            self._worker_task = None
        self._queue = None
        self._loop = None

    def submit_order_hash(self, order_id: str, data_hash: str | None) -> int | None:
        if not data_hash:
            return None
        payload = {"order_id": order_id, "data_hash": data_hash}
        record_id = self._create_record(
            record_type=ChainRecordType.ORDER_HASH,
            order_id=order_id,
            anomaly_id=None,
            payload=payload,
            data_hash=data_hash,
        )
        self._enqueue_record(record_id)
        return record_id

    def submit_anomaly_start(self, anomaly_id: int) -> int | None:
        with SessionLocal() as db:
            anomaly = db.get(Anomaly, anomaly_id)
            if anomaly is None:
                return None
            try:
                payload = self._build_anomaly_start_payload(db, anomaly)
            except Exception as exc:  # noqa: BLE001
                payload = {
                    "order_id": anomaly.order_id,
                    "anomaly_id": anomaly.anomaly_id,
                    "anomaly_type": _enum_value(anomaly.metric),
                    "trigger_value_raw": float(anomaly.trigger_value),
                    "trigger_value_scaled": self._scale_metric(anomaly.trigger_value),
                    "start_time": _to_unix_seconds(anomaly.start_time),
                    "encrypted_info": "",
                    "build_error": str(exc),
                }
            data_hash = _payload_hash(payload)
            order_id = anomaly.order_id
        record_id = self._create_record(
            record_type=ChainRecordType.ANOMALY_START,
            order_id=order_id,
            anomaly_id=anomaly_id,
            payload=payload,
            data_hash=data_hash,
        )
        self._enqueue_record(record_id)
        return record_id

    def submit_anomaly_end(self, anomaly_id: int) -> int | None:
        with SessionLocal() as db:
            anomaly = db.get(Anomaly, anomaly_id)
            if anomaly is None:
                return None
            chain_anomaly_id = self._resolve_chain_anomaly_id(db, anomaly_id)
            if chain_anomaly_id is None and not self._has_any_start_record(db, anomaly_id):
                # 历史异常没有 start 上链记录时，跳过 end 上链，避免产生不可恢复失败记录。
                return None
            try:
                payload = self._build_anomaly_end_payload(anomaly, chain_anomaly_id)
            except Exception as exc:  # noqa: BLE001
                payload = {
                    "order_id": anomaly.order_id,
                    "anomaly_id": anomaly.anomaly_id,
                    "chain_anomaly_id": chain_anomaly_id,
                    "anomaly_type": _enum_value(anomaly.metric),
                    "build_error": str(exc),
                }
            data_hash = _payload_hash(payload)
            order_id = anomaly.order_id
        record_id = self._create_record(
            record_type=ChainRecordType.ANOMALY_END,
            order_id=order_id,
            anomaly_id=anomaly_id,
            payload=payload,
            data_hash=data_hash,
        )
        self._enqueue_record(record_id)
        return record_id

    def retry_record(self, record_id: int) -> None:
        dependency_retry_ids: list[int] = []
        with SessionLocal() as db:
            row = db.get(ChainRecord, record_id)
            if row is None:
                raise ChainServiceError("上链记录不存在")

            if (
                row.type == ChainRecordType.ANOMALY_END
                and row.anomaly_id is not None
                and self._resolve_chain_anomaly_id(db, row.anomaly_id) is None
            ):
                start_row = self._load_latest_start_record(
                    db,
                    row.anomaly_id,
                    ChainRecordStatus.FAILED,
                )
                if start_row is not None:
                    self._prepare_row_for_retry(start_row)
                    db.add(start_row)
                    dependency_retry_ids.append(start_row.record_id)

            self._prepare_row_for_retry(row)
            db.add(row)
            db.commit()
        for retry_id in dependency_retry_ids:
            self._enqueue_record(retry_id)
        self._enqueue_record(record_id)

    def get_order_hash(self, order_id: str) -> dict | None:
        _, contract, _ = self._build_contract_client()
        if self._has_function(contract, "getOrderHashDigest"):
            try:
                digest, timestamp, uploader = contract.functions.getOrderHashDigest(order_id).call()
            except Exception as exc:  # noqa: BLE001
                if self._is_revert(exc, "order hash not found"):
                    return None
                raise ChainServiceError(f"查询链上运单失败: {exc}") from exc
            return {
                "order_id": str(order_id),
                "data_hash": _bytes32_to_hex_text(digest),
                "timestamp": int(timestamp),
                "uploader": str(uploader),
                "data_hash_mode": "digest",
            }

        try:
            chain_order_id, chain_hash, timestamp, uploader = contract.functions.getOrderHash(
                order_id
            ).call()
        except Exception as exc:  # noqa: BLE001
            if self._is_revert(exc, "order hash not found"):
                return None
            raise ChainServiceError(f"查询链上运单失败: {exc}") from exc

        return {
            "order_id": str(chain_order_id),
            "data_hash": str(chain_hash),
            "timestamp": int(timestamp),
            "uploader": str(uploader),
            "data_hash_mode": "legacy",
        }

    def verify_order_hash(self, order_id: str, data_hash: str) -> bool:
        _, contract, _ = self._build_contract_client()
        if self._has_function(contract, "verifyOrderHashDigest"):
            try:
                digest = "0x" + _normalize_hash_hex(data_hash)
                return bool(contract.functions.verifyOrderHashDigest(order_id, digest).call())
            except Exception as exc:  # noqa: BLE001
                raise ChainServiceError(f"链上哈希校验失败: {exc}") from exc
        try:
            return bool(contract.functions.verifyOrderHash(order_id, data_hash).call())
        except Exception as exc:  # noqa: BLE001
            raise ChainServiceError(f"链上哈希校验失败: {exc}") from exc

    def get_anomaly(self, chain_anomaly_id: int) -> dict | None:
        _, contract, _ = self._build_contract_client()
        try:
            result = contract.functions.getAnomaly(chain_anomaly_id).call()
        except Exception as exc:  # noqa: BLE001
            if self._is_revert(exc, "anomaly not found"):
                return None
            raise ChainServiceError(f"查询链上异常失败: {exc}") from exc

        chain_data = {
            "order_id": str(result[0]),
            "anomaly_type": str(result[1]),
            "trigger_value_scaled": int(result[2]),
            "start_time": int(result[3]),
            "end_time": int(result[4]),
            "peak_value_scaled": int(result[5]),
            "closed": bool(result[6]),
            "encrypted_info": str(result[7]),
            "uploader": str(result[8]),
        }
        if self._has_function(contract, "getAnomalyMeta"):
            try:
                encrypted_info_hash, has_inline = contract.functions.getAnomalyMeta(
                    chain_anomaly_id
                ).call()
                chain_data["encrypted_info_hash"] = _bytes32_to_hex_text(encrypted_info_hash)
                chain_data["has_inline_encrypted_info"] = bool(has_inline)
            except Exception:  # noqa: BLE001
                pass
        if self._has_function(contract, "getDriverAnchor"):
            try:
                (
                    driver_ref_hash,
                    id_commit,
                    profile_hash,
                    updated_at,
                    uploader,
                    exists,
                ) = contract.functions.getDriverAnchor(chain_data["order_id"]).call()
                chain_data["driver_anchor_exists"] = bool(exists)
                if exists:
                    chain_data["driver_ref_hash"] = _bytes32_to_hex_text(driver_ref_hash)
                    chain_data["id_commit"] = _bytes32_to_hex_text(id_commit)
                    chain_data["profile_hash"] = _bytes32_to_hex_text(profile_hash)
                    chain_data["driver_anchor_updated_at"] = int(updated_at)
                    chain_data["driver_anchor_uploader"] = str(uploader)
            except Exception:  # noqa: BLE001
                pass
        return chain_data

    def test_connection(self) -> dict:
        web3, contract, account = self._build_contract_client()
        try:
            authorized = bool(contract.functions.isAuthorized(account.address).call())
        except Exception:  # noqa: BLE001
            authorized = False
        return {
            "chain_id": int(web3.eth.chain_id),
            "latest_block": int(web3.eth.block_number),
            "account": account.address,
            "contract_address": contract.address,
            "is_authorized": authorized,
        }

    def decrypt_anomaly_info(self, encrypted_value: str) -> dict | None:
        if not encrypted_value:
            return None
        try:
            return crypto_service.decrypt_to_dict(encrypted_value)
        except Exception:  # noqa: BLE001
            return None

    async def _worker_loop(self) -> None:
        while True:
            if self._queue is None:
                await asyncio.sleep(0.2)
                continue
            record_id = await self._queue.get()
            try:
                await asyncio.to_thread(self._process_record_sync, record_id)
            except Exception as exc:  # noqa: BLE001
                logger.warning("chain worker process failed for %s: %s", record_id, exc)
            finally:
                self._queue.task_done()

    def _process_record_sync(self, record_id: int) -> None:
        with SessionLocal() as db:
            row = db.get(ChainRecord, record_id)
            if row is None:
                return
            if row.status not in (ChainRecordStatus.PENDING, ChainRecordStatus.FAILED):
                return

            payload = _safe_parse_json(row.payload)
            try:
                tx_result = self._dispatch_chain_write(db, row, payload)
                row.tx_hash = tx_result.tx_hash
                row.block_number = tx_result.block_number
                row.status = ChainRecordStatus.CONFIRMED
                if tx_result.data_hash_mode:
                    payload["data_hash_mode"] = tx_result.data_hash_mode
                if row.type != ChainRecordType.ORDER_HASH:
                    row.data_hash = _payload_hash(payload)
                row.payload = _stable_payload_text(payload)
                db.add(row)
                db.commit()
            except ChainRetryLater:
                db.rollback()
                time.sleep(1.2)
                self._enqueue_record(record_id)
            except Exception as exc:  # noqa: BLE001
                db.rollback()
                row = db.get(ChainRecord, record_id)
                if row is None:
                    return
                payload = _safe_parse_json(row.payload)
                payload["last_error"] = str(exc)
                payload["last_error_at"] = datetime.now(timezone.utc).isoformat()
                row.payload = _stable_payload_text(payload)
                row.status = ChainRecordStatus.FAILED
                db.add(row)
                db.commit()
                logger.warning("chain record %s failed: %s", record_id, exc)

    def _dispatch_chain_write(
        self,
        db,
        row: ChainRecord,
        payload: dict,
    ) -> ChainTxResult:
        if row.type == ChainRecordType.ORDER_HASH:
            order_id = str(payload.get("order_id") or row.order_id)
            data_hash = str(payload.get("data_hash") or row.data_hash)
            return self._write_order_hash(order_id, data_hash)

        if row.type == ChainRecordType.ANOMALY_START:
            result = self._write_anomaly_start(payload)
            if result.chain_anomaly_id is None:
                raise ChainWriteError("异常开始上链成功但未解析到 chain_anomaly_id")
            payload["chain_anomaly_id"] = int(result.chain_anomaly_id)
            return result

        if row.type == ChainRecordType.ANOMALY_END:
            chain_anomaly_id = payload.get("chain_anomaly_id")
            if chain_anomaly_id is None and row.anomaly_id is not None:
                chain_anomaly_id = self._resolve_chain_anomaly_id(db, row.anomaly_id)
                if chain_anomaly_id is not None:
                    payload["chain_anomaly_id"] = int(chain_anomaly_id)
            if chain_anomaly_id is None:
                if row.anomaly_id is not None and self._has_pending_start_record(db, row.anomaly_id):
                    raise ChainRetryLater("等待 anomaly_start 上链确认")
                if row.anomaly_id is not None and self._has_failed_start_record(db, row.anomaly_id):
                    raise ChainWriteError(
                        "关联的 anomaly_start 尚未成功，请先重试 anomaly_start 后再重试 anomaly_end"
                    )
                raise ChainWriteError("缺少 chain_anomaly_id，无法关闭链上异常")
            return self._write_anomaly_end(payload)

        raise ChainWriteError(f"未知上链记录类型: {row.type}")

    def _write_order_hash(self, order_id: str, data_hash: str) -> ChainTxResult:
        web3, contract, account = self._build_contract_client()
        normalized_hash = _normalize_hash_hex(data_hash)
        digest_hex = "0x" + normalized_hash

        if self._has_function(contract, "storeOrderHashDigest"):
            return self._send_transaction(
                lambda c: c.functions.storeOrderHashDigest(order_id, digest_hex),
                client=(web3, contract, account),
                data_hash_mode="digest",
            )

        return self._send_transaction(
            lambda c: c.functions.storeOrderHash(order_id, data_hash),
            client=(web3, contract, account),
            data_hash_mode="legacy",
        )

    def _write_anomaly_start(self, payload: dict) -> ChainTxResult:
        web3, contract, account = self._build_contract_client()
        order_id = str(payload["order_id"])
        anomaly_type = str(payload["anomaly_type"])
        trigger_value = int(payload["trigger_value_scaled"])
        start_time = int(payload["start_time"])
        encrypted_info = str(payload["encrypted_info"])
        encrypted_info_hash_hex = web3.to_hex(web3.keccak(text=encrypted_info))
        payload["encrypted_info_hash"] = _bytes32_to_hex_text(encrypted_info_hash_hex)

        driver_ref_hash = str(payload.get("driver_ref_hash") or "")
        if not driver_ref_hash:
            driver_ref_hash = _sha256_hex(f"driver|{order_id}|{anomaly_type}|fallback")
        id_commit = str(payload.get("id_commit") or "")
        if not id_commit:
            id_commit = _sha256_hex(f"id|{order_id}|fallback")
        profile_hash = str(payload.get("profile_hash") or "")
        if not profile_hash:
            profile_hash = _sha256_hex(f"profile|{encrypted_info}")

        payload["driver_ref_hash"] = _normalize_hash_hex(driver_ref_hash)
        payload["id_commit"] = _normalize_hash_hex(id_commit)
        payload["profile_hash"] = _normalize_hash_hex(profile_hash)

        if self._has_function(contract, "startAnomalyLiteWithAnchor"):
            driver_ref_hash_hex = "0x" + payload["driver_ref_hash"]
            id_commit_hex = "0x" + payload["id_commit"]
            profile_hash_hex = "0x" + payload["profile_hash"]
            return self._send_transaction(
                lambda c: c.functions.startAnomalyLiteWithAnchor(
                    order_id,
                    anomaly_type,
                    trigger_value,
                    start_time,
                    encrypted_info_hash_hex,
                    driver_ref_hash_hex,
                    id_commit_hex,
                    profile_hash_hex,
                ),
                parse_chain_anomaly_id=True,
                client=(web3, contract, account),
                data_hash_mode="lite_anchor",
            )

        if self._has_function(contract, "startAnomalyLite"):
            return self._send_transaction(
                lambda c: c.functions.startAnomalyLite(
                    order_id,
                    anomaly_type,
                    trigger_value,
                    start_time,
                    encrypted_info_hash_hex,
                ),
                parse_chain_anomaly_id=True,
                client=(web3, contract, account),
                data_hash_mode="lite",
            )

        return self._send_transaction(
            lambda c: c.functions.startAnomaly(
                order_id,
                anomaly_type,
                trigger_value,
                start_time,
                encrypted_info,
            ),
            parse_chain_anomaly_id=True,
            client=(web3, contract, account),
            data_hash_mode="legacy",
        )

    def _write_anomaly_end(self, payload: dict) -> ChainTxResult:
        chain_anomaly_id = int(payload["chain_anomaly_id"])
        end_time = int(payload["end_time"])
        peak_value = int(payload["peak_value_scaled"])
        return self._send_transaction(
            lambda contract: contract.functions.closeAnomaly(
                chain_anomaly_id,
                end_time,
                peak_value,
            )
        )

    def _send_transaction(
        self,
        function_builder,
        parse_chain_anomaly_id: bool = False,
        client=None,
        data_hash_mode: str | None = None,
    ) -> ChainTxResult:
        if client is None:
            web3, contract, account = self._build_contract_client()
        else:
            web3, contract, account = client
        function_call = function_builder(contract)
        nonce = web3.eth.get_transaction_count(account.address, "pending")
        tx_params = self._build_tx_params(web3, account.address, nonce)

        try:
            gas_estimate = function_call.estimate_gas({"from": account.address})
            tx_params["gas"] = max(int(gas_estimate * 1.2), 120000)
        except Exception:  # noqa: BLE001
            tx_params["gas"] = 350000

        tx = function_call.build_transaction(tx_params)
        signed = account.sign_transaction(tx)
        raw_tx = getattr(signed, "rawTransaction", None) or getattr(
            signed,
            "raw_transaction",
            None,
        )
        if raw_tx is None:
            raise ChainWriteError("签名交易缺少 rawTransaction")

        try:
            tx_hash_bytes = web3.eth.send_raw_transaction(raw_tx)
            receipt = web3.eth.wait_for_transaction_receipt(
                tx_hash_bytes,
                timeout=self.TX_RECEIPT_TIMEOUT_SECONDS,
            )
        except Exception as exc:  # noqa: BLE001
            tx_hash_hex = web3.to_hex(tx_hash_bytes) if "tx_hash_bytes" in locals() else ""
            if tx_hash_hex:
                try:
                    receipt = web3.eth.get_transaction_receipt(tx_hash_bytes)
                except Exception:  # noqa: BLE001
                    raise ChainWriteError(
                        "交易已广播但确认超时，"
                        f"tx_hash={tx_hash_hex}，timeout={self.TX_RECEIPT_TIMEOUT_SECONDS}s，"
                        f"原始错误: {exc}"
                    ) from exc
            else:
                raise ChainWriteError(f"交易发送失败: {exc}") from exc

        status = int(getattr(receipt, "status", 0))
        if status != 1:
            raise ChainWriteError("交易回执状态为失败")

        chain_anomaly_id = None
        if parse_chain_anomaly_id:
            chain_anomaly_id = self._parse_anomaly_started_event(contract, receipt)

        return ChainTxResult(
            tx_hash=web3.to_hex(tx_hash_bytes),
            block_number=int(getattr(receipt, "blockNumber", 0) or 0),
            chain_anomaly_id=chain_anomaly_id,
            data_hash_mode=data_hash_mode,
        )

    @staticmethod
    def _parse_anomaly_started_event(contract, receipt) -> int | None:
        for event_name in ("AnomalyStarted", "AnomalyStartedLite"):
            events = ChainService._process_receipt_events(contract, event_name, receipt)
            if not events:
                continue
            value = events[0]["args"].get("anomalyId")
            if value is not None:
                return int(value)
        return None

    @staticmethod
    def _process_receipt_events(contract, event_name: str, receipt) -> list:
        try:
            event_builder = getattr(contract.events, event_name)
        except Exception:  # noqa: BLE001
            return []
        try:
            from web3.logs import DISCARD  # pylint: disable=import-outside-toplevel

            return event_builder().process_receipt(receipt, errors=DISCARD)
        except Exception:  # noqa: BLE001
            try:
                return event_builder().process_receipt(receipt)
            except Exception:  # noqa: BLE001
                return []

    @staticmethod
    def _build_tx_params(web3, account_address: str, nonce: int) -> dict:
        params = {
            "from": account_address,
            "nonce": nonce,
            "chainId": int(web3.eth.chain_id),
        }
        latest_block = web3.eth.get_block("latest")
        base_fee = latest_block.get("baseFeePerGas") if isinstance(latest_block, dict) else None
        if base_fee is None:
            params["gasPrice"] = int(web3.eth.gas_price)
            return params

        priority = int(web3.to_wei(1, "gwei"))
        suggested = int(web3.eth.gas_price)
        params["maxPriorityFeePerGas"] = priority
        params["maxFeePerGas"] = max(int(base_fee) * 2 + priority, suggested)
        return params

    def _build_contract_client(self):
        Web3 = self._resolve_web3()
        config = self._load_chain_config()

        provider = Web3.HTTPProvider(config.rpc_url, request_kwargs={"timeout": 10})
        web3 = Web3(provider)
        if not web3.is_connected():
            raise ChainConfigError("ETH RPC 连接失败，请检查 eth_rpc_url")
        try:
            from web3.middleware import ExtraDataToPOAMiddleware  # pylint: disable=import-outside-toplevel

            web3.middleware_onion.inject(ExtraDataToPOAMiddleware, layer=0)
        except Exception:  # noqa: BLE001
            pass

        try:
            contract_address = Web3.to_checksum_address(config.contract_address)
        except Exception as exc:  # noqa: BLE001
            raise ChainConfigError("eth_contract_address 不是合法地址") from exc

        abi = self._load_contract_abi()
        contract = web3.eth.contract(address=contract_address, abi=abi)
        try:
            account = web3.eth.account.from_key(config.private_key)
        except Exception as exc:  # noqa: BLE001
            raise ChainConfigError("eth_private_key 格式不合法") from exc

        return web3, contract, account

    @staticmethod
    def _resolve_web3():
        try:
            from web3 import Web3  # pylint: disable=import-outside-toplevel
        except ImportError as exc:
            raise ChainConfigError("缺少 web3 依赖，请先安装 requirements.txt") from exc
        return Web3

    def _load_chain_config(self) -> ChainConfig:
        rpc_url = _normalize_secret(system_config_service.get_value("eth_rpc_url").value)
        private_key = _normalize_secret(
            system_config_service.get_value("eth_private_key", decrypt_sensitive=True).value
        )
        contract_address = _normalize_secret(
            system_config_service.get_value("eth_contract_address").value
        )

        missing = []
        if not rpc_url:
            missing.append("eth_rpc_url")
        if not private_key:
            missing.append("eth_private_key")
        if not contract_address:
            missing.append("eth_contract_address")
        if missing:
            joined = ", ".join(missing)
            raise ChainConfigError(f"系统配置缺少必要字段: {joined}")

        return ChainConfig(
            rpc_url=rpc_url,
            private_key=private_key,
            contract_address=contract_address,
        )

    def _load_contract_abi(self) -> list:
        with self._lock:
            if self._abi_cache is not None:
                return self._abi_cache

            try:
                abi_path = resources.files(self.BUNDLED_ABI_PACKAGE).joinpath(
                    self.BUNDLED_ABI_FILE
                )
                data = json.loads(abi_path.read_text(encoding="utf-8"))
            except Exception as exc:  # noqa: BLE001
                raise ChainConfigError(
                    "读取后端内置合约 ABI 失败，请检查 app/contracts 目录"
                ) from exc
            if not isinstance(data, list) or not data:
                raise ChainConfigError("后端内置合约 ABI 为空或格式不正确")
            self._abi_cache = data
            return data

    @staticmethod
    def _has_function(contract, fn_name: str) -> bool:
        try:
            getattr(contract.functions, fn_name)
            return True
        except Exception:  # noqa: BLE001
            return False

    @staticmethod
    def _is_revert(exc: Exception, keyword: str) -> bool:
        text = str(exc).lower()
        return "revert" in text and keyword.lower() in text

    @staticmethod
    def _scale_metric(value: float | None) -> int:
        if value is None:
            return 0
        return int(round(float(value) * 100))

    @staticmethod
    def _app_secret_salt() -> str:
        secret = _normalize_secret(get_settings().app_secret_key)
        return secret or "cold_chain_default_salt"

    def _build_driver_ref_hash(
        self,
        order_id: str,
        driver_id: int | None,
        driver_username: str | None,
    ) -> str:
        username = (driver_username or "").strip().lower()
        raw = f"{order_id}|{driver_id or 0}|{username}|{self._app_secret_salt()}|driver_ref"
        return _sha256_hex(raw)

    def _build_driver_id_commit(self, order_id: str, id_card: str | None) -> str:
        normalized_id_card = (id_card or "").strip().upper()
        raw = f"{order_id}|{normalized_id_card}|{self._app_secret_salt()}|id_commit"
        return _sha256_hex(raw)

    def _build_anomaly_start_payload(self, db, anomaly: Anomaly) -> dict:
        order = db.scalar(select(Order).where(Order.order_id == anomaly.order_id).limit(1))
        if order is None:
            raise ChainServiceError("异常关联运单不存在")

        driver_user = db.scalar(select(User).where(User.user_id == order.driver_id).limit(1))
        driver_profile = db.scalar(
            select(DriverProfile).where(DriverProfile.driver_id == order.driver_id).limit(1)
        )
        profile_plain = {
            "driver_name": driver_profile.real_name if driver_profile else None,
            "id_card": driver_profile.id_card if driver_profile else None,
            "phone": driver_profile.phone if driver_profile else None,
            "plate_number": driver_profile.plate_number if driver_profile else None,
            "vehicle_type": driver_profile.vehicle_type if driver_profile else None,
            "cargo_name": order.cargo_name,
            "origin": order.origin,
            "destination": order.destination,
        }
        encrypted_info = crypto_service.encrypt_dict(profile_plain)
        driver_ref_hash = self._build_driver_ref_hash(
            order_id=order.order_id,
            driver_id=order.driver_id,
            driver_username=driver_user.username if driver_user else "",
        )
        id_commit = self._build_driver_id_commit(
            order_id=order.order_id,
            id_card=driver_profile.id_card if driver_profile else "",
        )
        profile_hash = _payload_hash(profile_plain)

        return {
            "order_id": anomaly.order_id,
            "anomaly_id": anomaly.anomaly_id,
            "anomaly_type": _enum_value(anomaly.metric),
            "trigger_value_raw": float(anomaly.trigger_value),
            "trigger_value_scaled": self._scale_metric(anomaly.trigger_value),
            "start_time": _to_unix_seconds(anomaly.start_time),
            "encrypted_info": encrypted_info,
            "driver_ref_hash": driver_ref_hash,
            "id_commit": id_commit,
            "profile_hash": profile_hash,
        }

    def _build_anomaly_end_payload(self, anomaly: Anomaly, chain_anomaly_id: int | None) -> dict:
        if anomaly.end_time is None:
            raise ChainServiceError("异常尚未结束，无法上链 anomaly_end")
        start_time = _to_unix_seconds(anomaly.start_time)
        end_time = _to_unix_seconds(anomaly.end_time)
        if end_time <= start_time:
            end_time = start_time + 1
        peak_raw = (
            float(anomaly.peak_value)
            if anomaly.peak_value is not None
            else float(anomaly.trigger_value)
        )
        return {
            "order_id": anomaly.order_id,
            "anomaly_id": anomaly.anomaly_id,
            "chain_anomaly_id": chain_anomaly_id,
            "anomaly_type": _enum_value(anomaly.metric),
            "end_time": end_time,
            "peak_value_raw": peak_raw,
            "peak_value_scaled": self._scale_metric(peak_raw),
        }

    @staticmethod
    def _resolve_chain_anomaly_id(db, anomaly_id: int) -> int | None:
        row = db.scalar(
            select(ChainRecord)
            .where(
                ChainRecord.type == ChainRecordType.ANOMALY_START,
                ChainRecord.anomaly_id == anomaly_id,
                ChainRecord.status == ChainRecordStatus.CONFIRMED,
            )
            .order_by(ChainRecord.record_id.desc())
            .limit(1)
        )
        if row is None:
            return None
        payload = _safe_parse_json(row.payload)
        value = payload.get("chain_anomaly_id")
        if value is None:
            return None
        try:
            return int(value)
        except Exception:  # noqa: BLE001
            return None

    @staticmethod
    def _has_any_start_record(db, anomaly_id: int) -> bool:
        row = db.scalar(
            select(ChainRecord.record_id)
            .where(
                ChainRecord.type == ChainRecordType.ANOMALY_START,
                ChainRecord.anomaly_id == anomaly_id,
            )
            .limit(1)
        )
        return row is not None

    @staticmethod
    def _has_pending_start_record(db, anomaly_id: int) -> bool:
        row = db.scalar(
            select(ChainRecord.record_id)
            .where(
                ChainRecord.type == ChainRecordType.ANOMALY_START,
                ChainRecord.anomaly_id == anomaly_id,
                ChainRecord.status == ChainRecordStatus.PENDING,
            )
            .limit(1)
        )
        return row is not None

    @staticmethod
    def _has_failed_start_record(db, anomaly_id: int) -> bool:
        row = db.scalar(
            select(ChainRecord.record_id)
            .where(
                ChainRecord.type == ChainRecordType.ANOMALY_START,
                ChainRecord.anomaly_id == anomaly_id,
                ChainRecord.status == ChainRecordStatus.FAILED,
            )
            .limit(1)
        )
        return row is not None

    @staticmethod
    def _load_latest_start_record(
        db,
        anomaly_id: int,
        status: ChainRecordStatus,
    ) -> ChainRecord | None:
        return db.scalar(
            select(ChainRecord)
            .where(
                ChainRecord.type == ChainRecordType.ANOMALY_START,
                ChainRecord.anomaly_id == anomaly_id,
                ChainRecord.status == status,
            )
            .order_by(ChainRecord.record_id.desc())
            .limit(1)
        )

    @staticmethod
    def _prepare_row_for_retry(row: ChainRecord) -> None:
        row.status = ChainRecordStatus.PENDING
        row.tx_hash = None
        row.block_number = None
        payload = _clear_retry_metadata(_safe_parse_json(row.payload))
        row.payload = _stable_payload_text(payload)

    @staticmethod
    def _create_record(
        record_type: ChainRecordType,
        order_id: str,
        anomaly_id: int | None,
        payload: dict,
        data_hash: str,
    ) -> int:
        with SessionLocal() as db:
            row = ChainRecord(
                type=record_type,
                order_id=order_id,
                anomaly_id=anomaly_id,
                payload=_stable_payload_text(payload),
                data_hash=data_hash,
                status=ChainRecordStatus.PENDING,
            )
            db.add(row)
            db.commit()
            db.refresh(row)
            return row.record_id

    @staticmethod
    def _load_pending_record_ids() -> list[int]:
        with SessionLocal() as db:
            return db.scalars(
                select(ChainRecord.record_id).where(ChainRecord.status == ChainRecordStatus.PENDING)
            ).all()

    def _enqueue_record(self, record_id: int) -> None:
        if self._loop is None or self._queue is None:
            return
        self._loop.call_soon_threadsafe(self._queue.put_nowait, record_id)


chain_service = ChainService()
