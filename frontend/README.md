# Frontend Web

## 启动

```bash
npm install
npm run dev
```

默认访问 `http://127.0.0.1:5173`。

## 通过环境变量配置后端地址

复制 `.env.example` 为 `.env`，然后按下面两种模式二选一。

1. 代理模式（本地开发推荐）

```env
VITE_API_BASE_URL=/api
VITE_WS_BASE_URL=/ws
VITE_BACKEND_ORIGIN=http://127.0.0.1:8000
```

说明：
- 浏览器请求 `/api/*`，由 Vite 代理到 `VITE_BACKEND_ORIGIN`。
- 这样可以避免本地开发时的跨域问题。

2. 直连模式（部署常用）

```env
VITE_API_BASE_URL=https://api.example.com/api
VITE_WS_BASE_URL=wss://api.example.com/ws
```

说明：
- 前端直接请求后端地址，不走 Vite 代理。
- 需要后端允许前端来源的 CORS（例如 `http://localhost:5173`）。

## 已完成页面

- 公共：`/login`、`/register`
- 管理端：`/admin/dashboard`、`/admin/orders`、`/admin/orders/:orderId`、`/admin/devices`、`/admin/drivers`、`/admin/anomalies`、`/admin/chain`、`/admin/tickets`、`/admin/users`、`/admin/config`
- 司机端：`/driver/orders`、`/driver/orders/:orderId`、`/driver/notifications`、`/driver/tickets`、`/driver/profile`

### 运单详情增强

- 监控模式切换：实时 / 最近 / 自定义时间段
- 三个传感器图：温度、湿度、气压（阈值线 + 异常时段高亮）
- GPS 地图轨迹（OpenStreetMap 底图）
- 异常点定位（异常列表一键定位到地图点位）
- WebSocket 实时推送（`/ws/monitor/{order_id}`）驱动曲线增量更新
- WebSocket 断线自动重连（指数退避，鉴权失败码不重连）
