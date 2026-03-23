import { Navigate, Outlet, useLocation } from "react-router-dom";

import { getAuth, resolveHomePath } from "../lib/auth";

interface ProtectedRouteProps {
  area: "admin" | "driver";
}

export function ProtectedRoute(props: ProtectedRouteProps) {
  const auth = getAuth();
  const location = useLocation();

  if (!auth) {
    return <Navigate to="/login" replace state={{ from: location.pathname }} />;
  }

  if (props.area === "admin") {
    if (auth.role === "driver") {
      return <Navigate to="/driver/orders" replace />;
    }
    if (
      auth.role === "admin" &&
      (location.pathname.startsWith("/admin/users") ||
        location.pathname.startsWith("/admin/config"))
    ) {
      return <Navigate to="/admin/dashboard" replace />;
    }
    return <Outlet />;
  }

  if (auth.role !== "driver") {
    return <Navigate to={resolveHomePath(auth.role)} replace />;
  }

  return <Outlet />;
}
