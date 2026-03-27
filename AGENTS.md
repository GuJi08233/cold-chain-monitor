# Repository Guidelines

## Project Structure & Module Organization

`backend/` contains the FastAPI application, SQLAlchemy models, service layer, WebSocket handlers, scripts, and `backend/tests/`. `frontend/` contains the React + TypeScript + Vite app under `src/`. `contracts/ColdChainMonitorV3.sol` stores the current Solidity contract, and `Arduino/esp32.ino` holds the ESP32 sample firmware. Deployment entrypoints live in `Dockerfile` and `docker-compose.yml`. Long-form design notes are under `文档介绍/`.

## Build, Test, and Development Commands

- `cd backend && pip install -r requirements.txt` installs backend dependencies.
- `cd backend && python -m uvicorn app.main:app --host 127.0.0.1 --port 8000` starts the API locally.
- `cd frontend && npm install && npm run dev` starts the Vite dev server on `5173`.
- `cd frontend && npm run build` builds the production frontend bundle.
- `cd backend && python -m unittest` runs backend tests.
- `docker compose up --build -d` builds the single-image deployment and starts the app on `8080`.
- `docker compose exec app python scripts/seed_system_config.py` syncs runtime config into `system_config`.
- `docker compose exec app python scripts/tdengine_bootstrap.py` initializes TDengine tables.

## Coding Style & Naming Conventions

Use 4 spaces in Python and 2 spaces in frontend TypeScript/TSX to match the existing codebase. Keep Python modules `snake_case`, React components/pages `PascalCase`, and constants `UPPER_SNAKE_CASE`. Prefer small service methods, explicit types in TS, and concise Chinese comments only for non-obvious logic. Frontend type checking relies on `frontend/tsconfig.json` with `strict: true`.

## Testing Guidelines

Backend tests use Python `unittest` and live in `backend/tests/` with names like `test_chain_service.py` and `test_time_utils.py`. Add or update tests when changing hashing, chain retry, time handling, or system config behavior. For targeted runs, use `cd backend && python -m unittest tests.test_chain_service tests.test_chain_api`.

## Commit & Pull Request Guidelines

Recent history follows short Conventional Commit-style subjects such as `feat: ...`, `fix: ...`, `docs: ...`, and `chore: ...`. Keep messages imperative and scoped to one change. PRs should summarize behavior changes, list affected areas (`backend`, `frontend`, `contracts`, docs), mention any required `.env` updates, and include screenshots for UI changes.

## Security & Configuration Tips

Never commit `.env`, private keys, MQTT credentials, or production TDengine data. Default local persistence uses `./data` mapped to `/app/data`; avoid rebuilding without a mounted volume. If contract interfaces change, update `backend/app/contracts/cold_chain_monitor_v3_abi.json` together with the Solidity source.
