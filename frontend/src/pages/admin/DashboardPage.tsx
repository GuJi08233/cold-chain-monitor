import { useEffect, useState } from "react";
import { Link } from "react-router-dom";

import { Panel } from "../../components/Panel";
import { api, getErrorMessage, unwrap } from "../../lib/http";
import type { ApiResponse } from "../../types/api";

interface DashboardStats {
  devices_online: number;
  devices_total: number;
  orders_in_transit: number;
  orders_total: number;
  anomalies_ongoing: number;
  anomalies_total: number;
  chain_records_total: number;
}

interface RecentOrder {
  order_id: string;
  device_id: string;
  driver_id: number;
  status: string;
  origin: string;
  destination: string;
  created_at: string | null;
}

interface RecentAnomaly {
  anomaly_id: number;
  order_id: string;
  metric: string;
  status: string;
  trigger_value: number;
  peak_value: number | null;
  start_time: string | null;
}

interface PendingTickets {
  pending_tickets: number;
}

const emptyStats: DashboardStats = {
  devices_online: 0,
  devices_total: 0,
  orders_in_transit: 0,
  orders_total: 0,
  anomalies_ongoing: 0,
  anomalies_total: 0,
  chain_records_total: 0,
};

export function DashboardPage() {
  const [stats, setStats] = useState<DashboardStats>(emptyStats);
  const [orders, setOrders] = useState<RecentOrder[]>([]);
  const [anomalies, setAnomalies] = useState<RecentAnomaly[]>([]);
  const [pendingTickets, setPendingTickets] = useState(0);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  const loadData = async () => {
    setLoading(true);
    setError("");
    try {
      const [statsData, ordersData, anomaliesData, ticketData] = await Promise.all([
        unwrap(api.get<ApiResponse<DashboardStats>>("/dashboard/stats")),
        unwrap(api.get<ApiResponse<RecentOrder[]>>("/dashboard/recent-orders")),
        unwrap(api.get<ApiResponse<RecentAnomaly[]>>("/dashboard/recent-anomalies")),
        unwrap(api.get<ApiResponse<PendingTickets>>("/dashboard/pending-tickets")),
      ]);
      setStats(statsData);
      setOrders(ordersData);
      setAnomalies(anomaliesData);
      setPendingTickets(ticketData.pending_tickets);
    } catch (requestError) {
      setError(getErrorMessage(requestError));
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    void loadData();
  }, []);

  return (
    <div className="page-grid">
      <Panel
        extra={
          <button className="ghost-btn" onClick={() => void loadData()} type="button">
            刷新
          </button>
        }
        title="系统总览"
      >
        {error && <p className="error-text">{error}</p>}
        <div className="stats-grid">
          <article className="stat-card">
            <span>在线设备</span>
            <strong>
              {stats.devices_online}/{stats.devices_total}
            </strong>
          </article>
          <article className="stat-card">
            <span>运输中运单</span>
            <strong>
              {stats.orders_in_transit}/{stats.orders_total}
            </strong>
          </article>
          <article className="stat-card">
            <span>进行中异常</span>
            <strong>
              {stats.anomalies_ongoing}/{stats.anomalies_total}
            </strong>
          </article>
          <article className="stat-card">
            <span>上链记录</span>
            <strong>{stats.chain_records_total}</strong>
          </article>
          <article className="stat-card warning">
            <span>待处理工单</span>
            <strong>{pendingTickets}</strong>
          </article>
        </div>
      </Panel>

      <div className="dual-grid">
        <Panel title="最近运单">
          {loading ? (
            <p className="muted">加载中...</p>
          ) : (
            <div className="table-wrap">
              <table>
                <thead>
                <tr>
                  <th>运单号</th>
                  <th>设备</th>
                  <th>状态</th>
                  <th>起止地</th>
                  <th>创建时间</th>
                  <th>操作</th>
                </tr>
              </thead>
              <tbody>
                {orders.map((item) => (
                  <tr key={item.order_id}>
                      <td>{item.order_id}</td>
                      <td>{item.device_id}</td>
                      <td>{item.status}</td>
                    <td>
                      {item.origin} → {item.destination}
                    </td>
                    <td>{item.created_at || "-"}</td>
                    <td>
                      <Link className="text-link" to={`/admin/orders/${item.order_id}`}>
                        查看
                      </Link>
                    </td>
                  </tr>
                ))}
                {orders.length === 0 && (
                  <tr>
                    <td colSpan={6}>暂无数据</td>
                  </tr>
                )}
              </tbody>
            </table>
            </div>
          )}
        </Panel>

        <Panel title="最近异常">
          {loading ? (
            <p className="muted">加载中...</p>
          ) : (
            <div className="table-wrap">
              <table>
                <thead>
                  <tr>
                    <th>ID</th>
                    <th>运单</th>
                    <th>指标</th>
                    <th>状态</th>
                    <th>触发值</th>
                    <th>开始时间</th>
                    <th>操作</th>
                  </tr>
                </thead>
                <tbody>
                  {anomalies.map((item) => (
                    <tr key={item.anomaly_id}>
                      <td>{item.anomaly_id}</td>
                      <td>{item.order_id}</td>
                      <td>{item.metric}</td>
                      <td>{item.status}</td>
                      <td>{item.trigger_value}</td>
                      <td>{item.start_time || "-"}</td>
                      <td>
                        <Link
                          className="text-link"
                          to={`/admin/orders/${item.order_id}?anomaly_id=${item.anomaly_id}`}
                        >
                          定位
                        </Link>
                      </td>
                    </tr>
                  ))}
                  {anomalies.length === 0 && (
                    <tr>
                      <td colSpan={7}>暂无数据</td>
                    </tr>
                  )}
                </tbody>
              </table>
            </div>
          )}
        </Panel>
      </div>
    </div>
  );
}
