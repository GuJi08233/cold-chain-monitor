import { useEffect, useState } from "react";
import { Link } from "react-router-dom";

import { Pagination } from "../../components/Pagination";
import { Panel } from "../../components/Panel";
import { api, getErrorMessage, unwrap } from "../../lib/http";
import type { ApiResponse, PagedList } from "../../types/api";

interface DriverOrder {
  order_id: string;
  cargo_name: string;
  origin: string;
  destination: string;
  status: string;
  planned_start: string;
  actual_start: string | null;
  actual_end: string | null;
}

export function DriverOrdersPage() {
  const [items, setItems] = useState<DriverOrder[]>([]);
  const [status, setStatus] = useState("");
  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState(20);
  const [total, setTotal] = useState(0);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);

  const loadData = async (nextPage = page, nextPageSize = pageSize) => {
    setLoading(true);
    setError("");
    try {
      const data = await unwrap(
        api.get<ApiResponse<PagedList<DriverOrder>>>("/orders", {
          params: {
            page: nextPage,
            page_size: nextPageSize,
            status: status || undefined,
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
    void loadData();
    const timer = window.setInterval(() => {
      void loadData();
    }, 10000);
    return () => window.clearInterval(timer);
  }, [status, page, pageSize]);

  const startOrder = async (orderId: string) => {
    const ok = window.confirm(`确认提前出发运单 ${orderId} 吗？`);
    if (!ok) {
      return;
    }
    try {
      await api.patch(`/orders/${orderId}/start`);
      await loadData();
    } catch (requestError) {
      setError(getErrorMessage(requestError));
    }
  };

  const completeOrder = async (orderId: string) => {
    const ok = window.confirm(
      `确认已到达并完成运单 ${orderId} 吗？\n提交后将进入结算并触发哈希计算。`,
    );
    if (!ok) {
      return;
    }
    try {
      await api.patch(`/orders/${orderId}/complete`);
      await loadData();
    } catch (requestError) {
      setError(getErrorMessage(requestError));
    }
  };

  return (
    <Panel
      extra={
        <div className="toolbar-inline">
          <select
            onChange={(event) => {
              setPage(1);
              setStatus(event.target.value);
            }}
            value={status}
          >
            <option value="">全部状态</option>
            <option value="pending">待出发</option>
            <option value="in_transit">运输中</option>
            <option value="completed">已完成</option>
            <option value="cancelled">已取消</option>
          </select>
          <button className="ghost-btn" onClick={() => void loadData()} type="button">
            刷新
          </button>
        </div>
      }
      title="我的运单"
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
                  <th>运单号</th>
                  <th>货物</th>
                  <th>起止地</th>
                  <th>状态</th>
                  <th>计划出发</th>
                  <th>操作</th>
                </tr>
              </thead>
              <tbody>
                {items.map((item) => (
                  <tr key={item.order_id}>
                    <td>{item.order_id}</td>
                    <td>{item.cargo_name}</td>
                    <td>
                      {item.origin} → {item.destination}
                    </td>
                    <td>{item.status}</td>
                    <td>{item.planned_start}</td>
                    <td>
                      <div className="inline-actions">
                        <Link className="text-link" to={`/driver/orders/${item.order_id}`}>
                          详情
                        </Link>
                        {item.status === "pending" && (
                          <button
                            className="ghost-btn small"
                            onClick={() => void startOrder(item.order_id)}
                            type="button"
                          >
                            提前出发
                          </button>
                        )}
                        {item.status === "in_transit" && (
                          <button
                            className="primary-btn inline"
                            onClick={() => void completeOrder(item.order_id)}
                            type="button"
                          >
                            确认到达
                          </button>
                        )}
                        {(item.status === "pending" || item.status === "in_transit") && (
                          <Link
                            className="ghost-btn small text-link-btn"
                            onClick={(event) => {
                              const ok = window.confirm(
                                `确认要为运单 ${item.order_id} 提交取消申请吗？`,
                              );
                              if (!ok) {
                                event.preventDefault();
                              }
                            }}
                            to={`/driver/tickets/new?type=cancel_order&order_id=${encodeURIComponent(item.order_id)}`}
                          >
                            申请取消
                          </Link>
                        )}
                      </div>
                    </td>
                  </tr>
                ))}
                {items.length === 0 && (
                  <tr>
                    <td colSpan={6}>暂无运单</td>
                  </tr>
                )}
              </tbody>
            </table>
          </div>
          <Pagination
            onPageChange={(nextPage) => {
              setPage(nextPage);
            }}
            onPageSizeChange={(nextPageSize) => {
              setPage(1);
              setPageSize(nextPageSize);
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
