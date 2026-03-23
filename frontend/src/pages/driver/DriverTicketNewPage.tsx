import { type FormEvent, useEffect, useState } from "react";
import { Link, useNavigate, useSearchParams } from "react-router-dom";

import { Panel } from "../../components/Panel";
import { api, getErrorMessage, unwrap } from "../../lib/http";
import type { ApiResponse, PagedList } from "../../types/api";

type TicketTypeValue = "cancel_order" | "anomaly_report" | "info_change";

interface DriverOrder {
  order_id: string;
  status: string;
  cargo_name: string;
}

const VALID_TICKET_TYPES: TicketTypeValue[] = [
  "cancel_order",
  "anomaly_report",
  "info_change",
];

const TYPE_LABELS: Record<TicketTypeValue, string> = {
  cancel_order: "取消运单",
  anomaly_report: "异常申报",
  info_change: "信息变更",
};

function resolveType(raw: string | null): TicketTypeValue {
  if (!raw) {
    return "info_change";
  }
  if (VALID_TICKET_TYPES.includes(raw as TicketTypeValue)) {
    return raw as TicketTypeValue;
  }
  return "info_change";
}

export function DriverTicketNewPage() {
  const navigate = useNavigate();
  const [searchParams] = useSearchParams();

  const [orders, setOrders] = useState<DriverOrder[]>([]);
  const [type, setType] = useState<TicketTypeValue>("info_change");
  const [orderId, setOrderId] = useState("");
  const [reason, setReason] = useState("");
  const [error, setError] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [loadingOrders, setLoadingOrders] = useState(false);

  const loadOrders = async () => {
    setLoadingOrders(true);
    setError("");
    try {
      const data = await unwrap(
        api.get<ApiResponse<PagedList<DriverOrder>>>("/orders", {
          params: { page: 1, page_size: 100 },
        }),
      );
      setOrders(data.items);
    } catch (requestError) {
      setError(getErrorMessage(requestError));
    } finally {
      setLoadingOrders(false);
    }
  };

  useEffect(() => {
    void loadOrders();
  }, []);

  useEffect(() => {
    setType(resolveType(searchParams.get("type")));
    setOrderId(searchParams.get("order_id") || "");
  }, [searchParams]);

  const submitTicket = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    setError("");
    const requiredOrder = type === "cancel_order" || type === "anomaly_report";
    if (requiredOrder && !orderId) {
      setError("当前工单类型必须选择关联运单");
      return;
    }
    if (!reason.trim()) {
      setError("请填写申请理由");
      return;
    }
    const orderHint = orderId ? `（运单 ${orderId}）` : "";
    const ok = window.confirm(`确认提交${TYPE_LABELS[type]}工单${orderHint}吗？`);
    if (!ok) {
      return;
    }

    setSubmitting(true);
    try {
      const result = await unwrap(
        api.post<
          ApiResponse<{
            ticket_id: number;
          }>
        >("/tickets", {
          type,
          order_id: orderId || null,
          reason: reason.trim(),
        }),
      );
      navigate(`/driver/tickets?ticket_id=${result.ticket_id}`, { replace: true });
    } catch (requestError) {
      setError(getErrorMessage(requestError));
    } finally {
      setSubmitting(false);
    }
  };

  const requiredOrder = type === "cancel_order" || type === "anomaly_report";

  return (
    <Panel
      extra={
        <div className="inline-actions">
          <Link className="ghost-btn text-link-btn" to="/driver/tickets">
            返回我的工单
          </Link>
          <button className="ghost-btn" onClick={() => void loadOrders()} type="button">
            刷新运单
          </button>
        </div>
      }
      title="提交工单"
    >
      <form className="form-grid dual" onSubmit={submitTicket}>
        <label>
          工单类型
          <select
            onChange={(event) => setType(resolveType(event.target.value))}
            value={type}
          >
            <option value="cancel_order">取消运单</option>
            <option value="anomaly_report">异常申报</option>
            <option value="info_change">信息变更</option>
          </select>
        </label>
        <label>
          关联运单{requiredOrder ? "（必选）" : ""}
          <select
            onChange={(event) => setOrderId(event.target.value)}
            required={requiredOrder}
            value={orderId}
          >
            <option value="">不关联</option>
            {orders.map((item) => (
              <option key={item.order_id} value={item.order_id}>
                {item.order_id} ({item.status}) {item.cargo_name}
              </option>
            ))}
          </select>
        </label>
        <label className="full-row">
          申请理由
          <textarea
            onChange={(event) => setReason(event.target.value)}
            placeholder="请详细描述申请原因"
            required
            rows={5}
            value={reason}
          />
        </label>
        {loadingOrders && <p className="muted full-row">运单加载中...</p>}
        {error && <p className="error-text full-row">{error}</p>}
        <button className="primary-btn full-row" disabled={submitting} type="submit">
          {submitting ? "提交中..." : `提交${TYPE_LABELS[type]}工单`}
        </button>
      </form>
    </Panel>
  );
}
