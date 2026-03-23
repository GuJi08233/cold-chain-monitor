import { type FormEvent, useEffect, useState } from "react";

import { Panel } from "../../components/Panel";
import { api, getErrorMessage, unwrap } from "../../lib/http";
import type { ApiResponse, PagedList } from "../../types/api";

interface DeviceItem {
  device_id: string;
  name: string;
  status: string;
  driver_id: number | null;
  last_seen: string | null;
  driver?: {
    user_id: number;
    username: string;
    display_name?: string | null;
    status: string;
  } | null;
}

interface DriverItem {
  user_id: number;
  username: string;
  display_name?: string | null;
}

interface DiscoveredDeviceItem {
  device_id: string;
  last_seen: string;
  already_registered: boolean;
}

export function DevicesPage() {
  const [devices, setDevices] = useState<DeviceItem[]>([]);
  const [drivers, setDrivers] = useState<DriverItem[]>([]);
  const [discoveredDevices, setDiscoveredDevices] = useState<DiscoveredDeviceItem[]>([]);
  const [error, setError] = useState("");
  const [newDeviceId, setNewDeviceId] = useState("");
  const [newDeviceName, setNewDeviceName] = useState("");
  const [selectedBind, setSelectedBind] = useState<Record<string, string>>({});
  const [loading, setLoading] = useState(false);

  const loadData = async () => {
    setLoading(true);
    setError("");
    try {
      const [deviceData, driverData, discoveredData] = await Promise.all([
        unwrap(api.get<ApiResponse<DeviceItem[]>>("/devices")),
        unwrap(
          api.get<ApiResponse<PagedList<DriverItem>>>("/users", {
            params: { role: "driver", status: "active", page: 1, page_size: 100 },
          }),
        ),
        unwrap(
          api.get<ApiResponse<DiscoveredDeviceItem[]>>("/devices/discovered", {
            params: { include_registered: false, online_window_seconds: 180 },
          }),
        ),
      ]);
      setDevices(deviceData);
      setDrivers(driverData.items);
      setDiscoveredDevices(discoveredData);
    } catch (requestError) {
      setError(getErrorMessage(requestError));
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    void loadData();
  }, []);

  const createDevice = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    setError("");
    try {
      await api.post("/devices", { device_id: newDeviceId, name: newDeviceName });
      setNewDeviceId("");
      setNewDeviceName("");
      await loadData();
    } catch (requestError) {
      setError(getErrorMessage(requestError));
    }
  };

  const bindDevice = async (deviceId: string) => {
    const selected = selectedBind[deviceId];
    if (!selected) {
      setError("请先选择司机");
      return;
    }
    setError("");
    try {
      await api.patch(`/devices/${deviceId}/bind`, {
        driver_id: Number(selected),
      });
      await loadData();
    } catch (requestError) {
      setError(getErrorMessage(requestError));
    }
  };

  const unbindDevice = async (deviceId: string) => {
    try {
      await api.patch(`/devices/${deviceId}/bind`, { driver_id: null });
      await loadData();
    } catch (requestError) {
      setError(getErrorMessage(requestError));
    }
  };

  const deleteDevice = async (deviceId: string) => {
    const ok = window.confirm(`确认删除设备 ${deviceId} 吗？`);
    if (!ok) {
      return;
    }
    try {
      await api.delete(`/devices/${deviceId}`);
      await loadData();
    } catch (requestError) {
      setError(getErrorMessage(requestError));
    }
  };

  return (
    <div className="page-grid">
      <Panel title="添加设备">
        <form className="form-grid dual" onSubmit={createDevice}>
          <label>
            设备 ID
            <input onChange={(event) => setNewDeviceId(event.target.value)} required value={newDeviceId} />
          </label>
          <label>
            在线设备快速选择
            <select
              onChange={(event) => {
                if (event.target.value) {
                  setNewDeviceId(event.target.value);
                }
              }}
              value=""
            >
              <option value="">从 MQTT 在线设备中选择</option>
              {discoveredDevices.map((item) => (
                <option key={item.device_id} value={item.device_id}>
                  {item.device_id}（最近上报: {item.last_seen}）
                </option>
              ))}
            </select>
          </label>
          <label>
            设备名称
            <input
              onChange={(event) => setNewDeviceName(event.target.value)}
              required
              value={newDeviceName}
            />
          </label>
          <p className="muted full-row">
            可选在线设备：{discoveredDevices.length} 台（仅展示最近 3 分钟内 MQTT 上报且尚未创建的设备）
          </p>
          <button className="primary-btn full-row" type="submit">
            添加设备
          </button>
        </form>
      </Panel>

      <Panel
        extra={
          <button className="ghost-btn" onClick={() => void loadData()} type="button">
            刷新
          </button>
        }
        title="设备列表"
      >
        {error && <p className="error-text">{error}</p>}
        {loading ? (
          <p className="muted">加载中...</p>
        ) : (
          <div className="table-wrap">
            <table>
              <thead>
                <tr>
                  <th>设备 ID</th>
                  <th>名称</th>
                  <th>状态</th>
                  <th>已绑定司机</th>
                  <th>最近上报</th>
                  <th>绑定操作</th>
                  <th>删除</th>
                </tr>
              </thead>
              <tbody>
                {devices.map((device) => (
                  <tr key={device.device_id}>
                    <td>{device.device_id}</td>
                    <td>{device.name}</td>
                    <td>{device.status}</td>
                    <td>
                      {device.driver_id ? (
                        <div>
                          <strong>{device.driver?.display_name || device.driver?.username || "未知司机"}</strong>
                          <span className="muted">（ID: {device.driver_id}）</span>
                        </div>
                      ) : (
                        "-"
                      )}
                    </td>
                    <td>{device.last_seen || "-"}</td>
                    <td>
                      {device.driver_id ? (
                        <button
                          className="ghost-btn small"
                          onClick={() => void unbindDevice(device.device_id)}
                          type="button"
                        >
                          解绑
                        </button>
                      ) : (
                        <div className="inline-actions">
                          <select
                            onChange={(event) =>
                              setSelectedBind((prev) => ({
                                ...prev,
                                [device.device_id]: event.target.value,
                              }))
                            }
                            value={selectedBind[device.device_id] || ""}
                          >
                            <option value="">选择司机</option>
                            {drivers.map((driver) => (
                              <option key={driver.user_id} value={driver.user_id}>
                                {driver.display_name || driver.username}
                              </option>
                            ))}
                          </select>
                          <button
                            className="ghost-btn small"
                            onClick={() => void bindDevice(device.device_id)}
                            type="button"
                          >
                            绑定
                          </button>
                        </div>
                      )}
                    </td>
                    <td>
                      <button
                        className="danger-link"
                        onClick={() => void deleteDevice(device.device_id)}
                        type="button"
                      >
                        删除
                      </button>
                    </td>
                  </tr>
                ))}
                {devices.length === 0 && (
                  <tr>
                    <td colSpan={7}>暂无设备</td>
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
