import { type FormEvent, useState } from "react";
import { Link, useLocation, useNavigate } from "react-router-dom";

import { saveAuth, resolveHomePath } from "../lib/auth";
import { api, getErrorMessage } from "../lib/http";
import type { ApiResponse, LoginResult } from "../types/api";

export function LoginPage() {
  const navigate = useNavigate();
  const location = useLocation();
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");

  const handleSubmit = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    setLoading(true);
    setError("");

    try {
      const response = await api.post<ApiResponse<LoginResult>>("/auth/login", {
        username,
        password,
      });
      const auth = saveAuth(response.data.data);
      const from = location.state as { from?: string } | null;
      navigate(from?.from || resolveHomePath(auth.role), { replace: true });
    } catch (requestError) {
      setError(getErrorMessage(requestError));
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="auth-screen">
      <div className="auth-card">
        <h1>冷链运输监控系统</h1>
        <p>登录后将根据角色自动跳转到对应工作台</p>
        <form className="form-grid" onSubmit={handleSubmit}>
          <label>
            用户名
            <input
              autoComplete="username"
              onChange={(event) => setUsername(event.target.value)}
              placeholder="请输入用户名"
              required
              value={username}
            />
          </label>
          <label>
            密码
            <input
              autoComplete="current-password"
              onChange={(event) => setPassword(event.target.value)}
              placeholder="请输入密码"
              required
              type="password"
              value={password}
            />
          </label>
          {error && <p className="error-text">{error}</p>}
          <button className="primary-btn" disabled={loading} type="submit">
            {loading ? "登录中..." : "登录"}
          </button>
        </form>
        <div className="auth-footer">
          <span>还没有账号？</span>
          <Link to="/register">司机注册</Link>
        </div>
      </div>
    </div>
  );
}
