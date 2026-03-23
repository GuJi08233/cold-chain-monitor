import { type FormEvent, useEffect, useState } from "react";
import { Link } from "react-router-dom";

import { Panel } from "../../components/Panel";
import { api, getErrorMessage, unwrap } from "../../lib/http";
import type { ApiResponse } from "../../types/api";

interface DriverProfile {
  real_name: string;
  id_card: string;
  phone: string;
  plate_number: string;
  vehicle_type: string;
}

interface CurrentUser {
  user_id: number;
  username: string;
  role: string;
  display_name: string | null;
  status: string;
  created_at: string;
  driver_profile: DriverProfile | null;
}

export function DriverProfilePage() {
  const [current, setCurrent] = useState<CurrentUser | null>(null);
  const [oldPassword, setOldPassword] = useState("");
  const [newPassword, setNewPassword] = useState("");
  const [error, setError] = useState("");
  const [success, setSuccess] = useState("");

  const loadData = async () => {
    setError("");
    try {
      const data = await unwrap(api.get<ApiResponse<CurrentUser>>("/auth/me"));
      setCurrent(data);
    } catch (requestError) {
      setError(getErrorMessage(requestError));
    }
  };

  useEffect(() => {
    void loadData();
  }, []);

  const changePassword = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    setError("");
    setSuccess("");
    try {
      await api.patch("/auth/password", {
        old_password: oldPassword,
        new_password: newPassword,
      });
      setOldPassword("");
      setNewPassword("");
      setSuccess("密码修改成功");
    } catch (requestError) {
      setError(getErrorMessage(requestError));
    }
  };

  return (
    <div className="page-grid">
      <Panel title="个人信息">
        {error && <p className="error-text">{error}</p>}
        {current ? (
          <>
            <div className="key-value-grid">
              <p>
                <strong>用户名:</strong> {current.username}
              </p>
              <p>
                <strong>显示名:</strong> {current.display_name || "-"}
              </p>
              <p>
                <strong>账号状态:</strong> {current.status}
              </p>
              <p>
                <strong>姓名:</strong> {current.driver_profile?.real_name || "-"}
              </p>
              <p>
                <strong>身份证:</strong> {current.driver_profile?.id_card || "-"}
              </p>
              <p>
                <strong>手机号:</strong> {current.driver_profile?.phone || "-"}
              </p>
              <p>
                <strong>车牌号:</strong> {current.driver_profile?.plate_number || "-"}
              </p>
              <p>
                <strong>车辆类型:</strong> {current.driver_profile?.vehicle_type || "-"}
              </p>
            </div>
            <div className="inline-actions profile-actions">
              <Link className="ghost-btn text-link-btn" to="/driver/tickets/new?type=info_change">
                申请信息变更
              </Link>
            </div>
          </>
        ) : (
          <p className="muted">加载中...</p>
        )}
      </Panel>

      <Panel title="修改密码">
        <form className="form-grid dual" onSubmit={changePassword}>
          <label>
            旧密码
            <input
              onChange={(event) => setOldPassword(event.target.value)}
              required
              type="password"
              value={oldPassword}
            />
          </label>
          <label>
            新密码
            <input
              onChange={(event) => setNewPassword(event.target.value)}
              required
              type="password"
              value={newPassword}
            />
          </label>
          {success && <p className="success-text full-row">{success}</p>}
          <button className="primary-btn full-row" type="submit">
            提交修改
          </button>
        </form>
      </Panel>
    </div>
  );
}
