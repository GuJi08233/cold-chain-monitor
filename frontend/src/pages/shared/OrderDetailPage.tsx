import {
  Suspense,
  lazy,
  startTransition,
  useCallback,
  useEffect,
  useMemo,
  useState,
} from "react";
import type { EChartsOption } from "echarts";
import { Link, useParams, useSearchParams } from "react-router-dom";

import { Panel } from "../../components/Panel";
import { buildWsUrl } from "../../config/env";
import { getAuth } from "../../lib/auth";
import { api, getErrorMessage, unwrap } from "../../lib/http";
import { issueWsTicket } from "../../lib/wsTicket";
import type { ApiResponse } from "../../types/api";

const EChart = lazy(() =>
  import("../../components/charts/EChart").then((module) => ({
    default: module.EChart,
  })),
);
const TrackMap = lazy(() =>
  import("../../components/maps/TrackMap").then((module) => ({
    default: module.TrackMap,
  })),
);

type MetricKey = "temperature" | "humidity" | "pressure";
type MonitorMode = "realtime" | "recent" | "custom";
type IntervalMode = "auto" | "raw" | "1m" | "5m" | "10m" | "1h";
type WsState = "stopped" | "connecting" | "connected" | "reconnecting" | "error";

interface AlertRuleItem {
  rule_id: number;
  metric: MetricKey;
  min_value: number | null;
  max_value: number | null;
}

interface OrderDetail {
  order_id: string;
  device_id: string;
  driver_id: number;
  cargo_name: string;
  cargo_info: Record<string, unknown> | null;
  origin: string;
  destination: string;
  planned_start: string;
  actual_start: string | null;
  actual_end: string | null;
  status: string;
  data_hash: string | null;
  is_archived: boolean;
  archive_reason: string | null;
  archived_at: string | null;
  archived_by: number | null;
  archived_by_name: string | null;
  alert_rules: AlertRuleItem[];
}

interface AnomalyItem {
  anomaly_id: number;
  metric: MetricKey;
  trigger_value: number;
  threshold_min: number | null;
  threshold_max: number | null;
  status: string;
  peak_value: number | null;
  start_time: string;
  end_time: string | null;
}

interface SensorLatest {
  ts: string;
  temperature: number | null;
  humidity: number | null;
  pressure: number | null;
  gps_lat?: number | null;
  gps_lng?: number | null;
  uptime?: number | null;
}

interface HashVerify {
  local_hash: string | null;
  stored_hash: string | null;
  chain_hash: string | null;
  match: boolean;
  local_hash_changed: boolean;
}

interface SensorMetricPoint {
  ts: string;
  value?: number | null;
  avg?: number | null;
  min?: number | null;
  max?: number | null;
}

interface SensorPayload {
  order_id: string;
  mode: string;
  interval: string;
  total_points: number;
  metrics: Record<MetricKey, SensorMetricPoint[]>;
}

interface MonitorSummary {
  sensor_total_points: number;
  track_total_points: number;
  track_total_distance_meters: number;
}

interface LatestPayload {
  latest: SensorLatest | null;
  summary: MonitorSummary;
}

interface TrackPoint {
  ts: string;
  lat: number | null;
  lng: number | null;
}

interface TrackPayload {
  order_id: string;
  points: TrackPoint[];
}

interface WsSensorMessage {
  type: "sensor_data";
  data: SensorLatest & { order_id: string };
}

interface GeoTrackPoint {
  ts: string;
  lat: number;
  lng: number;
}

interface AnomalyGeoPoint extends GeoTrackPoint {
  anomalyId: number;
  metric: string;
  status: string;
}

interface CargoInfoItem {
  name: string;
  type: string;
  weight: string;
  quantity: string;
  remark: string;
}

const METRIC_UNITS: Record<MetricKey, string> = {
  temperature: "°C",
  humidity: "%",
  pressure: "hPa",
};

const METRIC_LABELS: Record<MetricKey, string> = {
  temperature: "温度",
  humidity: "湿度",
  pressure: "气压",
};

const STATUS_LABELS: Record<string, string> = {
  pending: "待出发",
  in_transit: "运输中",
  completed: "已完成",
  abnormal_closed: "异常关闭",
  cancelled: "已取消",
};

const STATUS_TONES: Record<string, string> = {
  pending: "pending",
  in_transit: "active",
  completed: "success",
  abnormal_closed: "danger",
  cancelled: "muted",
};

const EMPTY_METRICS: Record<MetricKey, SensorMetricPoint[]> = {
  temperature: [],
  humidity: [],
  pressure: [],
};

const WS_NO_RETRY_CODES = new Set([4001, 4003, 4004]);

function toMillis(rawTs: string): number {
  const normalized = rawTs.includes("T") ? rawTs : rawTs.replace(" ", "T");
  const value = Date.parse(normalized);
  return Number.isNaN(value) ? Date.now() : value;
}

function toChartValue(point: SensorMetricPoint): number | null {
  if (typeof point.value === "number") {
    return point.value;
  }
  if (typeof point.avg === "number") {
    return point.avg;
  }
  return null;
}

function inAnomalyWindow(ts: number, anomaly: AnomalyItem): boolean {
  const start = toMillis(anomaly.start_time);
  const end = anomaly.end_time ? toMillis(anomaly.end_time) : Date.now();
  return ts >= start && ts <= end;
}

function toDateTimeLocalText(date: Date): string {
  const year = date.getFullYear();
  const month = String(date.getMonth() + 1).padStart(2, "0");
  const day = String(date.getDate()).padStart(2, "0");
  const hour = String(date.getHours()).padStart(2, "0");
  const minute = String(date.getMinutes()).padStart(2, "0");
  return `${year}-${month}-${day}T${hour}:${minute}`;
}

function toDateTimeLocalValue(value: string | null | undefined): string {
  if (!value) {
    return "";
  }
  const normalized = value.includes("T") ? value : value.replace(" ", "T");
  const date = new Date(normalized);
  if (Number.isNaN(date.getTime())) {
    return "";
  }
  return toDateTimeLocalText(date);
}

function findNearestTrackPoint(points: GeoTrackPoint[], targetTs: number): GeoTrackPoint | null {
  if (!points.length) {
    return null;
  }
  let nearest = points[0];
  let bestGap = Math.abs(toMillis(points[0].ts) - targetTs);
  for (let idx = 1; idx < points.length; idx += 1) {
    const point = points[idx];
    const gap = Math.abs(toMillis(point.ts) - targetTs);
    if (gap < bestGap) {
      bestGap = gap;
      nearest = point;
    }
  }
  return nearest;
}

function toWsStateText(state: WsState, retries: number): string {
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

function asText(value: unknown): string {
  if (typeof value === "string") {
    return value.trim();
  }
  if (typeof value === "number" && Number.isFinite(value)) {
    return String(value);
  }
  return "";
}

function formatDateTimeText(value: string | null | undefined): string {
  if (!value) {
    return "-";
  }
  const normalized = value.includes("T") ? value : value.replace(" ", "T");
  const time = new Date(normalized);
  if (Number.isNaN(time.getTime())) {
    return value;
  }
  return time.toLocaleString("zh-CN", {
    hour12: false,
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
  });
}

function formatDurationText(
  start: string | null | undefined,
  end: string | null | undefined,
): string {
  if (!start || !end) {
    return "-";
  }
  const diffMs = toMillis(end) - toMillis(start);
  if (diffMs < 0) {
    return "-";
  }
  const totalMinutes = Math.round(diffMs / 60000);
  const days = Math.floor(totalMinutes / (60 * 24));
  const hours = Math.floor((totalMinutes % (60 * 24)) / 60);
  const minutes = totalMinutes % 60;
  if (days > 0) {
    return `${days}天 ${hours}小时 ${minutes}分钟`;
  }
  if (hours > 0) {
    return `${hours}小时 ${minutes}分钟`;
  }
  return `${minutes}分钟`;
}

function calcSegmentDistanceKm(prev: GeoTrackPoint, current: GeoTrackPoint): number {
  const toRadians = (deg: number) => (deg * Math.PI) / 180;
  const latDistance = toRadians(current.lat - prev.lat);
  const lngDistance = toRadians(current.lng - prev.lng);
  const a =
    Math.sin(latDistance / 2) ** 2 +
    Math.cos(toRadians(prev.lat)) *
      Math.cos(toRadians(current.lat)) *
      Math.sin(lngDistance / 2) ** 2;
  return 6371 * 2 * Math.atan2(Math.sqrt(a), Math.sqrt(1 - a));
}

function formatDistanceKmText(totalKm: number): string {
  if (totalKm <= 0) {
    return "-";
  }
  if (totalKm < 1) {
    return `${Math.round(totalKm * 1000)} m`;
  }
  if (totalKm >= 100) {
    return `${totalKm.toFixed(0)} km`;
  }
  return `${totalKm.toFixed(1)} km`;
}

function summarizeAlertRule(rule: AlertRuleItem): string {
  const metricLabel = METRIC_LABELS[rule.metric] || rule.metric;
  const segments: string[] = [];
  if (typeof rule.min_value === "number") {
    segments.push(`≥ ${rule.min_value}${METRIC_UNITS[rule.metric]}`);
  }
  if (typeof rule.max_value === "number") {
    segments.push(`≤ ${rule.max_value}${METRIC_UNITS[rule.metric]}`);
  }
  return `${metricLabel} ${segments.join(" / ")}`;
}

function DeferredBlock(props: { height: number; label: string }) {
  return (
    <div className="deferred-block" style={{ height: props.height }}>
      <span>{props.label}</span>
    </div>
  );
}

export function OrderDetailPage() {
  const params = useParams();
  const [searchParams] = useSearchParams();
  const orderId = params.orderId || "";
  const auth = getAuth();
  const isDriver = auth?.role === "driver";
  const isAdmin = auth?.role === "admin" || auth?.role === "super_admin";
  const isSuperAdmin = auth?.role === "super_admin";

  const [order, setOrder] = useState<OrderDetail | null>(null);
  const [anomalies, setAnomalies] = useState<AnomalyItem[]>([]);
  const [latest, setLatest] = useState<SensorLatest | null>(null);
  const [verify, setVerify] = useState<HashVerify | null>(null);
  const [verifyLoading, setVerifyLoading] = useState(false);
  const [archiveLoading, setArchiveLoading] = useState(false);
  const [metrics, setMetrics] = useState<Record<MetricKey, SensorMetricPoint[]>>(EMPTY_METRICS);
  const [trackPoints, setTrackPoints] = useState<TrackPoint[]>([]);
  const [sensorInterval, setSensorInterval] = useState("raw");
  const [sensorDisplayPointCount, setSensorDisplayPointCount] = useState(0);
  const [sensorTotalPointCount, setSensorTotalPointCount] = useState(0);
  const [trackTotalPointCount, setTrackTotalPointCount] = useState(0);
  const [trackTotalDistanceMeters, setTrackTotalDistanceMeters] = useState(0);
  const [mode, setMode] = useState<MonitorMode>("recent");
  const [intervalMode, setIntervalMode] = useState<IntervalMode>("auto");
  const [recent, setRecent] = useState("1h");
  const [customStart, setCustomStart] = useState(
    toDateTimeLocalText(new Date(Date.now() - 60 * 60 * 1000)),
  );
  const [customEnd, setCustomEnd] = useState(toDateTimeLocalText(new Date()));
  const [loadingBase, setLoadingBase] = useState(false);
  const [loadingMonitor, setLoadingMonitor] = useState(false);
  const [error, setError] = useState("");
  const [selectedAnomalyId, setSelectedAnomalyId] = useState<number | null>(null);
  const [wsState, setWsState] = useState<WsState>("stopped");
  const [wsRetries, setWsRetries] = useState(0);
  const canVerifyHash = order?.status === "completed";
  const isLiveOrder = order?.status === "in_transit";
  const isFinishedOrder =
    order?.status === "completed" ||
    order?.status === "abnormal_closed" ||
    order?.status === "cancelled";

  const targetAnomalyId = useMemo(() => {
    const raw = searchParams.get("anomaly_id");
    if (!raw) {
      return null;
    }
    const parsed = Number(raw);
    if (!Number.isInteger(parsed) || parsed <= 0) {
      return null;
    }
    return parsed;
  }, [searchParams]);

  const monitorAnchorTime = useMemo(() => {
    if (!isFinishedOrder) {
      return null;
    }
    return order?.actual_end || latest?.ts || order?.actual_start || order?.planned_start || null;
  }, [
    isFinishedOrder,
    order?.actual_end,
    order?.actual_start,
    order?.planned_start,
    latest?.ts,
  ]);

  const loadBaseData = useCallback(async () => {
    if (!orderId) {
      return;
    }
    setLoadingBase(true);
    setError("");
    try {
      const [orderData, anomalyData, latestData] = await Promise.all([
        unwrap(api.get<ApiResponse<OrderDetail>>(`/orders/${orderId}`)),
        unwrap(api.get<ApiResponse<AnomalyItem[]>>(`/orders/${orderId}/anomalies`)),
        unwrap(
          api.get<ApiResponse<LatestPayload>>(
            `/monitor/${orderId}/latest`,
          ),
        ),
      ]);
      setOrder(orderData);
      setAnomalies(anomalyData);
      setLatest(latestData.latest);
      setSensorTotalPointCount(latestData.summary?.sensor_total_points || 0);
      setTrackTotalPointCount(latestData.summary?.track_total_points || 0);
      setTrackTotalDistanceMeters(latestData.summary?.track_total_distance_meters || 0);
    } catch (requestError) {
      setError(getErrorMessage(requestError));
    } finally {
      setLoadingBase(false);
    }
  }, [orderId]);

  const loadMonitorData = useCallback(async () => {
    if (!orderId) {
      return;
    }
    if (mode === "custom" && (!customStart || !customEnd)) {
      return;
    }

    setLoadingMonitor(true);
    setError("");
    try {
      const sensorParams =
        mode === "recent"
          ? {
              mode,
              metric: "all",
              recent,
              interval: intervalMode,
              ...(monitorAnchorTime ? { anchor_time: monitorAnchorTime } : {}),
            }
          : mode === "custom"
            ? {
                mode,
                metric: "all",
                start_time: customStart,
                end_time: customEnd,
                interval: intervalMode,
              }
            : { mode, metric: "all", interval: "raw" };

      const trackParams =
        mode === "custom"
          ? {
              start_time: customStart,
              end_time: customEnd,
            }
          : {};

      const [sensorData, trackData] = await Promise.all([
        unwrap(
          api.get<ApiResponse<SensorPayload>>(`/monitor/${orderId}/sensor`, {
            params: sensorParams,
          }),
        ),
        unwrap(
          api.get<ApiResponse<TrackPayload>>(`/monitor/${orderId}/track`, {
            params: trackParams,
          }),
        ),
      ]);

      setMetrics({
        temperature: sensorData.metrics.temperature || [],
        humidity: sensorData.metrics.humidity || [],
        pressure: sensorData.metrics.pressure || [],
      });
      setSensorInterval(sensorData.interval);
      setSensorDisplayPointCount(sensorData.total_points);
      setTrackPoints(trackData.points || []);
    } catch (requestError) {
      setError(getErrorMessage(requestError));
    } finally {
      setLoadingMonitor(false);
    }
  }, [orderId, mode, recent, customStart, customEnd, intervalMode, monitorAnchorTime]);

  useEffect(() => {
    void loadBaseData();
  }, [loadBaseData]);

  useEffect(() => {
    void loadMonitorData();
  }, [loadMonitorData]);

  useEffect(() => {
    if (mode === "realtime" && !isLiveOrder) {
      setMode("recent");
    }
  }, [mode, isLiveOrder]);

  useEffect(() => {
    if (!isFinishedOrder || !order) {
      return;
    }
    const defaultStart = toDateTimeLocalValue(
      order.actual_start || order.planned_start || latest?.ts,
    );
    const defaultEnd = toDateTimeLocalValue(
      order.actual_end || latest?.ts || order.actual_start || order.planned_start,
    );
    if (defaultStart) {
      setCustomStart(defaultStart);
    }
    if (defaultEnd) {
      setCustomEnd(defaultEnd);
    }
  }, [isFinishedOrder, order, latest?.ts]);

  useEffect(() => {
    if (!orderId || !auth?.token || mode !== "realtime" || order?.status !== "in_transit") {
      setWsState("stopped");
      setWsRetries(0);
      return;
    }

    let disposed = false;
    let retryCount = 0;
    let retryTimer: number | undefined;
    let socket: WebSocket | null = null;

    const connect = async () => {
      if (disposed) {
        return;
      }
      setWsState(retryCount === 0 ? "connecting" : "reconnecting");
      let ticket = "";
      try {
        ticket = await issueWsTicket("monitor", orderId);
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
      socket = new WebSocket(buildWsUrl(`/monitor/${orderId}`, { ticket }));

      socket.onopen = () => {
        retryCount = 0;
        setWsRetries(0);
        setWsState("connected");
      };

      socket.onmessage = (event) => {
        try {
          const payload = JSON.parse(event.data) as WsSensorMessage;
          if (payload.type !== "sensor_data") {
            return;
          }
          const data = payload.data;
          startTransition(() => {
            setLatest(data);
            setMetrics((prev) => {
              const appendPoint = (
                key: MetricKey,
                value: number | null | undefined,
              ): SensorMetricPoint[] => {
                const next = [...prev[key], { ts: data.ts, value: value ?? null }];
                return next.length > 300 ? next.slice(next.length - 300) : next;
              };
              const nextMetrics = {
                temperature: appendPoint("temperature", data.temperature),
                humidity: appendPoint("humidity", data.humidity),
                pressure: appendPoint("pressure", data.pressure),
              };
              const maxCount = Math.max(
                nextMetrics.temperature.length,
                nextMetrics.humidity.length,
                nextMetrics.pressure.length,
              );
              setSensorDisplayPointCount(maxCount);
              return nextMetrics;
            });
            setSensorTotalPointCount((prev) => prev + 1);
            setTrackPoints((prev) => {
              if (typeof data.gps_lat !== "number" || typeof data.gps_lng !== "number") {
                return prev;
              }
              const nextPoint = { ts: data.ts, lat: data.gps_lat, lng: data.gps_lng };
              const lastPoint = prev[prev.length - 1];
              if (
                lastPoint &&
                typeof lastPoint.lat === "number" &&
                typeof lastPoint.lng === "number"
              ) {
                const previousPoint = {
                  ts: lastPoint.ts,
                  lat: lastPoint.lat,
                  lng: lastPoint.lng,
                };
                setTrackTotalDistanceMeters((distance) =>
                  distance + Math.round(calcSegmentDistanceKm(previousPoint, nextPoint) * 1000),
                );
              }
              setTrackTotalPointCount((count) => count + 1);
              const next = [...prev, nextPoint];
              return next.length > 500 ? next.slice(next.length - 500) : next;
            });
          });
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
        if (disposed) {
          return;
        }
        if (WS_NO_RETRY_CODES.has(event.code)) {
          setWsState("error");
          setError((prev) => prev || "实时监控鉴权失败，请重新登录后重试");
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
      if (socket && (socket.readyState === WebSocket.OPEN || socket.readyState === WebSocket.CONNECTING)) {
        socket.close(1000, "switch-mode");
      }
      setWsState("stopped");
      setWsRetries(0);
    };
  }, [orderId, auth?.token, mode, order?.status]);

  const verifyHash = async () => {
    if (!orderId || verifyLoading) {
      return;
    }
    setError("");
    setVerify(null);
    setVerifyLoading(true);
    try {
      const data = await unwrap(
        api.get<ApiResponse<HashVerify>>(`/chain/order/${orderId}/verify`),
      );
      setVerify(data);
    } catch (requestError) {
      setError(getErrorMessage(requestError));
    } finally {
      setVerifyLoading(false);
    }
  };

  const toggleArchive = async () => {
    if (!orderId || !order || archiveLoading) {
      return;
    }
    if (!order.is_archived && order.status !== "completed") {
      setError("仅已完成运单支持测试归档");
      return;
    }

    let archived = true;
    let reason = order.archive_reason || "测试归档";
    if (order.is_archived) {
      const ok = window.confirm(`确认取消运单 ${orderId} 的测试归档吗？`);
      if (!ok) {
        return;
      }
      archived = false;
      reason = "";
    } else {
      const input = window.prompt("请输入归档原因（可选）", reason);
      if (input === null) {
        return;
      }
      reason = input.trim() || "测试归档";
    }

    setError("");
    setArchiveLoading(true);
    try {
      const data = await unwrap(
        api.patch<ApiResponse<OrderDetail>>(`/orders/${orderId}/archive`, {
          archived,
          reason,
        }),
      );
      setOrder(data);
    } catch (requestError) {
      setError(getErrorMessage(requestError));
    } finally {
      setArchiveLoading(false);
    }
  };

  const withOrderAction = async (action: "start" | "complete" | "cancel") => {
    if (!orderId) {
      return;
    }
    const confirmText =
      action === "start"
        ? `确认提前出发运单 ${orderId} 吗？`
        : action === "complete"
          ? `确认已到达并完成运单 ${orderId} 吗？\n提交后将进入结算并触发哈希计算。`
          : `确认取消运单 ${orderId} 吗？`;
    const ok = window.confirm(confirmText);
    if (!ok) {
      return;
    }
    setError("");
    try {
      if (action === "cancel") {
        await api.patch(`/orders/${orderId}/cancel`);
      } else {
        await api.patch(`/orders/${orderId}/${action}`);
      }
      await Promise.all([loadBaseData(), loadMonitorData()]);
    } catch (requestError) {
      setError(getErrorMessage(requestError));
    }
  };

  const geoTrackPoints = useMemo<GeoTrackPoint[]>(() => {
    return trackPoints
      .filter(
        (item): item is { ts: string; lat: number; lng: number } =>
          typeof item.lat === "number" && typeof item.lng === "number",
      )
      .map((item) => ({ ts: item.ts, lat: item.lat, lng: item.lng }));
  }, [trackPoints]);

  const anomalyGeoPoints = useMemo<AnomalyGeoPoint[]>(() => {
    return anomalies
      .map((item) => {
        const nearest = findNearestTrackPoint(geoTrackPoints, toMillis(item.start_time));
        if (!nearest) {
          return null;
        }
        return {
          anomalyId: item.anomaly_id,
          metric: METRIC_LABELS[item.metric] || item.metric,
          status: item.status,
          ts: nearest.ts,
          lat: nearest.lat,
          lng: nearest.lng,
        };
      })
      .filter((item): item is AnomalyGeoPoint => item !== null);
  }, [anomalies, geoTrackPoints]);

  const anomalyGeoPointMap = useMemo(() => {
    const map = new Map<number, AnomalyGeoPoint>();
    anomalyGeoPoints.forEach((item) => map.set(item.anomalyId, item));
    return map;
  }, [anomalyGeoPoints]);

  const ongoingAnomalyCount = useMemo(
    () => anomalies.filter((item) => item.status === "ongoing").length,
    [anomalies],
  );
  const cargoInfoItems = useMemo<CargoInfoItem[]>(() => {
    const source = order?.cargo_info;
    if (!source) {
      return [];
    }
    const rawItems = source.items;
    if (!Array.isArray(rawItems)) {
      return [];
    }
    return rawItems
      .map((entry) => {
        if (!entry || typeof entry !== "object" || Array.isArray(entry)) {
          return null;
        }
        const row = entry as Record<string, unknown>;
        const normalized = {
          name: asText(row.name),
          type: asText(row.type),
          weight: asText(row.weight),
          quantity: asText(row.quantity),
          remark: asText(row.remark),
        };
        if (
          !normalized.name &&
          !normalized.type &&
          !normalized.weight &&
          !normalized.quantity &&
          !normalized.remark
        ) {
          return null;
        }
        return normalized;
      })
      .filter((entry): entry is CargoInfoItem => entry !== null);
  }, [order?.cargo_info]);
  const cargoInfoPairs = useMemo(() => {
    const source = order?.cargo_info;
    if (!source) {
      return [];
    }
    return Object.entries(source)
      .filter(([key]) => key !== "items")
      .map(([key, value]) => {
        const text = asText(value);
        if (!text) {
          return null;
        }
        return { key, value: text };
      })
      .filter((entry): entry is { key: string; value: string } => entry !== null);
  }, [order?.cargo_info]);
  const latestLocationText = useMemo(() => {
    if (!latest) {
      return "-";
    }
    if (typeof latest.gps_lat !== "number" || typeof latest.gps_lng !== "number") {
      return "-";
    }
    return `${latest.gps_lat.toFixed(6)}, ${latest.gps_lng.toFixed(6)}`;
  }, [latest]);
  const statusText = useMemo(() => {
    if (!order?.status) {
      return "-";
    }
    return STATUS_LABELS[order.status] || order.status;
  }, [order?.status]);
  const statusTone = useMemo(() => {
    if (!order?.status) {
      return "neutral";
    }
    return STATUS_TONES[order.status] || "neutral";
  }, [order?.status]);
  const latestTrackPoint = useMemo(() => {
    if (!geoTrackPoints.length) {
      return null;
    }
    return geoTrackPoints[geoTrackPoints.length - 1];
  }, [geoTrackPoints]);
  const trackDistanceText = useMemo(
    () => formatDistanceKmText(trackTotalDistanceMeters / 1000),
    [trackTotalDistanceMeters],
  );
  const journeyDurationText = useMemo(() => {
    const startTime = order?.actual_start || order?.planned_start || geoTrackPoints[0]?.ts;
    const endTime = order?.actual_end || latest?.ts || latestTrackPoint?.ts;
    return formatDurationText(startTime, endTime);
  }, [
    order?.actual_start,
    order?.planned_start,
    order?.actual_end,
    latest?.ts,
    latestTrackPoint?.ts,
    geoTrackPoints,
  ]);
  const alertRuleSummary = useMemo(
    () => (order?.alert_rules || []).map((item) => summarizeAlertRule(item)),
    [order?.alert_rules],
  );
  const selectedAnomaly = useMemo(() => {
    if (selectedAnomalyId === null) {
      return null;
    }
    return anomalies.find((item) => item.anomaly_id === selectedAnomalyId) || null;
  }, [selectedAnomalyId, anomalies]);
  const selectedAnomalyGeoPoint = useMemo(() => {
    if (selectedAnomalyId === null) {
      return null;
    }
    return anomalyGeoPointMap.get(selectedAnomalyId) || null;
  }, [selectedAnomalyId, anomalyGeoPointMap]);
  const timePointLabel = isFinishedOrder ? "最后数据时间" : "最新数据时间";
  const dashboardLocationLabel = isFinishedOrder ? "最后定位" : "最近定位";
  const summaryLocationLabel = isFinishedOrder ? "最后定位" : "最新定位";
  const mapTimeLabel = isFinishedOrder ? "最后轨迹时间" : "最新轨迹时间";
  const dashboardTitle = isFinishedOrder ? "监控概览" : "实时仪表盘";

  useEffect(() => {
    if (targetAnomalyId === null) {
      return;
    }
    setSelectedAnomalyId(targetAnomalyId);
  }, [targetAnomalyId]);

  useEffect(() => {
    if (selectedAnomalyId === null || anomalies.length === 0) {
      return;
    }
    const exists = anomalies.some((item) => item.anomaly_id === selectedAnomalyId);
    if (!exists) {
      setSelectedAnomalyId(null);
    }
  }, [selectedAnomalyId, anomalies]);

  const metricOptions = useMemo(() => {
    const buildOption = (metric: MetricKey): EChartsOption => {
      const anomalyRows = anomalies.filter((item) => item.metric === metric);
      const lineData = metrics[metric].map((item) => [
        toMillis(item.ts),
        toChartValue(item),
      ]) as [number, number | null][];

      const anomalyPoints = lineData.filter(([ts, value]) => {
        if (value === null) {
          return false;
        }
        return anomalyRows.some((row) => inAnomalyWindow(ts, row));
      });

      const markAreas: Array<[{ xAxis: number }, { xAxis: number }]> = anomalyRows.map(
        (row) => [
          { xAxis: toMillis(row.start_time) },
          { xAxis: row.end_time ? toMillis(row.end_time) : Date.now() },
        ],
      );

      const matchedRule = order?.alert_rules.find((item) => item.metric === metric);
      const thresholdLines: {
        yAxis: number;
        lineStyle: { color: string; type: "dashed" };
        label: { formatter: string };
      }[] = [];
      if (typeof matchedRule?.max_value === "number") {
        thresholdLines.push({
          yAxis: matchedRule.max_value,
          lineStyle: { color: "#cb3030", type: "dashed" },
          label: { formatter: "上限" },
        });
      }
      if (typeof matchedRule?.min_value === "number") {
        thresholdLines.push({
          yAxis: matchedRule.min_value,
          lineStyle: { color: "#2f79c9", type: "dashed" },
          label: { formatter: "下限" },
        });
      }

      return {
        animation: false,
        color: ["#0e7c86", "#d64045"],
        title: {
          text: `${METRIC_LABELS[metric]}曲线`,
          textStyle: { color: "#173436", fontSize: 14 },
          left: 8,
          top: 4,
        },
        tooltip: {
          trigger: "axis",
          valueFormatter: (value) => {
            if (
              value === null ||
              value === undefined ||
              Number.isNaN(Number(value))
            ) {
              return "-";
            }
            return `${Number(value).toFixed(2)} ${METRIC_UNITS[metric]}`;
          },
        },
        grid: { left: 58, right: 20, top: 40, bottom: 40 },
        xAxis: { type: "time" },
        yAxis: { type: "value", name: METRIC_UNITS[metric] },
        dataZoom: [
          { type: "inside" },
          { type: "slider", height: 16, bottom: 2 },
        ],
        series: [
          {
            type: "line",
            showSymbol: false,
            smooth: 0.15,
            connectNulls: false,
            data: lineData,
            areaStyle: { color: "rgba(14, 124, 134, 0.08)" },
            markArea: markAreas.length
              ? {
                  silent: true,
                  itemStyle: { color: "rgba(214, 64, 69, 0.14)" },
                  data: markAreas,
                }
              : undefined,
            markLine: thresholdLines.length
              ? {
                  silent: true,
                  data: thresholdLines,
                }
              : undefined,
          },
          {
            type: "scatter",
            data: anomalyPoints,
            symbolSize: 7,
            itemStyle: { color: "#d64045" },
          },
        ],
      };
    };

    return {
      temperature: buildOption("temperature"),
      humidity: buildOption("humidity"),
      pressure: buildOption("pressure"),
    };
  }, [metrics, anomalies, order?.alert_rules]);

  if (!orderId) {
    return <p className="error-text">参数错误：缺少运单编号</p>;
  }

  return (
    <div className="page-grid">
      {error && <p className="error-text">{error}</p>}

      <Panel
        extra={
          <div className="inline-actions">
            <button
              className="ghost-btn small"
              onClick={() => void loadBaseData()}
              type="button"
            >
              刷新信息
            </button>
            {isDriver && order?.status === "pending" && (
              <button
                className="ghost-btn small"
                disabled={loadingBase}
                onClick={() => void withOrderAction("start")}
                type="button"
              >
                提前出发
              </button>
            )}
            {isDriver && order?.status === "in_transit" && (
              <button
                className="primary-btn inline"
                disabled={loadingBase}
                onClick={() => void withOrderAction("complete")}
                type="button"
              >
                确认到达
              </button>
            )}
            {isDriver &&
              (order?.status === "pending" || order?.status === "in_transit") && (
                <Link
                  className="ghost-btn small text-link-btn"
                  onClick={(event) => {
                    const ok = window.confirm(
                      `确认要为运单 ${orderId} 提交取消申请吗？`,
                    );
                    if (!ok) {
                      event.preventDefault();
                    }
                  }}
                  to={`/driver/tickets/new?type=cancel_order&order_id=${encodeURIComponent(orderId)}`}
                >
                  申请取消
                </Link>
              )}
            {isDriver &&
              (order?.status === "completed" || order?.status === "abnormal_closed") &&
              anomalies.length > 0 && (
                <Link
                  className="ghost-btn small text-link-btn"
                  to={`/driver/tickets/new?type=anomaly_report&order_id=${encodeURIComponent(orderId)}`}
                >
                  异常申报
                </Link>
              )}
            {isAdmin &&
              (order?.status === "pending" || order?.status === "in_transit") && (
                <button
                  className="danger-link"
                  disabled={loadingBase}
                  onClick={() => void withOrderAction("cancel")}
                  type="button"
                >
                  取消运单
                </button>
              )}
            {isSuperAdmin && order?.status === "completed" && (
              <button
                className="ghost-btn small"
                disabled={archiveLoading}
                onClick={() => void toggleArchive()}
                type="button"
              >
                {archiveLoading ? "处理中..." : order?.is_archived ? "取消归档" : "测试归档"}
              </button>
            )}
          </div>
        }
        title="运单基础信息"
      >
        {order ? (
          <>
            <div className="detail-hero">
              <div className="detail-hero-main">
                <p className="section-kicker">运输任务 / {order.order_id}</p>
                <h3 className="detail-route">
                  <span>{order.origin}</span>
                  <i>→</i>
                  <span>{order.destination}</span>
                </h3>
                <p className="detail-subline">
                  {order.cargo_name} · 设备 {order.device_id} · 司机 #{order.driver_id}
                </p>
              </div>
              <div className="detail-hero-side">
                <span className={`status-badge ${statusTone}`}>{statusText}</span>
                <p>{canVerifyHash ? "已具备链上校验条件" : "运单完成后可验证哈希"}</p>
                {order.is_archived && (
                  <p>
                    已测试归档
                    {order.archive_reason ? ` / ${order.archive_reason}` : ""}
                  </p>
                )}
              </div>
            </div>

            {isSuperAdmin && order.status === "completed" && (
              <p className="muted">
                自动哈希巡检：
                {order.is_archived
                  ? `已跳过${order.archived_at ? `（${order.archived_at}）` : ""}`
                  : "正常参与"}
                {order.is_archived && order.archived_by_name
                  ? `，操作人：${order.archived_by_name}`
                  : ""}
              </p>
            )}

            <div className="detail-summary-grid">
              <article className="info-tile">
                <span>计划出发</span>
                <strong>{formatDateTimeText(order.planned_start)}</strong>
              </article>
              <article className="info-tile">
                <span>实际出发</span>
                <strong>{formatDateTimeText(order.actual_start)}</strong>
              </article>
              <article className="info-tile">
                <span>运行时长</span>
                <strong>{journeyDurationText}</strong>
              </article>
              <article className="info-tile">
                <span>轨迹里程</span>
                <strong>{trackDistanceText}</strong>
              </article>
              <article className="info-tile">
                <span>监控点数</span>
                <strong>{sensorTotalPointCount}</strong>
              </article>
              <article className="info-tile">
                <span>{summaryLocationLabel}</span>
                <strong>{latestLocationText}</strong>
              </article>
            </div>

            {alertRuleSummary.length > 0 && (
              <div className="rule-pill-row">
                {alertRuleSummary.map((item) => (
                  <span className="rule-pill" key={item}>
                    {item}
                  </span>
                ))}
              </div>
            )}

            <div className="key-value-grid detail-meta-grid">
              <p>
                <strong>当前状态:</strong> {statusText}
              </p>
              <p>
                <strong>实际结束:</strong> {formatDateTimeText(order.actual_end)}
              </p>
              <p>
                <strong>{timePointLabel}:</strong> {formatDateTimeText(latest?.ts)}
              </p>
              {isLiveOrder && (
                <p>
                  <strong>实时通道:</strong> {toWsStateText(wsState, wsRetries)}
                </p>
              )}
              <p className="detail-hash-line">
                <strong>数据哈希:</strong> {order.data_hash || "-"}
              </p>
            </div>
            {cargoInfoItems.length > 0 && (
              <div className="cargo-info-block">
                <h3>货物明细</h3>
                <div className="table-wrap">
                  <table>
                    <thead>
                      <tr>
                        <th>名称</th>
                        <th>类型</th>
                        <th>重量</th>
                        <th>数量</th>
                        <th>备注</th>
                      </tr>
                    </thead>
                    <tbody>
                      {cargoInfoItems.map((item, index) => (
                        <tr key={`cargo-detail-${index}`}>
                          <td>{item.name || "-"}</td>
                          <td>{item.type || "-"}</td>
                          <td>{item.weight || "-"}</td>
                          <td>{item.quantity || "-"}</td>
                          <td>{item.remark || "-"}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              </div>
            )}
            {cargoInfoItems.length === 0 && cargoInfoPairs.length > 0 && (
              <div className="cargo-info-block">
                <h3>货物附加信息</h3>
                <div className="cargo-meta-list">
                  {cargoInfoPairs.map((entry) => (
                    <p key={`cargo-meta-${entry.key}`}>
                      <strong>{entry.key}:</strong> {entry.value}
                    </p>
                  ))}
                </div>
              </div>
            )}
          </>
        ) : (
          <p className="muted">加载中...</p>
        )}
      </Panel>

      <Panel title={dashboardTitle}>
        <div className="stats-grid order-dashboard-grid">
          <div className="stat-card">
            <span>温度</span>
            <strong>
              {latest && typeof latest.temperature === "number"
                ? `${latest.temperature.toFixed(2)} °C`
                : "-"}
            </strong>
          </div>
          <div className="stat-card">
            <span>湿度</span>
            <strong>
              {latest && typeof latest.humidity === "number"
                ? `${latest.humidity.toFixed(2)} %`
                : "-"}
            </strong>
          </div>
          <div className="stat-card">
            <span>气压</span>
            <strong>
              {latest && typeof latest.pressure === "number"
                ? `${latest.pressure.toFixed(2)} hPa`
                : "-"}
            </strong>
          </div>
          <div className="stat-card warning">
            <span>异常总数</span>
            <strong>{anomalies.length}</strong>
          </div>
          <div className="stat-card warning">
            <span>进行中异常</span>
            <strong>{ongoingAnomalyCount}</strong>
          </div>
        </div>
        <div className="key-value-grid order-dashboard-meta">
          <p>
            <strong>{timePointLabel}:</strong> {latest?.ts || "-"}
          </p>
          <p>
            <strong>{dashboardLocationLabel}:</strong> {latestLocationText}
          </p>
          <p>
            <strong>轨迹点数:</strong> {trackTotalPointCount}
          </p>
          <p>
            <strong>异常定位点:</strong> {anomalyGeoPoints.length}
          </p>
          <p>
            <strong>监控点数:</strong> {sensorTotalPointCount}
          </p>
          {isLiveOrder && (
            <p>
              <strong>实时通道:</strong> {toWsStateText(wsState, wsRetries)}
            </p>
          )}
        </div>
      </Panel>

      <Panel
        extra={
          <div className="toolbar-inline">
            {isLiveOrder && (
              <button
                className={mode === "realtime" ? "mode-btn active" : "mode-btn"}
                onClick={() => setMode("realtime")}
                type="button"
              >
                实时
              </button>
            )}
            <button
              className={mode === "recent" ? "mode-btn active" : "mode-btn"}
              onClick={() => setMode("recent")}
              type="button"
            >
              最近
            </button>
            <button
              className={mode === "custom" ? "mode-btn active" : "mode-btn"}
              onClick={() => setMode("custom")}
              type="button"
            >
              自定义
            </button>
            {mode === "recent" && (
              <select
                onChange={(event) => setRecent(event.target.value)}
                value={recent}
              >
                <option value="30m">30m</option>
                <option value="1h">1h</option>
                <option value="6h">6h</option>
                <option value="12h">12h</option>
                <option value="24h">24h</option>
              </select>
            )}
            {mode !== "realtime" && (
              <select
                onChange={(event) => setIntervalMode(event.target.value as IntervalMode)}
                value={intervalMode}
              >
                <option value="auto">自动粒度</option>
                <option value="raw">原始点</option>
                <option value="1m">1m</option>
                <option value="5m">5m</option>
                <option value="10m">10m</option>
                <option value="1h">1h</option>
              </select>
            )}
            {mode === "custom" && (
              <>
                <input
                  onChange={(event) => setCustomStart(event.target.value)}
                  type="datetime-local"
                  value={customStart}
                />
                <input
                  onChange={(event) => setCustomEnd(event.target.value)}
                  type="datetime-local"
                  value={customEnd}
                />
              </>
            )}
            <button
              className="ghost-btn small"
              onClick={() => void loadMonitorData()}
              type="button"
            >
              刷新监控
            </button>
          </div>
        }
        title="监控曲线"
      >
        <p className="muted monitor-meta">
          当前粒度: {sensorInterval}
          {mode !== "realtime" ? `（请求：${intervalMode}）` : ""} | 显示点数:{" "}
          {sensorDisplayPointCount} / 总点数: {sensorTotalPointCount}
          {isLiveOrder && (
            <>
              {" "}| WS 状态: {toWsStateText(wsState, wsRetries)}
            </>
          )}
          {loadingMonitor ? " | 加载中..." : ""}
        </p>
        {mode !== "realtime" && sensorInterval !== "raw" && (
          <p className="muted monitor-note">
            当前返回的是聚合数据（每个时间桶一条点），所以点数会比原始采样更少。需要原始点可切换“原始点”。
          </p>
        )}
        {sensorDisplayPointCount < sensorTotalPointCount && (
          <p className="muted monitor-note">
            为保证图表流畅，当前曲线仅渲染部分点位；基础信息中的监控点数显示的是该运单完整总量。
          </p>
        )}
        <Suspense
          fallback={
            <div className="metric-grid">
              <DeferredBlock height={270} label="温度图表加载中..." />
              <DeferredBlock height={270} label="湿度图表加载中..." />
              <DeferredBlock height={270} label="气压图表加载中..." />
            </div>
          }
        >
          <div className="metric-grid">
            <EChart height={270} option={metricOptions.temperature} />
            <EChart height={270} option={metricOptions.humidity} />
            <EChart height={270} option={metricOptions.pressure} />
          </div>
        </Suspense>
      </Panel>

      <Panel title="GPS 轨迹地图">
        <div className="map-summary-grid">
          <article className="info-tile compact">
            <span>轨迹点数</span>
            <strong>{trackTotalPointCount}</strong>
          </article>
          <article className="info-tile compact">
            <span>定位异常</span>
            <strong>{anomalyGeoPoints.length}</strong>
          </article>
          <article className="info-tile compact">
            <span>路线跨度</span>
            <strong>{trackDistanceText}</strong>
          </article>
          <article className="info-tile compact">
            <span>{mapTimeLabel}</span>
            <strong>{formatDateTimeText(latestTrackPoint?.ts || latest?.ts)}</strong>
          </article>
        </div>
        {geoTrackPoints.length < trackTotalPointCount && (
          <p className="muted monitor-note">
            地图为提升渲染性能使用了抽样轨迹；上方轨迹点数与轨迹里程显示的是完整统计值。
          </p>
        )}

        <div className="map-toolbar">
          <div className="map-legend">
            <span className="map-legend-item">
              <i className="legend-dot start" />
              起点
            </span>
            <span className="map-legend-item">
              <i className="legend-dot end" />
              终点 / 最新点
            </span>
            <span className="map-legend-item">
              <i className="legend-dot anomaly" />
              异常点
            </span>
          </div>
          <div className="inline-actions">
            {selectedAnomalyId !== null && (
              <button
                className="ghost-btn small"
                onClick={() => setSelectedAnomalyId(null)}
                type="button"
              >
                重置视角
              </button>
            )}
          </div>
        </div>

        {selectedAnomaly && selectedAnomalyGeoPoint ? (
          <div className="focus-banner">
            <strong>已定位异常 #{selectedAnomaly.anomaly_id}</strong>
            <span>
              {METRIC_LABELS[selectedAnomaly.metric] || selectedAnomaly.metric} · {selectedAnomaly.status}
            </span>
            <span>{formatDateTimeText(selectedAnomaly.start_time)}</span>
            <span>
              {selectedAnomalyGeoPoint.lat.toFixed(6)}, {selectedAnomalyGeoPoint.lng.toFixed(6)}
            </span>
          </div>
        ) : (
          <p className="muted monitor-note">
            点击异常列表中的“定位”或地图红点，可快速聚焦到异常发生位置。
          </p>
        )}
        <Suspense fallback={<DeferredBlock height={420} label="地图加载中..." />}>
          <div className="track-map-shell">
            <TrackMap
              anomalyPoints={anomalyGeoPoints}
              onSelectAnomaly={(anomalyId) => setSelectedAnomalyId(anomalyId)}
              points={geoTrackPoints}
              selectedAnomalyId={selectedAnomalyId}
            />
          </div>
        </Suspense>
      </Panel>

      <Panel
        extra={
          canVerifyHash ? (
            <button
              className="ghost-btn"
              disabled={verifyLoading}
              onClick={() => void verifyHash()}
              type="button"
            >
              {verifyLoading ? "验证中..." : "验证哈希"}
            </button>
          ) : undefined
        }
        title="区块链校验"
      >
        {!canVerifyHash ? (
          <p className="muted">运单完成后才可进行哈希校验</p>
        ) : verifyLoading ? (
          <p className="muted">验证中，正在实时重算 TDengine 本地哈希...</p>
        ) : verify ? (
          <div className={verify.match ? "state-box success" : "state-box danger"}>
            <p>当前本地哈希: {verify.local_hash || "-"}</p>
            <p>完结快照哈希: {verify.stored_hash || "-"}</p>
            <p>链上哈希: {verify.chain_hash || "-"}</p>
            <p>本地数据状态: {verify.local_hash_changed ? "已发生变更" : "未检测到变更"}</p>
            <p>校验结果: {verify.match ? "一致" : "不一致"}</p>
          </div>
        ) : (
          <p className="muted">
            {order?.is_archived
              ? "该运单已测试归档，系统不会自动巡检；如需检查，可手动点击“验证哈希”。"
              : "点击“验证哈希”发起校验"}
          </p>
        )}
      </Panel>

      <Panel title="异常记录">
        <div className="table-wrap">
          <table>
            <thead>
              <tr>
                <th>ID</th>
                <th>指标</th>
                <th>触发值</th>
                <th>阈值</th>
                <th>状态</th>
                <th>峰值</th>
                <th>开始时间</th>
                <th>结束时间</th>
                <th>定位</th>
              </tr>
            </thead>
            <tbody>
              {anomalies.map((item) => {
                const locatable = anomalyGeoPointMap.has(item.anomaly_id);
                const active = item.anomaly_id === selectedAnomalyId;
                return (
                  <tr
                    className={
                      active
                        ? "anomaly-row active"
                        : locatable
                          ? "anomaly-row locatable"
                          : "anomaly-row"
                    }
                    key={item.anomaly_id}
                    onClick={() => {
                      if (locatable) {
                        setSelectedAnomalyId(item.anomaly_id);
                      }
                    }}
                  >
                    <td>{item.anomaly_id}</td>
                    <td>{METRIC_LABELS[item.metric] || item.metric}</td>
                    <td>{item.trigger_value}</td>
                    <td>
                      {item.threshold_min ?? "-"} / {item.threshold_max ?? "-"}
                    </td>
                    <td>{item.status}</td>
                    <td>{item.peak_value ?? "-"}</td>
                    <td>{item.start_time}</td>
                    <td>{item.end_time || "-"}</td>
                    <td>
                      {locatable ? (
                        <button
                          className="ghost-btn small"
                          onClick={() => setSelectedAnomalyId(item.anomaly_id)}
                          type="button"
                        >
                          {active ? "已定位" : "定位"}
                        </button>
                      ) : (
                        <span className="muted">无坐标</span>
                      )}
                    </td>
                  </tr>
                );
              })}
              {anomalies.length === 0 && (
                <tr>
                  <td colSpan={9}>暂无异常记录</td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
      </Panel>
    </div>
  );
}
