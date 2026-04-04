import { useEffect, useState } from "react";

import { Panel } from "../../components/Panel";
import { api, getErrorMessage, unwrap } from "../../lib/http";
import type { ApiResponse, PagedList } from "../../types/api";

interface DriverProfile {
  real_name: string;
  phone: string;
  plate_number: string;
  vehicle_type: string;
}

interface DriverUser {
  user_id: number;
  username: string;
  display_name?: string | null;
  status: string;
  driver_profile: DriverProfile | null;
  bound_device_id: string | null;
}

interface DeviceItem {
  device_id: string;
  name: string;
  driver_id: number | null;
}

export function DriversPage() {
  const [pendingDrivers, setPendingDrivers] = useState<DriverUser[]>([]);
  const [activeDrivers, setActiveDrivers] = useState<DriverUser[]>([]);
  const [devices, setDevices] = useState<DeviceItem[]>([]);
  const [selectedDevice, setSelectedDevice] = useState<Record<number, string>>({});
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");

  const loadData = async () => {
    setLoading(true);
    setError("");
    try {
      const [pendingData, activeData, deviceData] = await Promise.all([
        unwrap(
          api.get<ApiResponse<PagedList<DriverUser>>>("/users", {
            params: { role: "driver", status: "pending", page: 1, page_size: 100 },
          }),
        ),
        unwrap(
          api.get<ApiResponse<PagedList<DriverUser>>>("/users", {
            params: { role: "driver", status: "active", page: 1, page_size: 100 },
          }),
        ),
        unwrap(api.get<ApiResponse<PagedList<DeviceItem>>>("/devices", {
          params: { page: 1, page_size: 100 },
        })),
      ]);
      setPendingDrivers(pendingData.items);
      setActiveDrivers(activeData.items);
      setDevices(deviceData.items);
    } catch (requestError) {
      setError(getErrorMessage(requestError));
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    void loadData();
  }, []);

  const approve = async (driverId: number) => {
    const deviceId = selectedDevice[driverId];
    if (!deviceId) {
      setError("审批通过前请先选择绑定设备");
      return;
    }
    try {
      await api.patch(`/users/${driverId}/approve`, { device_id: deviceId });
      await loadData();
    } catch (requestError) {
      setError(getErrorMessage(requestError));
    }
  };

  const reject = async (driverId: number) => {
    try {
      await api.patch(`/users/${driverId}/reject`);
      await loadData();
    } catch (requestError) {
      setError(getErrorMessage(requestError));
    }
  };

  const disable = async (driverId: number) => {
    try {
      await api.patch(`/users/${driverId}/disable`);
      await loadData();
    } catch (requestError) {
      setError(getErrorMessage(requestError));
    }
  };

  const availableDevices = devices.filter((item) => !item.driver_id);

  return (
    <div className="page-grid">
      <Panel
        extra={
          <button className="ghost-btn" onClick={() => void loadData()} type="button">
            刷新
          </button>
        }
        title="待审批司机"
      >
        {error && <p className="error-text">{error}</p>}
        {loading ? (
          <p className="muted">加载中...</p>
        ) : (
          <div className="table-wrap">
            <table>
              <thead>
                <tr>
                  <th>用户</th>
                  <th>姓名</th>
                  <th>电话</th>
                  <th>车牌</th>
                  <th>车辆类型</th>
                  <th>绑定设备</th>
                  <th>操作</th>
                </tr>
              </thead>
              <tbody>
                {pendingDrivers.map((driver) => (
                  <tr key={driver.user_id}>
                    <td>{driver.username}</td>
                    <td>{driver.driver_profile?.real_name || "-"}</td>
                    <td>{driver.driver_profile?.phone || "-"}</td>
                    <td>{driver.driver_profile?.plate_number || "-"}</td>
                    <td>{driver.driver_profile?.vehicle_type || "-"}</td>
                    <td>
                      <select
                        onChange={(event) =>
                          setSelectedDevice((prev) => ({
                            ...prev,
                            [driver.user_id]: event.target.value,
                          }))
                        }
                        value={selectedDevice[driver.user_id] || ""}
                      >
                        <option value="">选择设备</option>
                        {availableDevices.map((device) => (
                          <option key={device.device_id} value={device.device_id}>
                            {device.device_id} / {device.name}
                          </option>
                        ))}
                      </select>
                    </td>
                    <td>
                      <div className="inline-actions">
                        <button
                          className="ghost-btn small"
                          onClick={() => void approve(driver.user_id)}
                          type="button"
                        >
                          通过
                        </button>
                        <button
                          className="danger-link"
                          onClick={() => void reject(driver.user_id)}
                          type="button"
                        >
                          拒绝
                        </button>
                      </div>
                    </td>
                  </tr>
                ))}
                {pendingDrivers.length === 0 && (
                  <tr>
                    <td colSpan={7}>当前无待审批司机</td>
                  </tr>
                )}
              </tbody>
            </table>
          </div>
        )}
      </Panel>

      <Panel title="已通过司机">
        <div className="table-wrap">
          <table>
            <thead>
              <tr>
                <th>用户</th>
                <th>姓名</th>
                <th>绑定设备</th>
                <th>状态</th>
                <th>操作</th>
              </tr>
            </thead>
            <tbody>
              {activeDrivers.map((driver) => (
                <tr key={driver.user_id}>
                  <td>{driver.username}</td>
                  <td>{driver.driver_profile?.real_name || driver.display_name || "-"}</td>
                  <td>{driver.bound_device_id || "-"}</td>
                  <td>{driver.status}</td>
                  <td>
                    <button
                      className="danger-link"
                      onClick={() => void disable(driver.user_id)}
                      type="button"
                    >
                      禁用
                    </button>
                  </td>
                </tr>
              ))}
              {activeDrivers.length === 0 && (
                <tr>
                  <td colSpan={5}>暂无已通过司机</td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
      </Panel>
    </div>
  );
}
