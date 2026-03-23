import { useEffect, useMemo, useState } from "react";
import { NavLink, Outlet, useLocation } from "react-router-dom";

import { buildWsUrl } from "../config/env";
import { clearAuth, getAuth } from "../lib/auth";
import { api, unwrap } from "../lib/http";
import { NOTIFICATION_SYNC_EVENT } from "../lib/notifications";
import { issueWsTicket } from "../lib/wsTicket";
import type { ApiResponse } from "../types/api";

interface NavItem {
  path: string;
  label: string;
  superOnly?: boolean;
  hasUnreadBadge?: boolean;
}

interface AppShellProps {
  section: "admin" | "driver";
}

type NotificationWsState =
  | "stopped"
  | "connecting"
  | "connected"
  | "reconnecting"
  | "error";

interface UnreadCountResult {
  unread_count: number;
}

const adminItems: NavItem[] = [
  { path: "/admin/dashboard", label: "仪表盘" },
  { path: "/admin/orders", label: "运单管理" },
  { path: "/admin/devices", label: "设备管理" },
  { path: "/admin/drivers", label: "司机审批" },
  { path: "/admin/anomalies", label: "异常记录" },
  { path: "/admin/chain", label: "区块链记录" },
  { path: "/admin/tickets", label: "工单管理" },
  { path: "/admin/users", label: "用户管理", superOnly: true },
  { path: "/admin/config", label: "系统配置", superOnly: true },
];

const driverItems: NavItem[] = [
  { path: "/driver/orders", label: "我的运单" },
  { path: "/driver/notifications", label: "消息通知", hasUnreadBadge: true },
  { path: "/driver/tickets", label: "我的工单" },
  { path: "/driver/profile", label: "个人中心" },
];

const WS_NO_RETRY_CODES = new Set([4001]);

function resolveTitle(pathname: string): string {
  const allItems = [...adminItems, ...driverItems];
  const matched = allItems.find((item) => pathname.startsWith(item.path));
  return matched?.label || "冷链监控平台";
}

function toWsStateText(state: NotificationWsState, retries: number): string {
  if (state === "connecting") {
    return "连接中";
  }
  if (state === "connected") {
    return "已连接";
  }
  if (state === "reconnecting") {
    return `重连中（第 ${retries} 次）`;
  }
  if (state === "error") {
    return "连接异常";
  }
  return "未连接";
}

export function AppShell(props: AppShellProps) {
  const auth = getAuth();
  const location = useLocation();
  const [unreadCount, setUnreadCount] = useState(0);
  const [wsState, setWsState] = useState<NotificationWsState>("stopped");
  const [wsRetries, setWsRetries] = useState(0);

  const items = props.section === "admin" ? adminItems : driverItems;
  const visibleItems =
    auth?.role === "super_admin"
      ? items
      : items.filter((item) => !item.superOnly);

  const showNotificationStatus = props.section === "driver";

  const loadUnreadCount = async () => {
    if (!auth?.token || props.section !== "driver") {
      setUnreadCount(0);
      return;
    }
    try {
      const data = await unwrap(
        api.get<ApiResponse<UnreadCountResult>>("/notifications/unread-count"),
      );
      setUnreadCount(data.unread_count || 0);
    } catch {
      return;
    }
  };

  useEffect(() => {
    void loadUnreadCount();
    const syncUnread = (event: Event) => {
      const custom = event as CustomEvent<{ count?: number }>;
      if (typeof custom.detail?.count === "number") {
        setUnreadCount(Math.max(0, Math.floor(custom.detail.count)));
      }
    };
    window.addEventListener(NOTIFICATION_SYNC_EVENT, syncUnread as EventListener);
    return () => {
      window.removeEventListener(NOTIFICATION_SYNC_EVENT, syncUnread as EventListener);
    };
  }, [auth?.token, props.section]);

  useEffect(() => {
    if (props.section !== "driver" || !auth?.token) {
      setWsState("stopped");
      setWsRetries(0);
      return;
    }

    let disposed = false;
    let retryCount = 0;
    let socket: WebSocket | null = null;
    let retryTimer: number | undefined;
    let heartbeatTimer: number | undefined;

    const connect = async () => {
      if (disposed) {
        return;
      }
      setWsState(retryCount === 0 ? "connecting" : "reconnecting");
      let ticket = "";
      try {
        ticket = await issueWsTicket("notifications");
      } catch {
        if (disposed) {
          return;
        }
        retryCount += 1;
        setWsRetries(retryCount);
        setWsState("reconnecting");
        const delayMs = Math.min(10000, 1000 * 2 ** Math.min(retryCount, 4));
        retryTimer = window.setTimeout(() => {
          void connect();
        }, delayMs);
        return;
      }
      if (disposed) {
        return;
      }

      socket = new WebSocket(buildWsUrl("/notifications", { ticket }));

      socket.onopen = () => {
        retryCount = 0;
        setWsRetries(0);
        setWsState("connected");
        void loadUnreadCount();
        heartbeatTimer = window.setInterval(() => {
          if (socket?.readyState === WebSocket.OPEN) {
            socket.send("ping");
          }
        }, 20000);
      };

      socket.onmessage = (event) => {
        try {
          const payload = JSON.parse(event.data) as {
            type?: string;
            data?: { is_read?: boolean };
          };
          if (payload.type === "notification" && payload.data?.is_read === false) {
            setUnreadCount((prev) => prev + 1);
          }
        } catch {
          return;
        }
      };

      socket.onerror = () => {
        if (!disposed) {
          setWsState("error");
        }
      };

      socket.onclose = (event) => {
        if (heartbeatTimer) {
          window.clearInterval(heartbeatTimer);
          heartbeatTimer = undefined;
        }
        if (disposed) {
          return;
        }
        if (WS_NO_RETRY_CODES.has(event.code)) {
          setWsState("error");
          return;
        }
        retryCount += 1;
        setWsRetries(retryCount);
        setWsState("reconnecting");
        const delayMs = Math.min(10000, 1000 * 2 ** Math.min(retryCount, 4));
        retryTimer = window.setTimeout(() => {
          void connect();
        }, delayMs);
      };
    };

    void connect();

    return () => {
      disposed = true;
      if (retryTimer) {
        window.clearTimeout(retryTimer);
      }
      if (heartbeatTimer) {
        window.clearInterval(heartbeatTimer);
      }
      if (
        socket &&
        (socket.readyState === WebSocket.OPEN ||
          socket.readyState === WebSocket.CONNECTING)
      ) {
        socket.close(1000, "app-shell-unmount");
      }
      setWsState("stopped");
      setWsRetries(0);
    };
  }, [auth?.token, props.section]);

  const handleLogout = () => {
    clearAuth();
    window.location.href = "/login";
  };

  const wsStateClass = useMemo(() => {
    if (wsState === "connected") {
      return "connected";
    }
    if (wsState === "error") {
      return "error";
    }
    if (wsState === "reconnecting" || wsState === "connecting") {
      return "pending";
    }
    return "stopped";
  }, [wsState]);

  return (
    <div className={props.section === "driver" ? "shell-root driver-shell" : "shell-root"}>
      <aside className="shell-sidebar">
        <div className="brand-box">
          <strong>Cold Chain</strong>
          <span>基于以太坊的冷链监控</span>
        </div>
        <nav className="menu-list">
          {visibleItems.map((item) => (
            <NavLink
              key={item.path}
              className={({ isActive }) =>
                isActive ? "menu-link active" : "menu-link"
              }
              to={item.path}
            >
              <span className="menu-link-label">{item.label}</span>
              {item.hasUnreadBadge && unreadCount > 0 && (
                <span className="menu-badge">
                  {unreadCount > 99 ? "99+" : unreadCount}
                </span>
              )}
            </NavLink>
          ))}
        </nav>
      </aside>

      <section className="shell-main">
        <header className="topbar">
          <div>
            <h1>{resolveTitle(location.pathname)}</h1>
            <p>{auth?.displayName || auth?.username || "未登录"}</p>
            {showNotificationStatus && (
              <p className={`ws-indicator ${wsStateClass}`}>
                通知通道: {toWsStateText(wsState, wsRetries)}
              </p>
            )}
          </div>
          <button className="ghost-btn" onClick={handleLogout} type="button">
            退出登录
          </button>
        </header>
        <main className="page-content">
          <Outlet />
        </main>
      </section>

      {props.section === "driver" && (
        <nav className="mobile-tabbar">
          {visibleItems.map((item) => (
            <NavLink
              key={`mobile-${item.path}`}
              className={({ isActive }) =>
                isActive ? "mobile-tab-link active" : "mobile-tab-link"
              }
              to={item.path}
            >
              <span>{item.label}</span>
              {item.hasUnreadBadge && unreadCount > 0 && (
                <span className="menu-badge">{unreadCount > 99 ? "99+" : unreadCount}</span>
              )}
            </NavLink>
          ))}
        </nav>
      )}
    </div>
  );
}
