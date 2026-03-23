import { useEffect, useState } from "react";

import { Panel } from "../../components/Panel";
import { api, getErrorMessage, unwrap } from "../../lib/http";
import type { ApiResponse, PagedList } from "../../types/api";

interface TicketItem {
  ticket_id: number;
  type: string;
  submitter_id: number;
  order_id: string | null;
  reason: string;
  status: string;
  reviewer_id: number | null;
  review_comment: string | null;
  created_at: string;
}

export function TicketsPage() {
  const [items, setItems] = useState<TicketItem[]>([]);
  const [status, setStatus] = useState("");
  const [type, setType] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");

  const loadData = async () => {
    setLoading(true);
    setError("");
    try {
      const data = await unwrap(
        api.get<ApiResponse<PagedList<TicketItem>>>("/tickets", {
          params: {
            page: 1,
            page_size: 100,
            status: status || undefined,
            type: type || undefined,
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

  const reviewTicket = async (ticketId: number, action: "approve" | "reject") => {
    const comment = window.prompt(`请输入${action === "approve" ? "通过" : "拒绝"}意见`);
    if (!comment?.trim()) {
      return;
    }
    setError("");
    try {
      await api.patch(`/tickets/${ticketId}/${action}`, { comment });
      await loadData();
    } catch (requestError) {
      setError(getErrorMessage(requestError));
    }
  };

  return (
    <Panel
      extra={
        <div className="toolbar-inline">
          <select onChange={(event) => setStatus(event.target.value)} value={status}>
            <option value="">全部状态</option>
            <option value="pending">pending</option>
            <option value="approved">approved</option>
            <option value="rejected">rejected</option>
          </select>
          <select onChange={(event) => setType(event.target.value)} value={type}>
            <option value="">全部类型</option>
            <option value="cancel_order">cancel_order</option>
            <option value="anomaly_report">anomaly_report</option>
            <option value="info_change">info_change</option>
          </select>
          <button className="ghost-btn" onClick={() => void loadData()} type="button">
            刷新
          </button>
        </div>
      }
      title="工单管理"
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
                <th>提交人</th>
                <th>关联运单</th>
                <th>状态</th>
                <th>理由</th>
                <th>提交时间</th>
                <th>操作</th>
              </tr>
            </thead>
            <tbody>
              {items.map((item) => (
                <tr key={item.ticket_id}>
                  <td>{item.ticket_id}</td>
                  <td>{item.type}</td>
                  <td>{item.submitter_id}</td>
                  <td>{item.order_id || "-"}</td>
                  <td>{item.status}</td>
                  <td>{item.reason}</td>
                  <td>{item.created_at}</td>
                  <td>
                    {item.status === "pending" && (
                      <div className="inline-actions">
                        <button
                          className="ghost-btn small"
                          onClick={() => void reviewTicket(item.ticket_id, "approve")}
                          type="button"
                        >
                          通过
                        </button>
                        <button
                          className="danger-link"
                          onClick={() => void reviewTicket(item.ticket_id, "reject")}
                          type="button"
                        >
                          拒绝
                        </button>
                      </div>
                    )}
                  </td>
                </tr>
              ))}
              {items.length === 0 && (
                <tr>
                  <td colSpan={8}>暂无工单</td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
      )}
    </Panel>
  );
}
