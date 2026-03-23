import { useEffect, useState } from "react";
import { Link } from "react-router-dom";

import { Panel } from "../../components/Panel";
import { api, getErrorMessage, unwrap } from "../../lib/http";
import type { ApiResponse, PagedList } from "../../types/api";

interface ChainRecord {
  record_id: number;
  type: string;
  order_id: string;
  anomaly_id: number | null;
  tx_hash: string | null;
  block_number: number | null;
  status: string;
  created_at: string;
}

interface VerifyResult {
  order_id: string;
  local_hash: string | null;
  chain_hash: string | null;
  match: boolean;
  tx_hash: string | null;
}

interface ChainAnomalyDetail {
  anomaly_id: number;
  chain_anomaly_id: number;
  order_id: string;
  anomaly_type: string;
  trigger_value: number;
  start_time: string | null;
  end_time: string | null;
  peak_value: number | null;
  closed: boolean;
  encrypted_info: string;
  encrypted_info_hash?: string | null;
  has_inline_encrypted_info?: boolean | null;
  driver_anchor_exists?: boolean | null;
  driver_ref_hash?: string | null;
  id_commit?: string | null;
  profile_hash?: string | null;
  driver_anchor_updated_at?: string | null;
  driver_anchor_uploader?: string | null;
  decrypted_info_source?: "chain" | "local_start_payload" | "none";
  driver_identity?: {
    driver_id: number | null;
    username: string | null;
    display_name: string | null;
    real_name: string | null;
  } | null;
  driver_anchor_match?: {
    driver_ref_hash: boolean | null;
    id_commit: boolean | null;
    profile_hash: boolean | null;
  } | null;
  decrypted_info: unknown;
  uploader: string;
  start_tx_hash: string | null;
  start_block_number: number | null;
  end_tx_hash: string | null;
  end_block_number: number | null;
}

const STATUS_LABELS: Record<string, string> = {
  pending: "待处理",
  confirmed: "已确认",
  failed: "失败",
};

const TYPE_LABELS: Record<string, string> = {
  order_hash: "运单哈希",
  anomaly_start: "异常开始",
  anomaly_end: "异常结束",
};
const SEPOLIA_ETHERSCAN_TX_BASE_URL = "https://sepolia.etherscan.io/tx/";

function toInt(raw: string): number | null {
  const text = raw.trim();
  if (!text) {
    return null;
  }
  const value = Number(text);
  if (!Number.isInteger(value) || value <= 0) {
    return null;
  }
  return value;
}

function formatJson(value: unknown): string {
  try {
    return JSON.stringify(value, null, 2);
  } catch {
    return String(value);
  }
}

function sourceLabel(source?: ChainAnomalyDetail["decrypted_info_source"]): string {
  if (source === "chain") {
    return "链上明文密文";
  }
  if (source === "local_start_payload") {
    return "本地上链快照回退";
  }
  return "不可用";
}

function matchLabel(value: boolean | null | undefined): string {
  if (value === true) {
    return "一致";
  }
  if (value === false) {
    return "不一致";
  }
  return "-";
}

function txExplorerUrl(txHash: string): string {
  return `${SEPOLIA_ETHERSCAN_TX_BASE_URL}${txHash}`;
}

function txHashLabel(txHash: string): string {
  if (txHash.length <= 18) {
    return txHash;
  }
  return `${txHash.slice(0, 10)}...${txHash.slice(-8)}`;
}

function renderTxHashLink(txHash: string | null, label?: string) {
  if (!txHash) {
    return "-";
  }
  return (
    <a
      className="text-link"
      href={txExplorerUrl(txHash)}
      rel="noreferrer"
      target="_blank"
      title={txHash}
    >
      {label || txHashLabel(txHash)}
    </a>
  );
}

export function ChainPage() {
  const [items, setItems] = useState<ChainRecord[]>([]);
  const [status, setStatus] = useState("");
  const [type, setType] = useState("");
  const [orderId, setOrderId] = useState("");
  const [anomalyId, setAnomalyId] = useState("");
  const [verifyOrderId, setVerifyOrderId] = useState("");
  const [verifyResult, setVerifyResult] = useState<VerifyResult | null>(null);
  const [detailAnomalyInput, setDetailAnomalyInput] = useState("");
  const [anomalyDetail, setAnomalyDetail] = useState<ChainAnomalyDetail | null>(null);
  const [loading, setLoading] = useState(false);
  const [detailLoading, setDetailLoading] = useState(false);
  const [error, setError] = useState("");

  const loadData = async () => {
    setLoading(true);
    setError("");
    try {
      const data = await unwrap(
        api.get<ApiResponse<PagedList<ChainRecord>>>("/chain/records", {
          params: {
            page: 1,
            page_size: 100,
            status: status || undefined,
            type: type || undefined,
            order_id: orderId.trim() || undefined,
            anomaly_id: toInt(anomalyId) || undefined,
          },
        }),
      );
      setItems(data.items);
    } catch (requestError) {
      setError(getErrorMessage(requestError));
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    void loadData();
  }, [status, type]);

  const retryRecord = async (recordId: number) => {
    try {
      await api.post(`/chain/records/${recordId}/retry`);
      await loadData();
    } catch (requestError) {
      setError(getErrorMessage(requestError));
    }
  };

  const verifyOrder = async () => {
    if (!verifyOrderId.trim()) {
      return;
    }
    setError("");
    setVerifyResult(null);
    try {
      const data = await unwrap(
        api.get<ApiResponse<VerifyResult>>(`/chain/order/${verifyOrderId.trim()}/verify`),
      );
      setVerifyResult(data);
    } catch (requestError) {
      setError(getErrorMessage(requestError));
    }
  };

  const loadAnomalyDetail = async (value?: number) => {
    const target = value ?? toInt(detailAnomalyInput);
    if (!target) {
      setError("请输入有效异常 ID");
      return;
    }
    setDetailLoading(true);
    setError("");
    try {
      const data = await unwrap(api.get<ApiResponse<ChainAnomalyDetail>>(`/chain/anomaly/${target}`));
      setAnomalyDetail(data);
      setDetailAnomalyInput(String(target));
    } catch (requestError) {
      setError(getErrorMessage(requestError));
    } finally {
      setDetailLoading(false);
    }
  };

  return (
    <div className="page-grid">
      <Panel title="运单哈希验证">
        <div className="toolbar-inline">
          <input
            onChange={(event) => setVerifyOrderId(event.target.value)}
            placeholder="输入运单号"
            value={verifyOrderId}
          />
          <button className="primary-btn inline" onClick={() => void verifyOrder()} type="button">
            验证哈希
          </button>
        </div>
        {verifyResult && (
          <div className={verifyResult.match ? "state-box success" : "state-box danger"}>
            <p>运单号: {verifyResult.order_id}</p>
            <p>本地哈希: {verifyResult.local_hash || "-"}</p>
            <p>链上哈希: {verifyResult.chain_hash || "-"}</p>
            <p>校验结果: {verifyResult.match ? "一致" : "不一致"}</p>
            <p>交易哈希: {renderTxHashLink(verifyResult.tx_hash, verifyResult.tx_hash || undefined)}</p>
          </div>
        )}
      </Panel>

      <Panel title="异常链上详情">
        <div className="toolbar-inline">
          <input
            onChange={(event) => setDetailAnomalyInput(event.target.value)}
            placeholder="输入异常 ID"
            value={detailAnomalyInput}
          />
          <button
            className="primary-btn inline"
            disabled={detailLoading}
            onClick={() => void loadAnomalyDetail()}
            type="button"
          >
            {detailLoading ? "查询中..." : "查询异常链上详情"}
          </button>
        </div>
        {anomalyDetail && (
          <div className="state-box success">
            <p>异常 ID: {anomalyDetail.anomaly_id}</p>
            <p>链上异常 ID: {anomalyDetail.chain_anomaly_id}</p>
            <p>运单号: {anomalyDetail.order_id}</p>
            <p>异常类型: {anomalyDetail.anomaly_type}</p>
            <p>触发值: {anomalyDetail.trigger_value}</p>
            <p>峰值: {anomalyDetail.peak_value ?? "-"}</p>
            <p>开始时间: {anomalyDetail.start_time || "-"}</p>
            <p>结束时间: {anomalyDetail.end_time || "-"}</p>
            <p>是否关闭: {anomalyDetail.closed ? "是" : "否"}</p>
            <p>上链账户: {anomalyDetail.uploader}</p>
            <p>
              开始交易:
              {" "}
              {renderTxHashLink(
                anomalyDetail.start_tx_hash,
                anomalyDetail.start_tx_hash || undefined,
              )}
            </p>
            <p>
              结束交易:
              {" "}
              {renderTxHashLink(
                anomalyDetail.end_tx_hash,
                anomalyDetail.end_tx_hash || undefined,
              )}
            </p>
            <p>解密来源: {sourceLabel(anomalyDetail.decrypted_info_source)}</p>
            <p>
              司机标识:
              {anomalyDetail.driver_identity
                ? `${anomalyDetail.driver_identity.display_name || anomalyDetail.driver_identity.real_name || anomalyDetail.driver_identity.username || "-"} (ID=${anomalyDetail.driver_identity.driver_id ?? "-"})`
                : "-"}
            </p>
            <p>司机锚点: {anomalyDetail.driver_anchor_exists ? "已存在" : "未找到"}</p>
            <p className="hash-cell">driver_ref_hash: {anomalyDetail.driver_ref_hash || "-"}</p>
            <p className="hash-cell">id_commit: {anomalyDetail.id_commit || "-"}</p>
            <p className="hash-cell">profile_hash: {anomalyDetail.profile_hash || "-"}</p>
            <p>driver_ref_hash 校验: {matchLabel(anomalyDetail.driver_anchor_match?.driver_ref_hash)}</p>
            <p>id_commit 校验: {matchLabel(anomalyDetail.driver_anchor_match?.id_commit)}</p>
            <p>profile_hash 校验: {matchLabel(anomalyDetail.driver_anchor_match?.profile_hash)}</p>
            <p>解密信息:</p>
            <pre className="json-block">{formatJson(anomalyDetail.decrypted_info)}</pre>
            <p>
              <Link
                className="text-link"
                to={`/admin/orders/${anomalyDetail.order_id}?anomaly_id=${anomalyDetail.anomaly_id}`}
              >
                跳转运单并定位异常
              </Link>
            </p>
          </div>
        )}
      </Panel>

      <Panel
        extra={
          <div className="toolbar-inline">
            <select onChange={(event) => setStatus(event.target.value)} value={status}>
              <option value="">全部状态</option>
              <option value="pending">待处理</option>
              <option value="confirmed">已确认</option>
              <option value="failed">失败</option>
            </select>
            <select onChange={(event) => setType(event.target.value)} value={type}>
              <option value="">全部类型</option>
              <option value="order_hash">运单哈希</option>
              <option value="anomaly_start">异常开始</option>
              <option value="anomaly_end">异常结束</option>
            </select>
            <input
              onChange={(event) => setOrderId(event.target.value)}
              placeholder="按运单号过滤"
              value={orderId}
            />
            <input
              onChange={(event) => setAnomalyId(event.target.value)}
              placeholder="按异常ID过滤"
              value={anomalyId}
            />
            <button className="ghost-btn" onClick={() => void loadData()} type="button">
              查询
            </button>
          </div>
        }
        title="上链记录"
      >
        {error && <p className="error-text">{error}</p>}
        {loading ? (
          <p className="muted">加载中...</p>
        ) : (
          <div className="table-wrap">
            <table>
              <thead>
                <tr>
                  <th>ID</th>
                  <th>类型</th>
                  <th>运单号</th>
                  <th>异常ID</th>
                  <th>状态</th>
                  <th>交易哈希</th>
                  <th>区块号</th>
                  <th>创建时间</th>
                  <th>操作</th>
                </tr>
              </thead>
              <tbody>
                {items.map((item) => (
                  <tr key={item.record_id}>
                    <td>{item.record_id}</td>
                    <td>{TYPE_LABELS[item.type] || item.type}</td>
                    <td>{item.order_id}</td>
                    <td>{item.anomaly_id ?? "-"}</td>
                    <td>{STATUS_LABELS[item.status] || item.status}</td>
                    <td className="hash-cell">{renderTxHashLink(item.tx_hash)}</td>
                    <td>{item.block_number || "-"}</td>
                    <td>{item.created_at}</td>
                    <td>
                      <div className="inline-actions">
                        {item.anomaly_id && (
                          <button
                            className="ghost-btn small"
                            onClick={() => void loadAnomalyDetail(item.anomaly_id!)}
                            type="button"
                          >
                            异常详情
                          </button>
                        )}
                        {item.status === "failed" && (
                          <button
                            className="danger-link"
                            onClick={() => void retryRecord(item.record_id)}
                            type="button"
                          >
                            重试
                          </button>
                        )}
                      </div>
                    </td>
                  </tr>
                ))}
                {items.length === 0 && (
                  <tr>
                    <td colSpan={9}>暂无上链记录</td>
                  </tr>
                )}
              </tbody>
            </table>
          </div>
        )}
      </Panel>
    </div>
  );
}
