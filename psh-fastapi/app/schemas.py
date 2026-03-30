from __future__ import annotations

from pydantic import BaseModel, Field


class LoginRequest(BaseModel):
    username: str
    password: str


class LoginResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"


class MeResponse(BaseModel):
    id: int
    username: str


class TokenCreateRequest(BaseModel):
    name: str = Field(min_length=1, max_length=100)


class ApiTokenResponse(BaseModel):
    id: int
    name: str
    token_prefix: str
    created_at: str
    last_used_at: str | None = None


class ApiTokenCreateResponse(ApiTokenResponse):
    token: str


class ServiceResponse(BaseModel):
    id: int
    name: str
    folder_name: str
    archive_name: str
    status: str
    pid: int | None
    created_at: str
    updated_at: str


class UploadServiceResponse(ServiceResponse):
    setup_logs: list[str]


class UploadJobStartResponse(BaseModel):
    job_id: str


class UploadJobStatusResponse(BaseModel):
    job_id: str
    status: str
    setup_logs: list[str]
    error_message: str | None = None
    service: ServiceResponse | None = None


class ServiceLogsResponse(BaseModel):
    stdout: list[str]
    stderr: list[str]
