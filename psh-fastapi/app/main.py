from __future__ import annotations

import re
import shutil
from pathlib import Path
from tempfile import NamedTemporaryFile

from fastapi import Depends, FastAPI, File, Form, Header, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from .auth import (
    authenticate_user,
    create_api_token,
    delete_api_token,
    ensure_default_user,
    get_user_from_api_token,
    get_user_from_bearer,
    issue_jwt,
    list_api_tokens,
    revoke_jwt,
)
from .config import SERVICES_DIR, STATIC_DIR, TMP_DIR, ensure_dirs
from .db import get_db, init_db, utcnow_iso
from .schemas import (
    ApiTokenCreateResponse,
    ApiTokenResponse,
    LoginRequest,
    LoginResponse,
    MeResponse,
    ServiceLogsResponse,
    ServiceResponse,
    TokenCreateRequest,
)
from .service_manager import ServiceManager

app = FastAPI(title="Py Server Hub API", version="0.1.0")
service_manager = ServiceManager()


def slugify(value: str) -> str:
    clean = re.sub(r"[^a-zA-Z0-9_-]+", "-", value.strip().lower())
    clean = clean.strip("-")
    return clean or "service"


def get_current_user(authorization: str | None = Header(default=None)):
    return get_user_from_bearer(authorization)


def get_service_actor(
    authorization: str | None = Header(default=None),
    x_api_token: str | None = Header(default=None, alias="X-API-Token"),
):
    if authorization and authorization.lower().startswith("bearer "):
        return get_user_from_bearer(authorization)
    return get_user_from_api_token(x_api_token)


@app.on_event("startup")
def startup() -> None:
    ensure_dirs()
    init_db()
    ensure_default_user()
    service_manager.mark_all_stopped()


@app.post("/api/auth/login", response_model=LoginResponse)
def login(payload: LoginRequest):
    user = authenticate_user(payload.username, payload.password)
    if not user:
        raise HTTPException(status_code=401, detail="Invalid credentials")
    token = issue_jwt(user["id"], user["username"])
    return LoginResponse(access_token=token)


@app.get("/api/auth/me", response_model=MeResponse)
def me(user=Depends(get_current_user)):
    return MeResponse(id=user["id"], username=user["username"])


@app.post("/api/auth/logout")
def logout(user=Depends(get_current_user)):
    revoke_jwt(user["jti"], user["id"])
    return {"ok": True}


@app.get("/api/tokens", response_model=list[ApiTokenResponse])
def get_tokens(user=Depends(get_current_user)):
    return [ApiTokenResponse(**token) for token in list_api_tokens(user["id"])]


@app.post("/api/tokens", response_model=ApiTokenCreateResponse)
def add_token(payload: TokenCreateRequest, user=Depends(get_current_user)):
    return ApiTokenCreateResponse(**create_api_token(user["id"], payload.name.strip()))


@app.delete("/api/tokens/{token_id}")
def remove_token(token_id: int, user=Depends(get_current_user)):
    delete_api_token(user["id"], token_id)
    return {"ok": True}


@app.get("/api/services", response_model=list[ServiceResponse])
def list_services(_=Depends(get_service_actor)):
    service_manager.sync_process_states()
    with get_db() as conn:
        rows = conn.execute("SELECT * FROM services ORDER BY id DESC").fetchall()
    return [ServiceResponse(**dict(row)) for row in rows]


@app.post("/api/services/upload", response_model=ServiceResponse)
async def upload_service(
    file: UploadFile = File(...),
    name: str | None = Form(default=None),
    _=Depends(get_service_actor),
):
    filename = file.filename or "service.zip"
    if not filename.lower().endswith((".zip", ".7z")):
        raise HTTPException(status_code=400, detail="Only .zip and .7z uploads are supported")

    base_name = Path(filename).stem
    service_name = (name or base_name).strip()
    folder_slug = slugify(service_name)

    with get_db() as conn:
        existing = conn.execute(
            "SELECT id FROM services WHERE name = ? OR folder_name = ?",
            (service_name, folder_slug),
        ).fetchone()
    if existing:
        raise HTTPException(status_code=409, detail="A service with this name already exists")

    archive_suffix = Path(filename).suffix
    destination = SERVICES_DIR / folder_slug

    tmp_file_path: Path | None = None
    try:
        with NamedTemporaryFile(delete=False, suffix=archive_suffix, dir=TMP_DIR) as temp_handle:
            content = await file.read()
            temp_handle.write(content)
            tmp_file_path = Path(temp_handle.name)

        service_manager.extract_archive(tmp_file_path, destination)
        service_manager.create_venv_and_install(destination)
    except Exception as exc:
        if destination.exists():
            shutil.rmtree(destination, ignore_errors=True)
        raise HTTPException(status_code=400, detail=f"Upload failed: {exc}") from exc
    finally:
        await file.close()
        if tmp_file_path and tmp_file_path.exists():
            tmp_file_path.unlink(missing_ok=True)

    now = utcnow_iso()
    with get_db() as conn:
        cursor = conn.execute(
            """
            INSERT INTO services (name, folder_name, archive_name, status, pid, created_at, updated_at)
            VALUES (?, ?, ?, ?, NULL, ?, ?)
            """,
            (service_name, folder_slug, filename, "stopped", now, now),
        )
        row = conn.execute("SELECT * FROM services WHERE id = ?", (cursor.lastrowid,)).fetchone()
    return ServiceResponse(**dict(row))


def _load_service(service_id: int) -> dict:
    service_manager.sync_process_states()
    with get_db() as conn:
        row = conn.execute("SELECT * FROM services WHERE id = ?", (service_id,)).fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="Service not found")
    return dict(row)


@app.get("/api/services/{service_id}", response_model=ServiceResponse)
def get_service(service_id: int, _=Depends(get_service_actor)):
    return ServiceResponse(**_load_service(service_id))


@app.post("/api/services/{service_id}/start", response_model=ServiceResponse)
def start_service(service_id: int, _=Depends(get_service_actor)):
    service = _load_service(service_id)
    return ServiceResponse(**service_manager.start(service))


@app.post("/api/services/{service_id}/stop")
def stop_service(service_id: int, _=Depends(get_service_actor)):
    _load_service(service_id)
    service_manager.stop(service_id)
    return {"ok": True}


@app.get("/api/services/{service_id}/logs", response_model=ServiceLogsResponse)
def get_service_logs(service_id: int, lines: int = 200, _=Depends(get_service_actor)):
    _load_service(service_id)
    safe_lines = max(20, min(lines, 2000))
    return ServiceLogsResponse(
        stdout=service_manager.tail_log(service_manager.stdout_log_path(service_id), safe_lines),
        stderr=service_manager.tail_log(service_manager.stderr_log_path(service_id), safe_lines),
    )


@app.delete("/api/services/{service_id}")
def delete_service(service_id: int, _=Depends(get_service_actor)):
    service = _load_service(service_id)
    service_manager.stop(service_id)
    service_manager.remove_service_dir(service["folder_name"])
    service_manager.stdout_log_path(service_id).unlink(missing_ok=True)
    service_manager.stderr_log_path(service_id).unlink(missing_ok=True)
    with get_db() as conn:
        conn.execute("DELETE FROM services WHERE id = ?", (service_id,))
    return {"ok": True}


app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

if (STATIC_DIR / "assets").exists():
    app.mount("/assets", StaticFiles(directory=STATIC_DIR / "assets"), name="assets")


@app.get("/{full_path:path}", include_in_schema=False)
def serve_spa(full_path: str):
    if full_path.startswith("api/"):
        return JSONResponse({"detail": "Not found"}, status_code=404)
    candidate = STATIC_DIR / full_path
    if full_path and candidate.is_file():
        return FileResponse(candidate)
    index_file = STATIC_DIR / "index.html"
    if index_file.exists():
        return FileResponse(index_file)
    return JSONResponse(
        {"detail": "Frontend build not found. Run npm run pybuild in psh-react."},
        status_code=404,
    )
