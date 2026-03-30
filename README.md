# Py Server Hub

Py Server Hub is a FastAPI + React project for managing uploaded Python service archives (`.zip` or `.7z`) as controlled processes.

## Project layout

- `psh-fastapi`: backend API, auth, service runtime manager, SQLite data store, static serving
- `psh-react`: React TypeScript UI (React Bootstrap + React Router)

## Quick start

1. Backend setup:
   - `cd psh-fastapi`
   - `python -m venv .venv`
   - `.venv\Scripts\activate` (Windows) or `source .venv/bin/activate` (Linux/macOS)
   - `pip install -r requirements.txt`
   - Copy `.env.example` to `.env` and set values (especially `PSH_JWT_SECRET`).
   - Run: `uvicorn app.main:app --reload --host 0.0.0.0 --port 9000`
2. Frontend setup (dev mode):
   - `cd psh-react`
   - `npm install`
   - `npm run dev`
3. Frontend build for backend static serving:
   - `cd psh-react`
   - `npm run pybuild`

After `pybuild`, the backend serves the compiled UI from `psh-fastapi/static`.

## Authentication and stored data

- Default user is auto-created on backend startup from env vars:
  - `PSH_DEFAULT_USERNAME`
  - `PSH_DEFAULT_PASSWORD`
- All auth and service metadata is stored in `psh-fastapi/data/psh.sqlite3`.
- Uploaded/extracted services are stored in `psh-fastapi/data/services`.
- Service logs are stored in `psh-fastapi/data/logs`.
- Mount `psh-fastapi/data` as a Docker volume for persistence later.

## Auth modes

- Browser/user auth: `Authorization: Bearer <jwt>`
- Headless auth: `X-API-Token: <token>`

Create API tokens from UI page **API Tokens** (token value is shown once at creation).

## API endpoints (core)

- `POST /api/auth/login`
- `GET /api/auth/me`
- `POST /api/auth/logout`
- `GET /api/tokens`
- `POST /api/tokens`
- `DELETE /api/tokens/{token_id}`
- `GET /api/services`
- `POST /api/services/upload`
- `GET /api/services/{service_id}`
- `POST /api/services/{service_id}/start`
- `POST /api/services/{service_id}/stop`
- `GET /api/services/{service_id}/logs?lines=200`
- `DELETE /api/services/{service_id}`

## Headless API token examples

Assume:
- `BASE=http://127.0.0.1:9000`
- `TOKEN=<your_api_token>`
- `SERVICE_ID=1`

Upload:

```bash
curl -X POST "$BASE/api/services/upload" \
  -H "X-API-Token: $TOKEN" \
  -F "name=my-service" \
  -F "file=@./my-service.zip"
```

Start:

```bash
curl -X POST "$BASE/api/services/$SERVICE_ID/start" \
  -H "X-API-Token: $TOKEN"
```

Stop:

```bash
curl -X POST "$BASE/api/services/$SERVICE_ID/stop" \
  -H "X-API-Token: $TOKEN"
```

Logs:

```bash
curl "$BASE/api/services/$SERVICE_ID/logs?lines=200" \
  -H "X-API-Token: $TOKEN"
```

Remove:

```bash
curl -X DELETE "$BASE/api/services/$SERVICE_ID" \
  -H "X-API-Token: $TOKEN"
```

## Service upload behavior

When a service archive is uploaded:

1. It is extracted into `data/services/<service-folder>`.
2. Backend validates root contains:
   - `main.py`
   - `requirements.txt`
3. Backend creates `.venv` inside that extracted service directory.
4. Backend installs dependencies from `requirements.txt`.
5. Start uses that `.venv` Python to run `main.py`.

Stop terminates the running process.  
Remove stops it first, then deletes the service folder and related logs.

## Docker reverse proxy routing

`psh-docker/docker-compose.yml` includes an Nginx reverse proxy service.

- Non-matching hosts route to main app (`psh:9000`) for UI/API.
- Hosts matching `^\d+psh\..+$` are routed to that port on the `psh` container.
  - Example: `1234psh.example.com` -> `psh:1234`
- WebSocket upgrades are enabled in `psh-docker/nginx.conf`.
- In double-proxy setups, configure `PSH_PROTO_MODE` in `psh-docker/.env`:
  - `https` (default) forces `X-Forwarded-Proto: https` downstream.
  - `forwarded` uses the incoming forwarded proto from the outer proxy.
  - `http` forces `X-Forwarded-Proto: http`.
  This is applied via `psh-docker/nginx.conf.template`.
