import { useEffect, useMemo, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";

import { Pagination } from "../../components/Pagination";
import { Panel } from "../../components/Panel";
import { api, getErrorMessage, unwrap } from "../../lib/http";
import type { ApiResponse, PagedList } from "../../types/api";

interface TicketItem {
  ticket_id: number;
  type: string;
  order_id: string | null;
  reason: string;
  status: string;
  review_comment: string | null;
  created_at: string;
}

export function DriverTicketsPage() {
  const [searchParams] = useSearchParams();
  const [items, setItems] = useState<TicketItem[]>([]);
  const [status, setStatus] = useState("");
  const [type, setType] = useState("");
  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState(20);
  const [total, setTotal] = useState(0);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);

  const focusTicketId = useMemo(() => {
    const raw = searchParams.get("ticket_id");
    if (!raw) {
      return null;
    }
    const parsed = Number(raw);
    if (!Number.isInteger(parsed) || parsed <= 0) {
      return null;
    }
    return parsed;
  }, [searchParams]);

  const loadData = async (nextPage = page, nextPageSize = pageSize) => {
    setLoading(true);
    setError("");
    try {
      const ticketData = await unwrap(
        api.get<ApiResponse<PagedList<TicketItem>>>("/tickets", {
          params: {
            page: nextPage,
            page_size: nextPageSize,
            status: status || undefined,
            type: type || undefined,
            ticket_id: focusTicketId || undefined,
          },
        }),
      );
      setItems(ticketData.items);
      setPage(ticketData.page);
      setPageSize(ticketData.page_size);
      setTotal(ticketData.total);
    } catch (requestError) {
      setError(getErrorMessage(requestError));
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    setPage(1);
    void loadData(1, pageSize);
  }, [status, type, focusTicketId]);

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
            <option value="pending">待处理</option>
            <option value="approved">已通过</option>
            <option value="rejected">已拒绝</option>
          </select>
          <select
            onChange={(event) => {
              setPage(1);
              setType(event.target.value);
            }}
            value={type}
          >
            <option value="">全部类型</option>
            <option value="cancel_order">取消运单</option>
            <option value="anomaly_report">异常申报</option>
            <option value="info_change">信息变更</option>
          </select>
          <Link className="primary-btn inline text-link-btn" to="/driver/tickets/new">
            提交工单
          </Link>
          <button className="ghost-btn" onClick={() => void loadData()} type="button">
            刷新
          </button>
        </div>
      }
      title="我的工单"
    >
      {error && <p className="error-text">{error}</p>}
      {focusTicketId && <p className="muted">当前定位工单: #{focusTicketId}</p>}
      {loading ? (
        <p className="muted">加载中...</p>
      ) : (
        <>
          <div className="table-wrap">
            <table>
              <thead>
                <tr>
                  <th>ID</th>
                  <th>类型</th>
                  <th>运单号</th>
                  <th>状态</th>
                  <th>理由</th>
                  <th>审批意见</th>
                  <th>提交时间</th>
                </tr>
              </thead>
              <tbody>
                {items.map((item) => (
                  <tr
                    className={focusTicketId === item.ticket_id ? "highlight-row" : undefined}
                    key={item.ticket_id}
                  >
                    <td>{item.ticket_id}</td>
                    <td>{item.type}</td>
                    <td>{item.order_id || "-"}</td>
                    <td>{item.status}</td>
                    <td>{item.reason}</td>
                    <td>{item.review_comment || "-"}</td>
                    <td>{item.created_at}</td>
                  </tr>
                ))}
                {items.length === 0 && (
                  <tr>
                    <td colSpan={7}>暂无工单</td>
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
