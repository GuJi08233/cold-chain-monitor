import { lazy, Suspense, type ReactNode } from "react";
import { Navigate, Route, Routes } from "react-router-dom";

import { AppShell } from "./components/AppShell";
import { ProtectedRoute } from "./components/ProtectedRoute";
import { getAuth, resolveHomePath } from "./lib/auth";
import { LoginPage } from "./pages/LoginPage";
import { NotFoundPage } from "./pages/NotFoundPage";
import { RegisterPage } from "./pages/RegisterPage";

const DashboardPage = lazy(() =>
  import("./pages/admin/DashboardPage").then((module) => ({
    default: module.DashboardPage,
  })),
);
const OrdersPage = lazy(() =>
  import("./pages/admin/OrdersPage").then((module) => ({
    default: module.OrdersPage,
  })),
);
const DevicesPage = lazy(() =>
  import("./pages/admin/DevicesPage").then((module) => ({
    default: module.DevicesPage,
  })),
);
const DriversPage = lazy(() =>
  import("./pages/admin/DriversPage").then((module) => ({
    default: module.DriversPage,
  })),
);
const AnomaliesPage = lazy(() =>
  import("./pages/admin/AnomaliesPage").then((module) => ({
    default: module.AnomaliesPage,
  })),
);
const ChainPage = lazy(() =>
  import("./pages/admin/ChainPage").then((module) => ({
    default: module.ChainPage,
  })),
);
const TicketsPage = lazy(() =>
  import("./pages/admin/TicketsPage").then((module) => ({
    default: module.TicketsPage,
  })),
);
const UsersPage = lazy(() =>
  import("./pages/admin/UsersPage").then((module) => ({
    default: module.UsersPage,
  })),
);
const ConfigPage = lazy(() =>
  import("./pages/admin/ConfigPage").then((module) => ({
    default: module.ConfigPage,
  })),
);
const DriverOrdersPage = lazy(() =>
  import("./pages/driver/DriverOrdersPage").then((module) => ({
    default: module.DriverOrdersPage,
  })),
);
const DriverNotificationsPage = lazy(() =>
  import("./pages/driver/DriverNotificationsPage").then((module) => ({
    default: module.DriverNotificationsPage,
  })),
);
const DriverTicketNewPage = lazy(() =>
  import("./pages/driver/DriverTicketNewPage").then((module) => ({
    default: module.DriverTicketNewPage,
  })),
);
const DriverTicketsPage = lazy(() =>
  import("./pages/driver/DriverTicketsPage").then((module) => ({
    default: module.DriverTicketsPage,
  })),
);
const DriverProfilePage = lazy(() =>
  import("./pages/driver/DriverProfilePage").then((module) => ({
    default: module.DriverProfilePage,
  })),
);
const OrderDetailPage = lazy(() =>
  import("./pages/shared/OrderDetailPage").then((module) => ({
    default: module.OrderDetailPage,
  })),
);

function RouteLoading() {
  return (
    <div className="route-loading">
      <p className="muted">页面加载中...</p>
    </div>
  );
}

function lazyElement(element: ReactNode) {
  return <Suspense fallback={<RouteLoading />}>{element}</Suspense>;
}

function RootRedirect() {
  const auth = getAuth();
  if (!auth) {
    return <Navigate replace to="/login" />;
  }
  return <Navigate replace to={resolveHomePath(auth.role)} />;
}

export function App() {
  return (
    <Routes>
      <Route element={<RootRedirect />} path="/" />

      <Route element={<LoginPage />} path="/login" />
      <Route element={<RegisterPage />} path="/register" />

      <Route element={<ProtectedRoute area="admin" />}>
        <Route element={<AppShell section="admin" />} path="/admin">
          <Route element={<Navigate replace to="/admin/dashboard" />} index />
          <Route element={lazyElement(<DashboardPage />)} path="dashboard" />
          <Route element={lazyElement(<OrdersPage />)} path="orders" />
          <Route element={lazyElement(<OrderDetailPage />)} path="orders/:orderId" />
          <Route element={lazyElement(<DevicesPage />)} path="devices" />
          <Route element={lazyElement(<DriversPage />)} path="drivers" />
          <Route element={lazyElement(<AnomaliesPage />)} path="anomalies" />
          <Route element={lazyElement(<ChainPage />)} path="chain" />
          <Route element={lazyElement(<TicketsPage />)} path="tickets" />
          <Route element={lazyElement(<UsersPage />)} path="users" />
          <Route element={lazyElement(<ConfigPage />)} path="config" />
        </Route>
      </Route>

      <Route element={<ProtectedRoute area="driver" />}>
        <Route element={<AppShell section="driver" />} path="/driver">
          <Route element={<Navigate replace to="/driver/orders" />} index />
          <Route element={lazyElement(<DriverOrdersPage />)} path="orders" />
          <Route element={lazyElement(<OrderDetailPage />)} path="orders/:orderId" />
          <Route element={lazyElement(<DriverNotificationsPage />)} path="notifications" />
          <Route element={lazyElement(<DriverTicketNewPage />)} path="tickets/new" />
          <Route element={lazyElement(<DriverTicketsPage />)} path="tickets" />
          <Route element={lazyElement(<DriverProfilePage />)} path="profile" />
        </Route>
      </Route>

      <Route element={<NotFoundPage />} path="*" />
    </Routes>
  );
}
