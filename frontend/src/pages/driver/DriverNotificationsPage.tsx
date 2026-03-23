import { useEffect, useState } from "react";
import { Link } from "react-router-dom";

import { Panel } from "../../components/Panel";
import { api, getErrorMessage, unwrap } from "../../lib/http";
import { dispatchUnreadSync } from "../../lib/notifications";
import type { ApiResponse, PagedList } from "../../types/api";

interface NotificationItem {
  notification_id: number;
  type: string;
  title: string;
  content: unknown;
  is_read: boolean;
  created_at: string;
}

interface UnreadCountResult {
  unread_count: number;
}

const TYPE_LABELS: Record<string, string> = {
  anomaly_start: "异常告警",
  anomaly_end: "异常恢复",
  ticket_result: "工单审批结果",
  order_assigned: "新运单下发",
  new_ticket: "新工单通知",
  driver_pending: "司机注册待审",
};

interface NotificationTarget {
  to: string;
  label: string;
}

function contentToObject(value: unknown): Record<string, unknown> | null {
  if (!value || typeof value !== "object" || Array.isArray(value)) {
    return null;
  }
  return value as Record<string, unknown>;
}

function valueToText(value: unknown): string {
  if (value === null || value === undefined) {
    return "";
  }
  if (typeof value === "string") {
    return value.trim();
  }
  if (typeof value === "number" || typeof value === "boolean") {
    return String(value);
  }
  if (Array.isArray(value)) {
    const texts = value
      .map((entry) => valueToText(entry))
      .filter((entry) => entry.length > 0);
    if (texts.length === 0) {
      return "";
    }
    return texts.join("、");
  }
  if (typeof value === "object") {
    const keyCount = Object.keys(value as Record<string, unknown>).length;
    return keyCount > 0 ? `对象(${keyCount}个字段)` : "";
  }
  return "";
}

function metricText(metric: unknown): string {
  if (metric === "temperature") {
    return "温度";
  }
  if (metric === "humidity") {
    return "湿度";
  }
  if (metric === "pressure") {
    return "气压";
  }
  return valueToText(metric);
}

const CONTENT_KEY_LABELS: Record<string, string> = {
  order_id: "运单号",
  anomaly_id: "异常ID",
  ticket_id: "工单ID",
  cargo_name: "货物名称",
  origin: "出发地",
  destination: "目的地",
  planned_start: "计划出发时间",
  actual_start: "实际出发时间",
  actual_end: "实际结束时间",
  driver_id: "司机ID",
  driver_name: "司机姓名",
  metric: "指标",
  trigger_value: "触发值",
  threshold_min: "阈值下限",
  threshold_max: "阈值上限",
  ts: "时间",
  start_time: "开始时间",
  end_time: "结束时间",
  device_id: "设备ID",
  gps_lat: "纬度",
  gps_lng: "经度",
  lat: "纬度",
  lng: "经度",
  status: "状态",
  result: "处理结果",
  message: "消息",
  reason: "原因",
  comment: "备注",
};

function buildSummary(item: NotificationItem, content: Record<string, unknown>): string | null {
  const orderId = valueToText(content.order_id) || "-";
  const anomalyId = valueToText(content.anomaly_id);
  const ticketId = valueToText(content.ticket_id);
  const metric = metricText(content.metric);
  const trigger = valueToText(content.trigger_value);
  const minValue = valueToText(content.threshold_min);
  const maxValue = valueToText(content.threshold_max);

  if (item.type === "anomaly_start") {
    const thresholdText =
      minValue || maxValue
        ? `（阈值 ${minValue || "-"} ~ ${maxValue || "-"}）`
        : "";
    const anomalyText = anomalyId ? `，异常ID ${anomalyId}` : "";
    return `运单 ${orderId} 出现${metric || ""}异常${anomalyText}${trigger ? `，触发值 ${trigger}` : ""}${thresholdText}`;
  }

  if (item.type === "anomaly_end") {
    return `运单 ${orderId} 的${metric || ""}异常已恢复${anomalyId ? `（异常ID ${anomalyId}）` : ""}`;
  }

  if (item.type === "order_assigned") {
    return `你已被分配到运单 ${orderId}`;
  }

  if (item.type === "ticket_result") {
    const resultText = valueToText(content.result) || valueToText(content.status) || "-";
    return `工单 ${ticketId ? `#${ticketId}` : ""} 审批结果：${resultText}`;
  }

  if (item.type === "new_ticket") {
    return ticketId ? `收到新工单 #${ticketId}` : "收到新工单，请尽快处理";
  }

  return null;
}

function renderContent(item: NotificationItem) {
  const rawContent =
    typeof item.content === "string" ? item.content.trim() : item.content;
  let content = contentToObject(rawContent);
  if (
    !content &&
    typeof rawContent === "string" &&
    (rawContent.startsWith("{") || rawContent.startsWith("["))
  ) {
    try {
      const parsed = JSON.parse(rawContent);
      content = contentToObject(parsed);
    } catch {
      content = null;
    }
  }
  if (!content) {
    return valueToText(rawContent) || "-";
  }

  const summary = buildSummary(item, content);
  const detailEntries = Object.entries(content)
    .map(([key, value]) => {
      const text = key === "metric" ? metricText(value) : valueToText(value);
      if (!text) {
        return null;
      }
      return {
        key,
        label: CONTENT_KEY_LABELS[key] || key,
        value: text,
      };
    })
    .filter((entry): entry is { key: string; label: string; value: string } => entry !== null);

  return (
    <div className="notification-content">
      {summary && <p className="notification-summary">{summary}</p>}
      {detailEntries.length > 0 && (
        <div className="notification-kv-list">
          {detailEntries.map((entry) => (
            <p key={`content-${entry.key}`}>
              <strong>{entry.label}:</strong> {entry.value}
            </p>
          ))}
        </div>
      )}
    </div>
  );
}

function toTicketId(raw: unknown): number | null {
  if (typeof raw === "number" && Number.isInteger(raw) && raw > 0) {
    return raw;
  }
  if (typeof raw === "string" && raw.trim()) {
    const parsed = Number(raw);
    if (Number.isInteger(parsed) && parsed > 0) {
      return parsed;
    }
  }
  return null;
}

function resolveTarget(item: NotificationItem): NotificationTarget | null {
  const parsed = contentToObject(item.content);
  if (!parsed) {
    return null;
  }

  const orderId =
    typeof parsed.order_id === "string" && parsed.order_id.trim()
      ? parsed.order_id
      : null;
  const ticketId = toTicketId(parsed.ticket_id);
  const anomalyId = toTicketId(parsed.anomaly_id);

  if (
    item.type === "anomaly_start" ||
    item.type === "anomaly_end" ||
    item.type === "order_assigned"
  ) {
    if (!orderId) {
      return null;
    }
    const anomalyQuery = anomalyId ? `?anomaly_id=${anomalyId}` : "";
    return {
      to: `/driver/orders/${encodeURIComponent(orderId)}${anomalyQuery}`,
      label: "查看运单",
    };
  }

  if (item.type === "ticket_result" || item.type === "new_ticket") {
    if (ticketId) {
      return {
        to: `/driver/tickets?ticket_id=${ticketId}`,
        label: "查看工单",
      };
    }
    return { to: "/driver/tickets", label: "查看工单" };
  }

  return null;
}

export function DriverNotificationsPage() {
  const [items, setItems] = useState<NotificationItem[]>([]);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);

  const syncUnreadCount = async () => {
    try {
      const data = await unwrap(
        api.get<ApiResponse<UnreadCountResult>>("/notifications/unread-count"),
      );
      dispatchUnreadSync(data.unread_count || 0);
    } catch {
      return;
    }
  };

  const loadData = async (options?: { syncUnread?: boolean }) => {
    setLoading(true);
    setError("");
    try {
      const data = await unwrap(
        api.get<ApiResponse<PagedList<NotificationItem>>>("/notifications", {
          params: { page: 1, page_size: 100 },
        }),
      );
      setItems(data.items);
      if (options?.syncUnread) {
        await syncUnreadCount();
      }
    } catch (requestError) {
      setError(getErrorMessage(requestError));
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    void loadData({ syncUnread: true });
  }, []);

  const markRead = async (notificationId: number) => {
    try {
      await api.patch(`/notifications/${notificationId}/read`);
      await loadData({ syncUnread: true });
    } catch (requestError) {
      setError(getErrorMessage(requestError));
    }
  };

  const markAllRead = async () => {
    try {
      await api.patch("/notifications/read-all");
      await loadData({ syncUnread: true });
    } catch (requestError) {
      setError(getErrorMessage(requestError));
    }
  };

  return (
    <Panel
      extra={
        <div className="inline-actions">
          <button
            className="ghost-btn"
            onClick={() => void loadData({ syncUnread: true })}
            type="button"
          >
            刷新
          </button>
          <button className="ghost-btn" onClick={() => void markAllRead()} type="button">
            全部已读
          </button>
        </div>
      }
      title="消息通知"
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
                <th>标题</th>
                <th>内容</th>
                <th>状态</th>
                <th>时间</th>
                <th>操作</th>
              </tr>
            </thead>
            <tbody>
              {items.map((item) => {
                const target = resolveTarget(item);
                return (
                  <tr key={item.notification_id}>
                    <td>{item.notification_id}</td>
                    <td>{TYPE_LABELS[item.type] || item.type}</td>
                    <td>
                      <p
                        className={item.is_read ? "notification-title" : "notification-title unread"}
                      >
                        {item.title}
                      </p>
                    </td>
                    <td className="content-cell">{renderContent(item)}</td>
                    <td>{item.is_read ? "已读" : "未读"}</td>
                    <td>{item.created_at}</td>
                    <td>
                      <div className="inline-actions">
                        {target && (
                          <Link className="text-link" to={target.to}>
                            {target.label}
                          </Link>
                        )}
                        {!item.is_read && (
                          <button
                            className="ghost-btn small"
                            onClick={() => void markRead(item.notification_id)}
                            type="button"
                          >
                            标记已读
                          </button>
                        )}
                      </div>
                    </td>
                  </tr>
                );
              })}
              {items.length === 0 && (
                <tr>
                  <td colSpan={7}>暂无通知</td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
      )}
    </Panel>
  );
}
