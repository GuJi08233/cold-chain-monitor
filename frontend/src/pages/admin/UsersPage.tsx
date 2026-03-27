import { type FormEvent, useEffect, useState } from "react";

import { Pagination } from "../../components/Pagination";
import { Panel } from "../../components/Panel";
import { api, getErrorMessage, unwrap } from "../../lib/http";
import type { ApiResponse, PagedList } from "../../types/api";

interface UserItem {
  user_id: number;
  username: string;
  display_name: string | null;
  role: string;
  status: string;
  bound_device_id: string | null;
}

export function UsersPage() {
  const [items, setItems] = useState<UserItem[]>([]);
  const [search, setSearch] = useState("");
  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState(20);
  const [total, setTotal] = useState(0);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [displayName, setDisplayName] = useState("");

  const loadData = async (nextPage = page, nextPageSize = pageSize) => {
    setLoading(true);
    setError("");
    try {
      const data = await unwrap(
        api.get<ApiResponse<PagedList<UserItem>>>("/users", {
          params: {
            page: nextPage,
            page_size: nextPageSize,
            search: search || undefined,
          },
        }),
      );
      setItems(data.items);
      setPage(data.page);
      setPageSize(data.page_size);
      setTotal(data.total);
    } catch (requestError) {
      setError(getErrorMessage(requestError));
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    setPage(1);
    void loadData(1, pageSize);
  }, [search]);

  const createAdmin = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    try {
      await api.post("/users", {
        username,
        password,
        display_name: displayName,
      });
      setUsername("");
      setPassword("");
      setDisplayName("");
      await loadData();
    } catch (requestError) {
      setError(getErrorMessage(requestError));
    }
  };

  const disableUser = async (userId: number) => {
    try {
      await api.patch(`/users/${userId}/disable`);
      await loadData();
    } catch (requestError) {
      setError(getErrorMessage(requestError));
    }
  };

  const deleteUser = async (userId: number) => {
    const ok = window.confirm(`确认删除用户 ID=${userId} 吗？`);
    if (!ok) {
      return;
    }
    try {
      await api.delete(`/users/${userId}`);
      await loadData();
    } catch (requestError) {
      setError(getErrorMessage(requestError));
    }
  };

  return (
    <div className="page-grid">
      <Panel title="创建管理员">
        <form className="form-grid triple" onSubmit={createAdmin}>
          <label>
            用户名
            <input onChange={(event) => setUsername(event.target.value)} required value={username} />
          </label>
          <label>
            密码
            <input
              onChange={(event) => setPassword(event.target.value)}
              required
              type="password"
              value={password}
            />
          </label>
          <label>
            显示名称
            <input onChange={(event) => setDisplayName(event.target.value)} value={displayName} />
          </label>
          <button className="primary-btn full-row" type="submit">
            创建管理员
          </button>
        </form>
      </Panel>

      <Panel
        extra={
          <div className="toolbar-inline">
            <input
              onChange={(event) => {
                setPage(1);
                setSearch(event.target.value);
              }}
              placeholder="按用户名/显示名搜索"
              value={search}
            />
            <button className="ghost-btn" onClick={() => void loadData()} type="button">
              刷新
            </button>
          </div>
        }
        title="用户管理"
      >
        {error && <p className="error-text">{error}</p>}
        {loading ? (
          <p className="muted">加载中...</p>
        ) : (
          <>
            <div className="table-wrap">
              <table>
                <thead>
                  <tr>
                    <th>ID</th>
                    <th>用户名</th>
                    <th>显示名</th>
                    <th>角色</th>
                    <th>状态</th>
                    <th>绑定设备</th>
                    <th>操作</th>
                  </tr>
                </thead>
                <tbody>
                  {items.map((item) => (
                    <tr key={item.user_id}>
                      <td>{item.user_id}</td>
                      <td>{item.username}</td>
                      <td>{item.display_name || "-"}</td>
                      <td>{item.role}</td>
                      <td>{item.status}</td>
                      <td>{item.bound_device_id || "-"}</td>
                      <td>
                        <div className="inline-actions">
                          {item.role !== "super_admin" && (
                            <button
                              className="ghost-btn small"
                              onClick={() => void disableUser(item.user_id)}
                              type="button"
                            >
                              禁用
                            </button>
                          )}
                          {item.role !== "super_admin" && (
                            <button
                              className="danger-link"
                              onClick={() => void deleteUser(item.user_id)}
                              type="button"
                            >
                              删除
                            </button>
                          )}
                        </div>
                      </td>
                    </tr>
                  ))}
                  {items.length === 0 && (
                    <tr>
                      <td colSpan={7}>暂无用户</td>
                    </tr>
                  )}
                </tbody>
              </table>
            </div>
            <Pagination
              onPageChange={(nextPage) => {
                setPage(nextPage);
                void loadData(nextPage, pageSize);
              }}
              onPageSizeChange={(nextPageSize) => {
                setPage(1);
                setPageSize(nextPageSize);
                void loadData(1, nextPageSize);
              }}
              page={page}
              pageSize={pageSize}
              total={total}
            />
          </>
        )}
      </Panel>
    </div>
  );
}
