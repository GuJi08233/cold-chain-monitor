import { useEffect, useMemo, useState } from "react";
import { Link } from "react-router-dom";

import { Pagination } from "../../components/Pagination";
import { Panel } from "../../components/Panel";
import { api, getErrorMessage, unwrap } from "../../lib/http";
import type { ApiResponse, PagedList } from "../../types/api";

interface AnomalyItem {
  anomaly_id: number;
  order_id: string;
  device_id: string;
  metric: string;
  trigger_value: number;
  threshold_min: number | null;
  threshold_max: number | null;
  start_time: string;
  end_time: string | null;
  peak_value: number | null;
  status: string;
}

const METRIC_LABELS: Record<string, string> = {
  temperature: "温度",
  humidity: "湿度",
  pressure: "气压",
  device_offline: "设备离线",
};

const STATUS_LABELS: Record<string, string> = {
  ongoing: "进行中",
  resolved: "已恢复",
};

function toMillis(raw: string | null): number | null {
  if (!raw) {
    return null;
  }
  const normalized = raw.includes("T") ? raw : raw.replace(" ", "T");
  const value = Date.parse(normalized);
  if (Number.isNaN(value)) {
    return null;
  }
  return value;
}

function formatDuration(startTime: string, endTime: string | null): string {
  const start = toMillis(startTime);
  const end = toMillis(endTime) ?? Date.now();
  if (start === null) {
    return "-";
  }
  const seconds = Math.max(0, Math.floor((end - start) / 1000));
  const hours = Math.floor(seconds / 3600);
  const minutes = Math.floor((seconds % 3600) / 60);
  const remainSeconds = seconds % 60;

  if (hours > 0) {
    return `${hours}h ${minutes}m`;
  }
  if (minutes > 0) {
    return `${minutes}m ${remainSeconds}s`;
  }
  return `${remainSeconds}s`;
}

export function AnomaliesPage() {
  const [items, setItems] = useState<AnomalyItem[]>([]);
  const [status, setStatus] = useState("");
  const [metric, setMetric] = useState("");
  const [orderId, setOrderId] = useState("");
  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState(20);
  const [total, setTotal] = useState(0);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");

  const normalizedOrderId = useMemo(() => orderId.trim(), [orderId]);

  const loadData = async (nextPage = page, nextPageSize = pageSize) => {
    setLoading(true);
    setError("");
    try {
      const data = await unwrap(
        api.get<ApiResponse<PagedList<AnomalyItem>>>("/anomalies", {
          params: {
            page: nextPage,
            page_size: nextPageSize,
            status: status || undefined,
            metric: metric || undefined,
            order_id: normalizedOrderId || undefined,
          },
        }),
      );
      setItems(data.items);
      setPage(data.page);
      setPageSize(data.page_size);
      setTotal(data.total);
    } catch (requestError) {
      setError(getErrorMessage(requestError));
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    setPage(1);
    void loadData(1, pageSize);
  }, [status, metric]);

  return (
    <Panel
      extra={
        <div className="toolbar-inline">
          <select onChange={(event) => setStatus(event.target.value)} value={status}>
            <option value="">全部状态</option>
            <option value="ongoing">进行中</option>
            <option value="resolved">已恢复</option>
          </select>
          <select onChange={(event) => setMetric(event.target.value)} value={metric}>
            <option value="">全部指标</option>
            <option value="temperature">温度</option>
            <option value="humidity">湿度</option>
            <option value="pressure">气压</option>
            <option value="device_offline">设备离线</option>
          </select>
          <input
            onChange={(event) => setOrderId(event.target.value)}
            placeholder="运单号过滤"
            value={orderId}
          />
          <button
            className="ghost-btn"
            onClick={() => {
              setPage(1);
              void loadData(1, pageSize);
            }}
            type="button"
          >
            查询
          </button>
        </div>
      }
      title="异常记录"
    >
      {error && <p className="error-text">{error}</p>}
      {loading ? (
        <p className="muted">加载中...</p>
      ) : (
        <>
          <div className="table-wrap">
            <table>
              <thead>
                <tr>
                  <th>ID</th>
                  <th>运单号</th>
                  <th>设备</th>
                  <th>指标</th>
                  <th>触发值</th>
                  <th>阈值</th>
                  <th>状态</th>
                  <th>峰值</th>
                  <th>开始</th>
                  <th>持续</th>
                  <th>操作</th>
                </tr>
              </thead>
              <tbody>
                {items.map((item) => (
                  <tr key={item.anomaly_id}>
                    <td>{item.anomaly_id}</td>
                    <td>{item.order_id}</td>
                    <td>{item.device_id}</td>
                    <td>{METRIC_LABELS[item.metric] || item.metric}</td>
                    <td>{item.trigger_value}</td>
                    <td>
                      {item.threshold_min ?? "-"} / {item.threshold_max ?? "-"}
                    </td>
                    <td>{STATUS_LABELS[item.status] || item.status}</td>
                    <td>{item.peak_value ?? "-"}</td>
                    <td>{item.start_time}</td>
                    <td>{formatDuration(item.start_time, item.end_time)}</td>
                    <td>
                      <Link
                        className="text-link"
                        to={`/admin/orders/${item.order_id}?anomaly_id=${item.anomaly_id}`}
                      >
                        查看详情
                      </Link>
                    </td>
                  </tr>
                ))}
                {items.length === 0 && (
                  <tr>
                    <td colSpan={11}>暂无异常记录</td>
                  </tr>
                )}
              </tbody>
            </table>
          </div>
          <Pagination
            onPageChange={(nextPage) => {
              setPage(nextPage);
              void loadData(nextPage, pageSize);
            }}
            onPageSizeChange={(nextPageSize) => {
              setPage(1);
              setPageSize(nextPageSize);
              void loadData(1, nextPageSize);
            }}
            page={page}
            pageSize={pageSize}
            total={total}
          />
        </>
      )}
    </Panel>
  );
}
