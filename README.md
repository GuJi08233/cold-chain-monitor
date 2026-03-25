# 基于以太坊的冷链运输监控系统

这是一个面向冷链运输场景的最小公开代码仓库，保留当前项目的核心程序代码与脱敏后的设备/合约源码。

## 包含内容

- `backend/`：FastAPI + SQLAlchemy 后端
- `frontend/`：React + TypeScript + Vite 前端
- `contracts/ColdChainMonitorV3.sol`：当前最终版智能合约源码
- `Arduino/esp32.ino`：脱敏后的 ESP32 示例代码
- `文档介绍/`：硬件、智能合约、系统说明文档
- `Dockerfile`：单镜像构建前后端并由 FastAPI 统一提供服务
- `docker-compose.yml`：单机部署入口

当前仓库不包含本地数据库、日志、私钥、部署产物、真实设备配置和测试运行结果。

## 目录说明

```text
.
├── backend/
├── contracts/
├── frontend/
├── Arduino/
├── 文档介绍/
├── Dockerfile
├── docker-compose.yml
└── README.md
```

更详细的设计与实现说明可查看：

- `文档介绍/硬件部分.md`
- `文档介绍/智能合约部分.md`
- `文档介绍/系统部分.md`

## 环境变量

公开仓库只保留运行项目所需的示例环境变量：

- `backend/.env.example`
- `frontend/.env.example`

复制方式：

```bash
cp backend/.env.example backend/.env
cp frontend/.env.example frontend/.env
```

上线前请务必替换以下敏感项：

- `APP_SECRET_KEY`
- `JWT_SECRET_KEY`
- `SUPER_ADMIN_PASSWORD`
- `APP_TIMEZONE`
- `MQTT_*`
- `TDENGINE_*`
- `ETH_RPC_URL`
- `ETH_CONTRACT_ADDRESS`
- `ETH_PRIVATE_KEY`
- `ETH_AES_KEY`

`Arduino/esp32.ino` 中的 WiFi、MQTT、NTP 配置也需要在本地手动替换为真实值。

## 本地开发

### 后端

```bash
cd backend
pip install -r requirements.txt
python -m uvicorn app.main:app --host 127.0.0.1 --port 8000
```

### 前端

```bash
cd frontend
npm install
npm run dev
```

## Docker

仓库默认提供单镜像部署入口：

- `Dockerfile`
- `docker-compose.yml`

根目录 `Dockerfile` 会在构建阶段打包前端，再把产物复制到后端镜像中；运行时只启动一个 FastAPI 进程，由它统一提供：

- 前端静态资源
- API `/api/*`
- WebSocket `/ws/*`

启动前需要先准备：

- `backend/.env`
- 可访问的 MQTT Broker
- 可访问的 TDengine
- 可访问的 ETH RPC（如果启用上链）

如果你使用 SQLite（默认配置），建议把数据库文件放到容器挂载目录中，避免 `docker compose up --build` 重建容器后丢失数据。当前示例环境变量默认使用：

```env
APP_TIMEZONE=Asia/Shanghai
DATABASE_URL=sqlite:///./data/cold_chain.db
CHAIN_AUTO_RETRY_ENABLED=true
CHAIN_AUTO_RETRY_INTERVAL_SECONDS=30
CHAIN_AUTO_RETRY_MAX_INTERVAL_SECONDS=900
CHAIN_AUTO_RETRY_BATCH_SIZE=20
HASH_AUDIT_ENABLED=true
HASH_AUDIT_INTERVAL_SECONDS=300
HASH_AUDIT_BATCH_SIZE=20
```

启动示例：

```bash
docker build -t cold-chain-monitor .
docker run --env-file backend/.env -p 8080:8000 -v $(pwd)/data:/app/data cold-chain-monitor
```

或使用 Compose：

```bash
docker compose up --build -d
```

Compose 默认会把宿主机 `./data` 挂载到容器 `/app/data`，用于持久化 SQLite 数据库。

默认对外开放 `8080`，访问：

- 前端：`http://127.0.0.1:8080/`
- API：`http://127.0.0.1:8080/api/*`
- WebSocket：`ws://127.0.0.1:8080/ws/*`

链上后台维护默认启用两类周期任务：

- `CHAIN_AUTO_RETRY_*`：自动扫描 `failed` 上链记录并按退避策略重试，适合网络抖动场景
- `HASH_AUDIT_*`：定时重算已完成运单的本地哈希并比对链上存证，发现不一致会记录日志并发送通知

超级管理员登录后，也可以直接在“系统配置”页面修改以下运行参数：

- 应用时区 `APP_TIMEZONE`
- 自动重试启用状态、扫描间隔、最大退避、单轮批量数
- 自动哈希巡检启用状态、巡检间隔、单轮批量数

环境变量仍然保留，作为数据库配置为空时的默认回退值。

如果某些已完成运单只是用于手工篡改演示或验收测试，超级管理员可以在运单详情页将其“测试归档”：

- 归档后不会再参与自动哈希巡检
- 手动点击“验证哈希”仍然可用
- 取消归档后会恢复自动哈希巡检

这项能力不改 `orders` 表结构，而是复用 `system_config` 保存按运单的归档元数据，适合直接部署到现有 SQLite 环境。

订单详情页当前采用两种展示语义：

- 运输中运单：按实时监控视图展示，可使用实时/最近/自定义模式
- 已完成运单：默认按结果视图展示，最近模式会锚定到订单完成时间，自定义默认查看订单全程，实时模式仅运输中可用

## 合约与硬件说明

- `contracts/ColdChainMonitorV3.sol` 是当前项目最终使用的合约源码
- 公开仓库不再携带 Hardhat 测试、部署脚本和部署产物
- 后端运行时已内置最小 ABI，不再依赖 Hardhat 编译产物
- `Arduino/esp32.ino` 已脱敏，真实设备配置仅保留在你的本地副本中

## 合约公开安全说明

智能合约源码公开本身是常见做法，安全性不应依赖“源码保密”。真正需要保密的是：

- 私钥
- 管理员凭据
- 未公开的业务敏感数据
- 加密密钥

即使不公开源码，只要合约已经部署到链上，字节码仍然是公开可分析的。因此：

- 可以公开合约源码
- 不要公开部署私钥和生产环境密钥
- 不要把历史部署日志、热钱包关联文档、真实生产配置一起放进公开仓库

## 额外说明

- 当前公开仓库运行后端时，只需要正确配置 `ETH_RPC_URL`、`ETH_CONTRACT_ADDRESS`、`ETH_PRIVATE_KEY`
- 如果你后续升级了链上合约接口，需要同步更新 `backend/app/contracts/cold_chain_monitor_v3_abi.json`
