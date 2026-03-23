import { type FormEvent, useMemo, useState } from "react";
import { Link, useNavigate } from "react-router-dom";

import { api, getErrorMessage } from "../lib/http";
import type { ApiResponse } from "../types/api";

interface RegisterForm {
  username: string;
  password: string;
  confirmPassword: string;
  real_name: string;
  id_card: string;
  phone: string;
  plate_number: string;
  vehicle_type: string;
}

const initialForm: RegisterForm = {
  username: "",
  password: "",
  confirmPassword: "",
  real_name: "",
  id_card: "",
  phone: "",
  plate_number: "",
  vehicle_type: "冷藏车",
};

function hasPasswordTypeMix(password: string): boolean {
  const hasUpper = /[A-Z]/.test(password);
  const hasLower = /[a-z]/.test(password);
  const hasDigit = /\d/.test(password);
  const typeCount = Number(hasUpper) + Number(hasLower) + Number(hasDigit);
  return typeCount >= 2;
}

export function RegisterPage() {
  const navigate = useNavigate();
  const [form, setForm] = useState<RegisterForm>(initialForm);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [success, setSuccess] = useState("");

  const passwordRuleHint = useMemo(() => {
    if (!form.password && !form.confirmPassword) {
      return "";
    }
    if (form.password.length < 8) {
      return "密码长度至少 8 位";
    }
    if (!hasPasswordTypeMix(form.password)) {
      return "密码至少包含大写字母、小写字母、数字中的两种";
    }
    if (form.password !== form.confirmPassword) {
      return "两次输入的密码不一致";
    }
    return "";
  }, [form.password, form.confirmPassword]);

  const validateBeforeSubmit = (): string => {
    if (!form.username.trim()) {
      return "请输入用户名";
    }
    if (!form.phone.trim()) {
      return "请输入手机号";
    }
    if (!form.real_name.trim()) {
      return "请输入姓名";
    }
    if (!form.id_card.trim()) {
      return "请输入身份证号";
    }
    if (!form.plate_number.trim()) {
      return "请输入车牌号";
    }
    if (!form.password || !form.confirmPassword) {
      return "请输入密码并确认密码";
    }
    if (form.password.length < 8) {
      return "密码长度至少 8 位";
    }
    if (!hasPasswordTypeMix(form.password)) {
      return "密码至少包含大写字母、小写字母、数字中的两种";
    }
    if (form.password !== form.confirmPassword) {
      return "两次输入的密码不一致";
    }
    return "";
  };

  const updateField = (key: keyof RegisterForm, value: string) => {
    setForm((prev) => ({ ...prev, [key]: value }));
  };

  const handleSubmit = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    const validationError = validateBeforeSubmit();
    if (validationError) {
      setError(validationError);
      return;
    }

    setLoading(true);
    setError("");
    setSuccess("");
    try {
      await api.post<ApiResponse<{ user_id: number }>>("/auth/register", {
        username: form.username,
        password: form.password,
        real_name: form.real_name,
        id_card: form.id_card,
        phone: form.phone,
        plate_number: form.plate_number,
        vehicle_type: form.vehicle_type,
      });
      setSuccess("注册成功，请等待管理员审批");
      setTimeout(() => navigate("/login"), 1200);
    } catch (requestError) {
      setError(getErrorMessage(requestError));
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="auth-screen">
      <div className="auth-card wide">
        <h1>司机注册</h1>
        <p>注册后状态为待审批，请联系管理员完成审核</p>
        <form className="form-grid dual" onSubmit={handleSubmit}>
          <label>
            用户名
            <input
              onChange={(event) => updateField("username", event.target.value)}
              required
              value={form.username}
            />
          </label>
          <label>
            手机号
            <input
              onChange={(event) => updateField("phone", event.target.value)}
              required
              value={form.phone}
            />
          </label>
          <label>
            密码
            <input
              onChange={(event) => updateField("password", event.target.value)}
              minLength={8}
              required
              type="password"
              value={form.password}
            />
          </label>
          <label>
            确认密码
            <input
              onChange={(event) => updateField("confirmPassword", event.target.value)}
              minLength={8}
              required
              type="password"
              value={form.confirmPassword}
            />
          </label>
          <label>
            姓名
            <input
              onChange={(event) => updateField("real_name", event.target.value)}
              required
              value={form.real_name}
            />
          </label>
          <label>
            身份证号
            <input
              onChange={(event) => updateField("id_card", event.target.value)}
              required
              value={form.id_card}
            />
          </label>
          <label>
            车牌号
            <input
              onChange={(event) => updateField("plate_number", event.target.value)}
              required
              value={form.plate_number}
            />
          </label>
          <label>
            车辆类型
            <select
              onChange={(event) => updateField("vehicle_type", event.target.value)}
              value={form.vehicle_type}
            >
              <option value="冷藏车">冷藏车</option>
              <option value="保温车">保温车</option>
              <option value="冷冻车">冷冻车</option>
            </select>
          </label>

          {passwordRuleHint && <p className="muted full-row">{passwordRuleHint}</p>}
          {error && <p className="error-text full-row">{error}</p>}
          {success && <p className="success-text full-row">{success}</p>}

          <button className="primary-btn full-row" disabled={loading} type="submit">
            {loading ? "提交中..." : "提交注册"}
          </button>
        </form>
        <div className="auth-footer">
          <span>已有账号？</span>
          <Link to="/login">返回登录</Link>
        </div>
      </div>
    </div>
  );
}
