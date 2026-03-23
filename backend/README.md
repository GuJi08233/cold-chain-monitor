# Cold Chain Backend

基于 FastAPI + SQLAlchemy 的后端骨架，当前已完成阶段一-B、阶段二-D/E/F、阶段三-G/H、阶段四-I/J/K/L、阶段五-M/N基础能力：

- FastAPI 应用入口与统一响应格式
- SQLite 业务库模型与自动建表
- 全局异常处理
- 启动时初始化 `super_admin` 账户与系统配置键
- JWT 登录鉴权（`/api/auth/login`）
- 司机注册（`/api/auth/register`）
- 当前用户信息（`/api/auth/me`）
- 修改密码（`/api/auth/password`）
- 用户管理接口（`/api/users`：列表/详情/审批/拒绝/禁用/删除）
- 设备管理接口（`/api/devices`：列表/创建/详情/绑定/删除）
- 运单管理接口（`/api/orders`：创建/列表/详情/告警规则/出发/完成/取消）
- 后台 MQTT 订阅服务（QoS 1）
- MQTT 消息解析 + 设备状态更新（`devices.last_seen/status`）
- 运输中运单数据写入 TDengine 子表
- 监控数据 API（`/api/monitor/{order_id}/latest|sensor|track`）
- WebSocket 监控推送（`/ws/monitor/{order_id}`）
- 异常判断引擎（阈值触发、峰值追踪、连续 3 条恢复）
- 设备离线检测任务（5 秒检测，10 秒超时）
- 异常查询 API（`/api/anomalies`、`/api/orders/{order_id}/anomalies`）
- 通知 API（`/api/notifications`、`/api/notifications/unread-count`）
- 通知 WebSocket（`/ws/notifications?token=<JWT>`）
- AES-256-CBC 加解密服务（链上敏感信息）
- SHA-256 哈希服务（支持流式批处理）
- 运单完成时自动计算并写入 `orders.data_hash`
- 异常开始/恢复异步上链 + 运单哈希异步上链（`chain_records`）
- 区块链查询与重试 API（`/api/chain/*`）
- 工单系统 API（`/api/tickets/*`）
- 仪表盘 API（`/api/dashboard/*`）
- 系统配置 API（`/api/config/*`，含 MQTT/TDengine/ETH 连通性测试）

## 1. 安装依赖

```bash
pip install -r requirements.txt
```

## 2. 配置环境变量

```bash
cp .env.example .env
```

按需修改 `.env`，重点配置：

- `DATABASE_URL`
- `SUPER_ADMIN_USERNAME`
- `SUPER_ADMIN_PASSWORD`
- `JWT_SECRET_KEY`

## 3. 启动服务

```bash
uvicorn app.main:app --reload
```

## 4. 验证

- 健康检查：`GET /api/health`
- 鉴权接口：`/api/auth/*`
- 用户接口：`/api/users/*`
- 设备接口：`/api/devices/*`
- 运单接口：`/api/orders/*`
- 监控接口：`/api/monitor/*`
- 异常接口：`/api/anomalies*`
- 通知接口：`/api/notifications*`
- 区块链接口：`/api/chain/*`
- 工单接口：`/api/tickets/*`
- 仪表盘接口：`/api/dashboard/*`
- 系统配置接口：`/api/config/*`
- 监控 WS：`/ws/monitor/{order_id}?token=<JWT>`
- 通知 WS：`/ws/notifications?token=<JWT>`
- 文档地址：`/docs`
- 首次启动会自动创建 `cold_chain.db` 和 `super_admin` 用户

## 5. 环境联调脚本

- TDengine 建库建超级表：`python scripts/tdengine_bootstrap.py`
- MQTT 订阅探活：`python scripts/mqtt_probe.py --seconds 10`
- 同步 MQTT/TDengine/ETH 到 system_config：`python scripts/seed_system_config.py`
- 全链路验收冒烟（默认自动清理数据）：`python scripts/full_flow_smoke.py`
