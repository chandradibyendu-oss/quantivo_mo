# Quantivo

Phase 1 is a local API and an Expo app. Sign in with a development code, open Mani's sample calls, and see that an order is refused.

## Run locally

From the repository root:

```powershell
.\start.cmd
.\stop.cmd
.\restart.cmd
```

`start` brings Postgres up only when that container is not already running, applies migrations, seeds Mani's sample calls, then starts the API and the web preview. `restart` stops and starts the API and the preview and leaves Postgres running. `.\restart.cmd database` or `.\start.cmd database` restarts the Postgres container when the container itself must be replaced. Schema changes still apply through migrations and do not need that. This project's API uses port 8001 and the preview uses 8081. A port already taken by another process is left running. Quantivo then tries the next few ports and says which one it chose. The preview is pointed at the API port that was actually chosen. `stop` stops only the processes these scripts recorded. `.\stop.cmd database` also stops this project's database container.

The first run still needs `backend\.venv` and `mobile\node_modules`. See below.

## API

From the repository root:

```powershell
docker compose up -d
cd backend
python -m venv .venv
.\.venv\Scripts\python -m pip install -e ".[dev]"
copy .env.example .env
.\.venv\Scripts\alembic upgrade head
.\.venv\Scripts\python -m app.seed
.\.venv\Scripts\python -m pytest
.\.venv\Scripts\uvicorn app.main:app --reload --port 8001
```

Postgres is published on host port 5433. The development one-time code is returned only when `ENVIRONMENT` is `development` or `test`. Live trading stays off.

## Mobile

```powershell
cd mobile
npm install
npx expo start --web
```

The app calls `http://127.0.0.1:8001` unless `EXPO_PUBLIC_API_URL` is set. On a phone emulator, point that variable at the machine running the API.

The review layout is `mockup/quantivo-mobile.html`. It is not the running client.
