# 基于以太坊的冷链运输监控系统

这是一个面向冷链运输场景的全栈项目公开代码仓库，包含：

- `backend/`：FastAPI + SQLAlchemy 后端
- `frontend/`：React + TypeScript + Vite 前端
- `hardhat/`：智能合约、测试与部署模块
- `hardware/`：ESP32 设备侧示例代码

当前仓库只保留程序代码、示例配置和基础部署文件，不包含本地数据库、日志、私钥、部署产物和测试运行结果。

## 核心能力

- 用户与权限：`super_admin / admin / driver`，JWT 鉴权、登录保护、WebSocket 临时票据
- 冷链监控：设备绑定、运单流转、实时监控、异常检测、通知和工单闭环
- 数据接入：MQTT 订阅设备数据并写入 TDengine
- 区块链存证：运单哈希上链、异常开始/结束上链、低 Gas 司机锚点
- 前端展示：管理员端、司机端、图表、轨迹地图、区块浏览器跳转

## 目录说明

```text
.
├── backend/
├── frontend/
├── hardhat/
├── hardware/
├── docker-compose.yml
└── README.md
```

## 环境变量

每个模块都使用自己的 `.env.example`：

- `backend/.env.example`
- `frontend/.env.example`
- `hardhat/.env.example`
- `hardware/.env.example`

复制方式：

```bash
cp backend/.env.example backend/.env
cp frontend/.env.example frontend/.env
cp hardhat/.env.example hardhat/.env
```

说明：

- `hardware/.env.example` 仅作为硬件配置占位清单，ESP32 草图需要手动同步这些值

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
- `hardhat/.env` 中的各网络私钥

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

### 合约

```bash
cd hardhat
npm install
npx hardhat compile
npx hardhat test
```

## Docker

仓库提供了基础容器文件：

- `backend/Dockerfile`
- `frontend/Dockerfile`
- `frontend/nginx.conf`
- `docker-compose.yml`

`docker-compose.yml` 默认将前端静态资源和 `/api`、`/ws` 统一挂在一个入口下，便于单机部署和外部客户端访问。

启动前需要先准备：

- `backend/.env`
- 可访问的 MQTT Broker
- 可访问的 TDengine

启动示例：

```bash
docker compose up --build -d
```

默认对外开放 `8080`，访问：

- 前端：`http://127.0.0.1:8080/`
- API：`http://127.0.0.1:8080/api/*`
- WebSocket：`ws://127.0.0.1:8080/ws/*`

## 合约与公开安全说明

智能合约源码公开本身是常见做法，安全性不应依赖“源码保密”。真正需要保密的是：

- 私钥
- 管理员凭据
- 未公开的业务敏感数据
- 加密密钥

即使不公开源码，只要合约已经部署到链上，字节码仍然是公开可分析的。因此：

- 可以公开合约源码、测试和部署脚本
- 不要公开部署私钥和生产环境密钥
- 不要把历史部署日志、热钱包关联文档、真实生产配置一起放进公开仓库

## 额外说明

- 后端链上交互会读取 Hardhat 部署后生成的 ABI 产物
- 当前公开仓库不提交 `hardhat/ignition/deployments/*` 运行产物
- 如需启用上链功能，请先完成合约部署，再根据部署结果同步后端配置
