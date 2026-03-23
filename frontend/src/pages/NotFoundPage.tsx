import { Link } from "react-router-dom";

import { getAuth, resolveHomePath } from "../lib/auth";

export function NotFoundPage() {
  const auth = getAuth();
  return (
    <div className="center-empty">
      <h2>页面不存在</h2>
      <p>请检查地址，或返回系统首页继续操作。</p>
      <Link className="primary-btn inline" to={resolveHomePath(auth?.role)}>
        返回首页
      </Link>
    </div>
  );
}
