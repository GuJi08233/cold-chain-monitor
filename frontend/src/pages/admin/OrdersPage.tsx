import { type FormEvent, useEffect, useMemo, useState } from "react";
import { Link } from "react-router-dom";

import { Panel } from "../../components/Panel";
import { api, getErrorMessage, unwrap } from "../../lib/http";
import type { ApiResponse, PagedList } from "../../types/api";

interface OrderItem {
  order_id: string;
  device_id: string;
  driver_id: number;
  cargo_name: string;
  origin: string;
  destination: string;
  planned_start: string;
  status: string;
  created_at: string;
  is_archived: boolean;
  archive_reason: string | null;
  archived_at: string | null;
}

interface DriverProfile {
  real_name: string;
  plate_number: string;
}

interface DriverItem {
  user_id: number;
  username: string;
  display_name?: string | null;
  driver_profile: DriverProfile | null;
  bound_device_id: string | null;
}

interface DeviceItem {
  device_id: string;
  name: string;
  driver_id: number | null;
  status: string;
}

interface CargoItemForm {
  name: string;
  type: string;
  weight: string;
  quantity: string;
  remark: string;
}

interface NewOrderForm {
  device_id: string;
  driver_id: string;
  cargo_name: string;
  cargo_items: CargoItemForm[];
  origin: string;
  destination: string;
  planned_start: string;
  temperature_min: string;
  temperature_max: string;
  humidity_min: string;
  humidity_max: string;
  pressure_min: string;
  pressure_max: string;
}

function createEmptyCargoItem(): CargoItemForm {
  return {
    name: "",
    type: "",
    weight: "",
    quantity: "",
    remark: "",
  };
}

const initialForm: NewOrderForm = {
  device_id: "",
  driver_id: "",
  cargo_name: "",
  cargo_items: [createEmptyCargoItem()],
  origin: "",
  destination: "",
  planned_start: "",
  temperature_min: "",
  temperature_max: "",
  humidity_min: "",
  humidity_max: "",
  pressure_min: "",
  pressure_max: "",
};

function resolveDriverName(driver: DriverItem): string {
  return driver.display_name || driver.driver_profile?.real_name || driver.username;
}

function resolveDriverText(driver: DriverItem): string {
  const base = resolveDriverName(driver);
  const plate = driver.driver_profile?.plate_number;
  if (plate) {
    return `${base} (${plate})`;
  }
  return base;
}

function toThresholdValue(raw: string, label: string): number | undefined {
  const text = raw.trim();
  if (!text) {
    return undefined;
  }
  const parsed = Number(text);
  if (Number.isNaN(parsed)) {
    throw new Error(`${label}必须是数字`);
  }
  return parsed;
}

function buildRule(
  metric: "temperature" | "humidity" | "pressure",
  minRaw: string,
  maxRaw: string,
  minLabel: string,
  maxLabel: string,
) {
  const minValue = toThresholdValue(minRaw, minLabel);
  const maxValue = toThresholdValue(maxRaw, maxLabel);
  if (minValue === undefined && maxValue === undefined) {
    return null;
  }
  if (minValue !== undefined && maxValue !== undefined && minValue > maxValue) {
    throw new Error(`${minLabel}不能大于${maxLabel}`);
  }
  return {
    metric,
    min_value: minValue,
    max_value: maxValue,
  };
}

function normalizeCargoItems(items: CargoItemForm[]): CargoItemForm[] {
  return items
    .map((item) => ({
      name: item.name.trim(),
      type: item.type.trim(),
      weight: item.weight.trim(),
      quantity: item.quantity.trim(),
      remark: item.remark.trim(),
    }))
    .filter((item) => item.name || item.type || item.weight || item.quantity || item.remark);
}

export function OrdersPage() {
  const [orders, setOrders] = useState<OrderItem[]>([]);
  const [drivers, setDrivers] = useState<DriverItem[]>([]);
  const [devices, setDevices] = useState<DeviceItem[]>([]);
  const [status, setStatus] = useState("");
  const [search, setSearch] = useState("");
  const [driverFilterId, setDriverFilterId] = useState("");
  const [deviceFilterId, setDeviceFilterId] = useState("");
  const [loading, setLoading] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState("");
  const [form, setForm] = useState<NewOrderForm>(initialForm);

  const driverMap = useMemo(() => {
    const map = new Map<number, DriverItem>();
    drivers.forEach((item) => map.set(item.user_id, item));
    return map;
  }, [drivers]);

  const deviceMap = useMemo(() => {
    const map = new Map<string, DeviceItem>();
    devices.forEach((item) => map.set(item.device_id, item));
    return map;
  }, [devices]);

  const selectedDriver = useMemo(() => {
    if (!form.driver_id) {
      return null;
    }
    const userId = Number(form.driver_id);
    return drivers.find((item) => item.user_id === userId) || null;
  }, [drivers, form.driver_id]);

  const selectedDriverDevice = useMemo(() => {
    if (!selectedDriver) {
      return null;
    }
    if (selectedDriver.bound_device_id) {
      const found = deviceMap.get(selectedDriver.bound_device_id);
      if (found) {
        return found;
      }
      return {
        device_id: selectedDriver.bound_device_id,
        name: "未知设备",
        driver_id: selectedDriver.user_id,
        status: "unknown",
      };
    }
    const fallback = devices.find((item) => item.driver_id === selectedDriver.user_id);
    return fallback || null;
  }, [selectedDriver, deviceMap, devices]);

  const loadOrders = async () => {
    setLoading(true);
    setError("");
    try {
      const data = await unwrap(
        api.get<ApiResponse<PagedList<OrderItem>>>("/orders", {
          params: {
            page: 1,
            page_size: 100,
            status: status || undefined,
            search: search || undefined,
            driver_id: driverFilterId ? Number(driverFilterId) : undefined,
            device_id: deviceFilterId || undefined,
          },
        }),
      );
      setOrders(data.items);
    } catch (requestError) {
      setError(getErrorMessage(requestError));
    } finally {
      setLoading(false);
    }
  };

  const loadDependencies = async () => {
    try {
      const [driverData, deviceData] = await Promise.all([
        unwrap(
          api.get<ApiResponse<PagedList<DriverItem>>>("/users", {
            params: { role: "driver", status: "active", page: 1, page_size: 100 },
          }),
        ),
        unwrap(api.get<ApiResponse<DeviceItem[]>>("/devices")),
      ]);
      setDrivers(driverData.items);
      setDevices(deviceData);
    } catch (requestError) {
      setError(getErrorMessage(requestError));
    }
  };

  useEffect(() => {
    void loadOrders();
  }, [status, search, driverFilterId, deviceFilterId]);

  useEffect(() => {
    void loadDependencies();
  }, []);

  useEffect(() => {
    if (selectedDriverDevice) {
      setForm((prev) => ({ ...prev, device_id: selectedDriverDevice.device_id }));
      return;
    }
    if (!form.driver_id) {
      setForm((prev) => ({ ...prev, device_id: "" }));
    }
  }, [selectedDriverDevice, form.driver_id]);

  const updateForm = (key: keyof NewOrderForm, value: string) => {
    setForm((prev) => ({ ...prev, [key]: value }));
  };

  const addCargoItem = () => {
    setForm((prev) => ({
      ...prev,
      cargo_items: [...prev.cargo_items, createEmptyCargoItem()],
    }));
  };

  const removeCargoItem = (index: number) => {
    setForm((prev) => {
      const nextItems = prev.cargo_items.filter((_, idx) => idx !== index);
      return {
        ...prev,
        cargo_items: nextItems.length > 0 ? nextItems : [createEmptyCargoItem()],
      };
    });
  };

  const updateCargoItem = (index: number, key: keyof CargoItemForm, value: string) => {
    setForm((prev) => ({
      ...prev,
      cargo_items: prev.cargo_items.map((item, idx) =>
        idx === index ? { ...item, [key]: value } : item,
      ),
    }));
  };

  const changeDriver = (value: string) => {
    setForm((prev) => ({ ...prev, driver_id: value, device_id: "" }));
  };

  const createOrder = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (!form.device_id) {
      setError("该司机暂无绑定设备，请先在设备管理中绑定设备");
      return;
    }
    setSubmitting(true);
    setError("");
    try {
      const rules = [
        buildRule(
          "temperature",
          form.temperature_min,
          form.temperature_max,
          "温度最小阈值",
          "温度最大阈值",
        ),
        buildRule(
          "humidity",
          form.humidity_min,
          form.humidity_max,
          "湿度最小阈值",
          "湿度最大阈值",
        ),
        buildRule(
          "pressure",
          form.pressure_min,
          form.pressure_max,
          "气压最小阈值",
          "气压最大阈值",
        ),
      ].filter((item) => item !== null);

      const cargoItems = normalizeCargoItems(form.cargo_items);
      const cargoInfo: Record<string, unknown> | null =
        cargoItems.length > 0 ? { items: cargoItems } : null;

      await api.post<ApiResponse<OrderItem>>("/orders", {
        device_id: form.device_id,
        driver_id: Number(form.driver_id),
        cargo_name: form.cargo_name.trim(),
        cargo_info: cargoInfo,
        origin: form.origin.trim(),
        destination: form.destination.trim(),
        planned_start: form.planned_start,
        alert_rules: rules,
      });
      setForm(initialForm);
      await loadOrders();
    } catch (requestError) {
      setError(getErrorMessage(requestError));
    } finally {
      setSubmitting(false);
    }
  };

  const cancelOrder = async (orderId: string) => {
    const ok = window.confirm(`确认取消运单 ${orderId} 吗？`);
    if (!ok) {
      return;
    }
    try {
      await api.patch<ApiResponse<OrderItem>>(`/orders/${orderId}/cancel`);
      await loadOrders();
    } catch (requestError) {
      setError(getErrorMessage(requestError));
    }
  };

  return (
    <div className="page-grid">
      <Panel title="创建运单">
        <form className="form-grid triple" onSubmit={createOrder}>
          <label>
            选择司机
            <select onChange={(event) => changeDriver(event.target.value)} required value={form.driver_id}>
              <option value="">请选择司机</option>
              {drivers.map((driver) => (
                <option key={driver.user_id} value={driver.user_id}>
                  {resolveDriverText(driver)}
                </option>
              ))}
            </select>
          </label>
          <label>
            关联设备
            <select disabled onChange={(event) => updateForm("device_id", event.target.value)} required value={form.device_id}>
              <option value="">自动关联司机绑定设备</option>
              {selectedDriverDevice && (
                <option value={selectedDriverDevice.device_id}>
                  {selectedDriverDevice.device_id} / {selectedDriverDevice.name}
                </option>
              )}
            </select>
          </label>
          <label>
            货物名称
            <input
              onChange={(event) => updateForm("cargo_name", event.target.value)}
              required
              value={form.cargo_name}
            />
          </label>
          <label>
            出发地
            <input onChange={(event) => updateForm("origin", event.target.value)} required value={form.origin} />
          </label>
          <label>
            目的地
            <input
              onChange={(event) => updateForm("destination", event.target.value)}
              required
              value={form.destination}
            />
          </label>
          <label>
            计划出发时间
            <input
              onChange={(event) => updateForm("planned_start", event.target.value)}
              required
              type="datetime-local"
              value={form.planned_start}
            />
          </label>
          <label>
            温度最小阈值
            <input
              onChange={(event) => updateForm("temperature_min", event.target.value)}
              type="number"
              value={form.temperature_min}
            />
          </label>
          <label>
            温度最大阈值
            <input
              onChange={(event) => updateForm("temperature_max", event.target.value)}
              type="number"
              value={form.temperature_max}
            />
          </label>
          <label>
            湿度最小阈值
            <input
              onChange={(event) => updateForm("humidity_min", event.target.value)}
              type="number"
              value={form.humidity_min}
            />
          </label>
          <label>
            湿度最大阈值
            <input
              onChange={(event) => updateForm("humidity_max", event.target.value)}
              type="number"
              value={form.humidity_max}
            />
          </label>
          <label>
            气压最小阈值
            <input
              onChange={(event) => updateForm("pressure_min", event.target.value)}
              type="number"
              value={form.pressure_min}
            />
          </label>
          <label>
            气压最大阈值
            <input
              onChange={(event) => updateForm("pressure_max", event.target.value)}
              type="number"
              value={form.pressure_max}
            />
          </label>
          <div className="full-row cargo-items-editor">
            <div className="cargo-items-head">
              <strong>货物明细（可选）</strong>
              <button className="ghost-btn small" onClick={addCargoItem} type="button">
                添加货物
              </button>
            </div>
            <div className="cargo-items-list">
              {form.cargo_items.map((item, index) => (
                <div className="cargo-item-row" key={`cargo-item-${index}`}>
                  <input
                    onChange={(event) => updateCargoItem(index, "name", event.target.value)}
                    placeholder="货物名称"
                    value={item.name}
                  />
                  <input
                    onChange={(event) => updateCargoItem(index, "type", event.target.value)}
                    placeholder="类型（如：疫苗/冻品）"
                    value={item.type}
                  />
                  <input
                    onChange={(event) => updateCargoItem(index, "weight", event.target.value)}
                    placeholder="重量（如：1.2 吨）"
                    value={item.weight}
                  />
                  <input
                    onChange={(event) => updateCargoItem(index, "quantity", event.target.value)}
                    placeholder="数量（如：40 箱）"
                    value={item.quantity}
                  />
                  <input
                    onChange={(event) => updateCargoItem(index, "remark", event.target.value)}
                    placeholder="备注"
                    value={item.remark}
                  />
                  <button
                    className="ghost-btn small"
                    onClick={() => removeCargoItem(index)}
                    type="button"
                  >
                    删除
                  </button>
                </div>
              ))}
            </div>
            <p className="muted">提交后按结构化字段保存，不再需要手写 JSON。</p>
          </div>
          {form.driver_id && !form.device_id && (
            <p className="muted full-row">当前司机未绑定设备，请先在设备管理完成绑定</p>
          )}
          {error && <p className="error-text full-row">{error}</p>}
          <button className="primary-btn full-row" disabled={submitting || !form.device_id} type="submit">
            {submitting ? "提交中..." : "创建运单"}
          </button>
        </form>
      </Panel>

      <Panel
        extra={
          <div className="toolbar-inline">
            <select onChange={(event) => setStatus(event.target.value)} value={status}>
              <option value="">全部状态</option>
              <option value="pending">待出发</option>
              <option value="in_transit">运输中</option>
              <option value="completed">已完成</option>
              <option value="abnormal_closed">异常关闭</option>
              <option value="cancelled">已取消</option>
            </select>
            <select onChange={(event) => setDriverFilterId(event.target.value)} value={driverFilterId}>
              <option value="">全部司机</option>
              {drivers.map((driver) => (
                <option key={`filter-driver-${driver.user_id}`} value={driver.user_id}>
                  {resolveDriverText(driver)}
                </option>
              ))}
            </select>
            <select onChange={(event) => setDeviceFilterId(event.target.value)} value={deviceFilterId}>
              <option value="">全部设备</option>
              {devices.map((device) => (
                <option key={`filter-device-${device.device_id}`} value={device.device_id}>
                  {device.device_id}
                </option>
              ))}
            </select>
            <input
              onChange={(event) => setSearch(event.target.value)}
              placeholder="按运单号搜索"
              value={search}
            />
            <button className="ghost-btn" onClick={() => void loadOrders()} type="button">
              刷新
            </button>
          </div>
        }
        title="运单列表"
      >
        {loading ? (
          <p className="muted">加载中...</p>
        ) : (
          <div className="table-wrap">
            <table>
              <thead>
                <tr>
                  <th>运单号</th>
                  <th>司机</th>
                  <th>设备</th>
                  <th>货物</th>
                  <th>起止地</th>
                  <th>状态</th>
                  <th>归档</th>
                  <th>创建时间</th>
                  <th>计划出发</th>
                  <th>操作</th>
                </tr>
              </thead>
              <tbody>
                {orders.map((item) => {
                  const driver = driverMap.get(item.driver_id);
                  return (
                    <tr key={item.order_id}>
                      <td>{item.order_id}</td>
                      <td>{driver ? resolveDriverText(driver) : item.driver_id}</td>
                      <td>{item.device_id}</td>
                      <td>{item.cargo_name}</td>
                      <td>
                        {item.origin} → {item.destination}
                      </td>
                      <td>{item.status}</td>
                      <td>
                        {item.is_archived ? (
                          <span title={item.archive_reason || "测试归档"}>
                            已归档{item.archive_reason ? ` / ${item.archive_reason}` : ""}
                          </span>
                        ) : (
                          "-"
                        )}
                      </td>
                      <td>{item.created_at || "-"}</td>
                      <td>{item.planned_start}</td>
                      <td>
                        <div className="inline-actions">
                          <Link className="text-link" to={`/admin/orders/${item.order_id}`}>
                            详情
                          </Link>
                          {item.status !== "completed" &&
                            item.status !== "cancelled" &&
                            item.status !== "abnormal_closed" && (
                              <button
                                className="danger-link"
                                onClick={() => void cancelOrder(item.order_id)}
                                type="button"
                              >
                                取消
                              </button>
                            )}
                        </div>
                      </td>
                    </tr>
                  );
                })}
                {orders.length === 0 && (
                  <tr>
                    <td colSpan={10}>暂无运单</td>
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
