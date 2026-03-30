from __future__ import annotations

import re
import json
from pathlib import Path
from tempfile import NamedTemporaryFile

from fastapi import Depends, FastAPI, File, Form, Header, HTTPException, Query, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles

from .auth import (
    authenticate_user,
    create_api_token,
    delete_api_token,
    get_user_from_token,
    ensure_default_user,
    get_user_from_api_token,
    get_user_from_bearer,
    issue_jwt,
    list_api_tokens,
    revoke_jwt,
)
from .config import SERVICES_DIR, STATIC_DIR, TMP_DIR, ensure_dirs
from .db import get_db, init_db
from .schemas import (
    ApiTokenCreateResponse,
    ApiTokenResponse,
    LoginRequest,
    LoginResponse,
    MeResponse,
    ServiceLogsResponse,
    ServiceResponse,
    TokenCreateRequest,
    UploadJobStartResponse,
    UploadJobStatusResponse,
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


@app.post("/api/services/upload", response_model=UploadJobStartResponse)
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
            while True:
                chunk = await file.read(1024 * 1024)
                if not chunk:
                    break
                temp_handle.write(chunk)
            tmp_file_path = Path(temp_handle.name)
        job_id = service_manager.create_upload_job(
            user_id=_["id"],
            service_name=service_name,
            folder_slug=folder_slug,
            filename=filename,
            tmp_file_path=tmp_file_path,
        )
        return UploadJobStartResponse(job_id=job_id)
    except Exception as exc:
        if tmp_file_path and tmp_file_path.exists():
            tmp_file_path.unlink(missing_ok=True)
        raise HTTPException(
            status_code=400,
            detail={"message": f"Upload failed before job start: {exc}", "setup_logs": []},
        ) from exc
    finally:
        await file.close()


@app.get("/api/services/upload-jobs/{job_id}", response_model=UploadJobStatusResponse)
def get_upload_job_status(job_id: str, user=Depends(get_service_actor)):
    job = service_manager.get_upload_job(job_id, user["id"])
    service_payload = ServiceResponse(**job["service"]) if job["service"] else None
    return UploadJobStatusResponse(
        job_id=job["job_id"],
        status=job["status"],
        setup_logs=job["setup_logs"],
        error_message=job["error_message"],
        service=service_payload,
    )


def _get_stream_user(token: str | None, authorization: str | None):
    if authorization and authorization.lower().startswith("bearer "):
        return get_user_from_bearer(authorization)
    if token:
        return get_user_from_token(token)
    raise HTTPException(status_code=401, detail="Missing auth token for stream")


@app.get("/api/services/upload-jobs/{job_id}/stream")
def stream_upload_job_logs(
    job_id: str,
    token: str | None = Query(default=None),
    authorization: str | None = Header(default=None),
):
    user = _get_stream_user(token, authorization)

    def event_stream():
        last_index = 0
        while True:
            update = service_manager.wait_upload_job_update(
                job_id=job_id,
                user_id=user["id"],
                last_index=last_index,
                timeout_seconds=20,
            )
            for line in update["lines"]:
                payload = {"type": "log", "line": line}
                yield f"data: {json.dumps(payload)}\n\n"
            last_index = update["next_index"]

            if update["done"]:
                payload = {
                    "type": "done",
                    "status": update["status"],
                    "error_message": update["error_message"],
                    "service": update["service"],
                }
                yield f"data: {json.dumps(payload)}\n\n"
                break

            yield ": keepalive\n\n"

    return StreamingResponse(event_stream(), media_type="text/event-stream")


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
