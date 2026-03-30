from __future__ import annotations

import hashlib
import secrets
import uuid
from datetime import datetime, timedelta, timezone

import jwt
from fastapi import Header, HTTPException, status

from .config import DEFAULT_PASSWORD, DEFAULT_USERNAME, JWT_EXPIRE_MINUTES, JWT_SECRET
from .db import get_db, utcnow_iso


def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    iterations = 240000
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, iterations)
    return f"{iterations}${salt.hex()}${digest.hex()}"


def verify_password(password: str, stored_hash: str) -> bool:
    try:
        iterations_raw, salt_hex, hash_hex = stored_hash.split("$", 2)
        iterations = int(iterations_raw)
        digest = hashlib.pbkdf2_hmac(
            "sha256",
            password.encode("utf-8"),
            bytes.fromhex(salt_hex),
            iterations,
        )
        return secrets.compare_digest(digest.hex(), hash_hex)
    except ValueError:
        return False


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def issue_jwt(user_id: int, username: str) -> str:
    now = datetime.now(timezone.utc)
    expires_at = now + timedelta(minutes=JWT_EXPIRE_MINUTES)
    jti = str(uuid.uuid4())
    payload = {
        "sub": str(user_id),
        "username": username,
        "jti": jti,
        "iat": int(now.timestamp()),
        "exp": int(expires_at.timestamp()),
    }
    token = jwt.encode(payload, JWT_SECRET, algorithm="HS256")
    with get_db() as conn:
        conn.execute(
            """
            INSERT INTO jwt_sessions (user_id, jti, created_at, expires_at, revoked_at)
            VALUES (?, ?, ?, ?, NULL)
            """,
            (user_id, jti, now.isoformat(), expires_at.isoformat()),
        )
    return token


def decode_jwt(token: str) -> dict:
    try:
        return jwt.decode(token, JWT_SECRET, algorithms=["HS256"])
    except jwt.InvalidTokenError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid token",
        ) from exc


def ensure_default_user() -> None:
    with get_db() as conn:
        existing = conn.execute(
            "SELECT id FROM users WHERE username = ?",
            (DEFAULT_USERNAME,),
        ).fetchone()
        if existing:
            return

        conn.execute(
            "INSERT INTO users (username, password_hash, created_at) VALUES (?, ?, ?)",
            (DEFAULT_USERNAME, hash_password(DEFAULT_PASSWORD), utcnow_iso()),
        )


def authenticate_user(username: str, password: str):
    with get_db() as conn:
        row = conn.execute(
            "SELECT id, username, password_hash FROM users WHERE username = ?",
            (username,),
        ).fetchone()
        if not row or not verify_password(password, row["password_hash"]):
            return None
        return {"id": row["id"], "username": row["username"]}


def get_user_from_bearer(authorization: str | None) -> dict:
    if not authorization or not authorization.lower().startswith("bearer "):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing bearer token",
        )
    token = authorization.split(" ", 1)[1].strip()
    payload = decode_jwt(token)
    jti = payload.get("jti")
    subject = payload.get("sub")
    try:
        user_id = int(subject)
    except (TypeError, ValueError) as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid token subject",
        ) from exc
    with get_db() as conn:
        session = conn.execute(
            """
            SELECT id FROM jwt_sessions
            WHERE jti = ? AND user_id = ? AND revoked_at IS NULL
            """,
            (jti, user_id),
        ).fetchone()
        if not session:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Session revoked",
            )
        user = conn.execute(
            "SELECT id, username FROM users WHERE id = ?",
            (user_id,),
        ).fetchone()
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Unknown user",
        )
    return {"id": user["id"], "username": user["username"], "token": token, "jti": jti}


def revoke_jwt(jti: str, user_id: int) -> None:
    with get_db() as conn:
        conn.execute(
            "UPDATE jwt_sessions SET revoked_at = ? WHERE jti = ? AND user_id = ?",
            (utcnow_iso(), jti, user_id),
        )


def create_api_token(user_id: int, name: str) -> dict:
    raw_token = f"psh_{secrets.token_urlsafe(36)}"
    prefix = raw_token[:14]
    with get_db() as conn:
        cursor = conn.execute(
            """
            INSERT INTO api_tokens (user_id, name, token_prefix, token_hash, created_at, last_used_at)
            VALUES (?, ?, ?, ?, ?, NULL)
            """,
            (user_id, name, prefix, hash_token(raw_token), utcnow_iso()),
        )
        token_id = cursor.lastrowid
        row = conn.execute(
            "SELECT id, name, token_prefix, created_at, last_used_at FROM api_tokens WHERE id = ?",
            (token_id,),
        ).fetchone()
    return {
        "id": row["id"],
        "name": row["name"],
        "token_prefix": row["token_prefix"],
        "created_at": row["created_at"],
        "last_used_at": row["last_used_at"],
        "token": raw_token,
    }


def list_api_tokens(user_id: int) -> list[dict]:
    with get_db() as conn:
        rows = conn.execute(
            """
            SELECT id, name, token_prefix, created_at, last_used_at
            FROM api_tokens
            WHERE user_id = ?
            ORDER BY id DESC
            """,
            (user_id,),
        ).fetchall()
    return [dict(row) for row in rows]


def delete_api_token(user_id: int, token_id: int) -> None:
    with get_db() as conn:
        deleted = conn.execute(
            "DELETE FROM api_tokens WHERE id = ? AND user_id = ?",
            (token_id, user_id),
        ).rowcount
    if deleted == 0:
        raise HTTPException(status_code=404, detail="Token not found")


def get_user_from_api_token(api_token: str | None = Header(default=None, alias="X-API-Token")) -> dict:
    if not api_token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing API token",
        )

    token_hash = hash_token(api_token)
    with get_db() as conn:
        row = conn.execute(
            """
            SELECT users.id AS user_id, users.username
            FROM api_tokens
            JOIN users ON users.id = api_tokens.user_id
            WHERE api_tokens.token_hash = ?
            """,
            (token_hash,),
        ).fetchone()
        if not row:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid API token",
            )
        conn.execute(
            "UPDATE api_tokens SET last_used_at = ? WHERE token_hash = ?",
            (utcnow_iso(), token_hash),
        )
    return {"id": row["user_id"], "username": row["username"], "api_token": api_token}
