# 基于以太坊的冷链运输监控系统

这是一个面向冷链运输场景的最小公开代码仓库，保留当前项目的核心程序代码与脱敏后的设备/合约源码。

## 包含内容

- `backend/`：FastAPI + SQLAlchemy 后端
- `frontend/`：React + TypeScript + Vite 前端
- `contracts/ColdChainMonitorV3.sol`：当前最终版智能合约源码
- `Arduino/esp32.ino`：脱敏后的 ESP32 示例代码
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
├── Dockerfile
├── docker-compose.yml
└── README.md
```

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

启动示例：

```bash
docker build -t cold-chain-monitor .
docker run --env-file backend/.env -p 8080:8000 cold-chain-monitor
```

或使用 Compose：

```bash
docker compose up --build -d
```

默认对外开放 `8080`，访问：

- 前端：`http://127.0.0.1:8080/`
- API：`http://127.0.0.1:8080/api/*`
- WebSocket：`ws://127.0.0.1:8080/ws/*`

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
