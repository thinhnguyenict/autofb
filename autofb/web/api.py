"""FastAPI entrypoint for the first multi-tenant AutoFB application slice."""
from __future__ import annotations

import json
import logging
import os
import sqlite3
import time
import os
import shutil
import uuid
from datetime import UTC, datetime, timedelta
from functools import lru_cache
from pathlib import Path

from fastapi import Depends, FastAPI, HTTPException, UploadFile, status
from fastapi.responses import FileResponse, Response
from fastapi.staticfiles import StaticFiles
from starlette.middleware.base import BaseHTTPMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from starlette.middleware.base import BaseHTTPMiddleware
from fastapi import Depends, FastAPI, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel, Field

from .database import Database
from .oauth import MetaOAuth, MetaOAuthSettings, OAuthError
from .observability import ErrorReportLimiter, configure_logging, report_unhandled_error, request_id
from .readiness import backup_readiness_report, readiness_report, worker_readiness_report
from .security import http_security_headers
from .service import AuthenticationThrottled, AutoFBService, ServiceError
from .storage import LocalMediaStorage, MediaStorageError, S3MediaStorage, media_storage_from_environment

bearer = HTTPBearer(auto_error=False)
application_logger = configure_logging("autofb.api")
error_report_limiter = ErrorReportLimiter()
from .service import AutoFBService, ServiceError

bearer = HTTPBearer(auto_error=False)


class RegisterRequest(BaseModel):
    email: str
    password: str = Field(min_length=12, max_length=256)
    display_name: str = Field(min_length=1, max_length=120)


class LoginRequest(BaseModel):
    email: str
    password: str


class ChangePasswordRequest(BaseModel):
    current_password: str
    new_password: str = Field(min_length=12, max_length=256)


class ProfileRequest(BaseModel):
    display_name: str = Field(min_length=1, max_length=120)


class DeleteAccountRequest(BaseModel):
    password: str = Field(min_length=1, max_length=256)


class WorkspaceRequest(BaseModel):
    name: str = Field(min_length=1, max_length=120)


class AddMemberRequest(BaseModel):
    email: str
    role: str


class ManualFacebookPageRequest(BaseModel):
    facebook_page_id: str = Field(min_length=1, max_length=128)
    name: str = Field(min_length=1, max_length=255)
    page_access_token: str = Field(min_length=1, max_length=4096)
    expires_at: str | None = None


class PostRequest(BaseModel):
    page_id: str
    body: str = Field(min_length=1, max_length=5000)
    media_ids: list[str] = Field(default_factory=list)


class PostUpdateRequest(BaseModel):
    body: str | None = Field(default=None, min_length=1, max_length=5000)
    media_ids: list[str] | None = None


class ScheduleRequest(BaseModel):
    scheduled_at: str
    timezone: str = Field(min_length=1, max_length=64)


class ApprovalRequest(BaseModel):
    comment: str | None = Field(default=None, max_length=1000)


class ApprovalReviewRequest(BaseModel):
    decision: str
    comment: str | None = Field(default=None, max_length=1000)


@lru_cache
def service() -> AutoFBService:
    database = Database(Path(os.environ.get("AUTOFB_DATABASE_PATH", "autofb.db")))
    database.initialize()
    return AutoFBService(database)


@lru_cache
def media_storage() -> LocalMediaStorage | S3MediaStorage:
    return media_storage_from_environment()


def current_user(credentials: HTTPAuthorizationCredentials | None = Depends(bearer)) -> dict[str, str]:
    if credentials is None or credentials.scheme.lower() != "bearer":
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Authentication required")
    user = service().user_for_token(credentials.credentials)
    if user is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid or expired session")
    return user


def operation(fn):
    try:
        return fn()
    except AuthenticationThrottled as exc:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=str(exc),
            headers={"Retry-After": "900"},
        ) from exc
    except ServiceError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc


def meta_oauth() -> MetaOAuth:
    try:
        return MetaOAuth(MetaOAuthSettings.from_environment())
    except OAuthError as exc:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(exc)) from exc


def oauth_environment_status() -> dict[str, object]:
    values = {
        "app_id": os.environ.get("META_APP_ID", ""),
        "app_secret": os.environ.get("META_APP_SECRET", ""),
        "redirect_uri": os.environ.get("META_REDIRECT_URI", ""),
        "encryption_key": os.environ.get("AUTOFB_TOKEN_ENCRYPTION_KEY", ""),
    }
    missing = [name for name, value in values.items() if not value]
    return {
        "configured": not missing,
        "missing": missing,
        "redirect_uri": values["redirect_uri"],
        "graph_version": os.environ.get("META_GRAPH_VERSION", "v25.0"),
        "scopes": os.environ.get("META_OAUTH_SCOPES", "pages_show_list,pages_manage_posts"),
    }


def encrypt_runtime_token(value: str) -> str:
    encryption_key = os.environ.get("AUTOFB_TOKEN_ENCRYPTION_KEY", "")
    if not encryption_key:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="AUTOFB_TOKEN_ENCRYPTION_KEY is required")
    from cryptography.fernet import Fernet

    return Fernet(encryption_key.encode()).encrypt(value.encode()).decode()


app = FastAPI(title="AutoFB API", version="0.1.0")


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request, call_next):
        correlation_id = request_id(request.headers.get("X-Request-ID"))
        started = time.monotonic()
        try:
            response = await call_next(request)
        except Exception as exc:
            application_logger.exception(
                "api.unhandled_error",
                extra={"request_id": correlation_id, "method": request.method, "path": request.url.path},
            )
            error_type = type(exc).__name__
            if error_report_limiter.allow(request.method, request.url.path, error_type):
                report_unhandled_error(
                    os.environ.get("AUTOFB_ERROR_WEBHOOK_URL", ""),
                    request_id_value=correlation_id,
                    method=request.method,
                    path=request.url.path,
                    error_type=error_type,
                    bearer_token=os.environ.get("AUTOFB_ERROR_WEBHOOK_TOKEN") or None,
                )
            raise
        duration_ms = round((time.monotonic() - started) * 1000, 2)
        application_logger.info(
            "api.request",
            extra={
                "request_id": correlation_id,
                "method": request.method,
                "path": request.url.path,
                "status_code": response.status_code,
                "duration_ms": duration_ms,
            },
        )
        response.headers["X-Request-ID"] = correlation_id
        enable_hsts = os.environ.get("AUTOFB_ENABLE_HSTS", "").lower() in {"1", "true", "yes"}
        response.headers.update(http_security_headers(request.url.path, enable_hsts=enable_hsts))
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Referrer-Policy"] = "same-origin"
        response.headers["Cache-Control"] = "no-store" if request.url.path.startswith("/api/") else "public, max-age=3600"
        return response


app.add_middleware(SecurityHeadersMiddleware)
STATIC_DIR = Path(__file__).with_name("static")
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


@app.get("/", include_in_schema=False)
def dashboard() -> FileResponse:
    return FileResponse(STATIC_DIR / "index.html")


@app.get("/healthz")
def healthz() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/readyz")
def readyz(response: Response) -> dict[str, object]:
    database_failed = False
    try:
        service()
    except (OSError, sqlite3.Error):
        database_failed = True
    report = readiness_report(
        os.environ.get("AUTOFB_DATABASE_PATH", "autofb.db"),
        os.environ.get("AUTOFB_MEDIA_DIR", "media"),
        media_backend=os.environ.get("AUTOFB_MEDIA_BACKEND", "local"),
        s3_bucket=os.environ.get("AUTOFB_S3_BUCKET", ""),
        s3_endpoint_url=os.environ.get("AUTOFB_S3_ENDPOINT_URL") or None,
        s3_region=os.environ.get("AUTOFB_S3_REGION") or None,
    )
    if database_failed:
        report["checks"]["database"] = "error"
        report["status"] = "not_ready"
    if report["status"] != "ready":
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
    return report


@app.get("/workerz")
def workerz(response: Response) -> dict[str, object]:
    report = worker_readiness_report(
        os.environ.get("AUTOFB_DATABASE_PATH", "autofb.db"),
        int(os.environ.get("AUTOFB_WORKER_MAX_HEARTBEAT_AGE", "300")),
    )
    if report["status"] != "ready":
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
    return report


@app.get("/backupz")
def backupz(response: Response) -> dict[str, object]:
    report = backup_readiness_report(
        os.environ.get("AUTOFB_DATABASE_PATH", "autofb.db"),
        int(os.environ.get("AUTOFB_BACKUP_MAX_AGE", "172800")),
    )
    if report["status"] != "ready":
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
    return report


    service()
    return {"status": "ok"}


@app.post("/api/v1/auth/register", status_code=status.HTTP_201_CREATED)
def register(payload: RegisterRequest) -> dict[str, str]:
    return operation(lambda: service().register(payload.email, payload.password, payload.display_name))


@app.post("/api/v1/auth/login")
def login(payload: LoginRequest) -> dict[str, str]:
    token = operation(lambda: service().login(payload.email, payload.password))
    return {"access_token": token, "token_type": "bearer"}


@app.post("/api/v1/auth/logout")
def logout(credentials: HTTPAuthorizationCredentials | None = Depends(bearer)) -> dict[str, str]:
    if credentials is not None and credentials.scheme.lower() == "bearer":
        service().logout(credentials.credentials)
    return {"status": "ok"}
@app.post("/api/v1/auth/logout", status_code=status.HTTP_204_NO_CONTENT)
def logout(credentials: HTTPAuthorizationCredentials | None = Depends(bearer)) -> None:
    if credentials is not None and credentials.scheme.lower() == "bearer":
        service().logout(credentials.credentials)


@app.get("/api/v1/me")
def me(user: dict[str, str] = Depends(current_user)) -> dict[str, str]:
    return user


@app.patch("/api/v1/me")
def update_profile(payload: ProfileRequest, user: dict[str, str] = Depends(current_user)) -> dict[str, str]:
    return operation(lambda: service().update_profile(user["id"], payload.display_name))


@app.post("/api/v1/me/password")
def change_password(payload: ChangePasswordRequest, user: dict[str, str] = Depends(current_user)) -> dict[str, str]:
    return operation(lambda: service().change_password(user["id"], payload.current_password, payload.new_password))


@app.delete("/api/v1/me")
def delete_account(payload: DeleteAccountRequest, user: dict[str, str] = Depends(current_user)) -> dict[str, str]:
    return operation(lambda: service().delete_account(user["id"], payload.password))


@app.get("/api/v1/workspaces")
def workspaces(user: dict[str, str] = Depends(current_user)) -> list[dict[str, str]]:
    return service().list_workspaces(user["id"])


@app.get("/api/v1/workspaces/{workspace_id}/export")
def export_workspace(workspace_id: str, user: dict[str, str] = Depends(current_user)) -> Response:
    payload = operation(lambda: service().export_workspace_data(user["id"], workspace_id))
    headers = {"Content-Disposition": f'attachment; filename="autofb-workspace-{workspace_id}.json"'}
    return Response(content=json.dumps(payload, ensure_ascii=False, indent=2), media_type="application/json", headers=headers)


@app.post("/api/v1/workspaces", status_code=status.HTTP_201_CREATED)
def create_workspace(payload: WorkspaceRequest, user: dict[str, str] = Depends(current_user)) -> dict[str, str]:
    return operation(lambda: service().create_workspace(user["id"], payload.name))


@app.patch("/api/v1/workspaces/{workspace_id}")
def update_workspace(workspace_id: str, payload: WorkspaceRequest, user: dict[str, str] = Depends(current_user)) -> dict[str, str]:
    return operation(lambda: service().update_workspace(user["id"], workspace_id, payload.name))


@app.delete("/api/v1/workspaces/{workspace_id}")
def delete_workspace(workspace_id: str, user: dict[str, str] = Depends(current_user)) -> dict[str, str]:
    result = operation(lambda: service().delete_workspace(user["id"], workspace_id))
    for media_path in result.pop("media_paths"):
        try:
            media_storage().delete(media_path)
        except MediaStorageError:
            logging.warning("Skipped unsafe media path while deleting workspace %s", workspace_id)
    return result


@app.put("/api/v1/workspaces/{workspace_id}/members")
def add_member(workspace_id: str, payload: AddMemberRequest, user: dict[str, str] = Depends(current_user)) -> dict[str, str]:
    return operation(lambda: service().add_member(user["id"], workspace_id, payload.email, payload.role))


@app.get("/api/v1/workspaces/{workspace_id}/members")
def members(workspace_id: str, user: dict[str, str] = Depends(current_user)) -> list[dict[str, str]]:
    return operation(lambda: service().list_members(user["id"], workspace_id))


@app.delete("/api/v1/workspaces/{workspace_id}/members/{member_id}")
def remove_member(workspace_id: str, member_id: str, user: dict[str, str] = Depends(current_user)) -> dict[str, str]:
    return operation(lambda: service().remove_member(user["id"], workspace_id, member_id))


@app.get("/api/v1/workspaces/{workspace_id}/summary")
def workspace_summary(workspace_id: str, user: dict[str, str] = Depends(current_user)) -> dict[str, int]:
    return operation(lambda: service().workspace_summary(user["id"], workspace_id))


@app.post("/api/v1/workspaces/{workspace_id}/facebook/connect")
def start_facebook_connect(workspace_id: str, user: dict[str, str] = Depends(current_user)) -> dict[str, str]:
    state = operation(lambda: service().create_oauth_state(user["id"], workspace_id))
    return {"authorization_url": meta_oauth().authorization_url(state)}


@app.get("/api/v1/oauth/facebook/callback")
def facebook_callback(code: str = "", state: str = "", error: str = "") -> dict[str, str]:
    if error:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"Meta authorization failed: {error}")
    if not code or not state:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="OAuth code and state are required")
    context = operation(lambda: service().consume_oauth_state(state))
    try:
        provider_user_id, display_name, pages, encrypted_token, expires_in = meta_oauth().exchange_and_discover(code)
    except OAuthError as exc:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc)) from exc
    expires_at = (datetime.now(UTC) + timedelta(seconds=expires_in)).isoformat() if expires_in else None
    return operation(lambda: service().save_facebook_connection(context["workspace_id"], context["actor_id"], provider_user_id, display_name, encrypted_token, expires_at, pages))


@app.get("/api/v1/workspaces/{workspace_id}/facebook/pages")
def facebook_pages(workspace_id: str, user: dict[str, str] = Depends(current_user)) -> list[dict[str, str]]:
    return operation(lambda: service().list_facebook_pages(user["id"], workspace_id))


@app.post("/api/v1/workspaces/{workspace_id}/facebook/pages/manual", status_code=status.HTTP_201_CREATED)
def import_facebook_page(workspace_id: str, payload: ManualFacebookPageRequest, user: dict[str, str] = Depends(current_user)) -> dict[str, str]:
    encrypted_token = encrypt_runtime_token(payload.page_access_token)
    return operation(lambda: service().import_facebook_page(user["id"], workspace_id, payload.facebook_page_id, payload.name, encrypted_token, payload.expires_at))


@app.delete("/api/v1/workspaces/{workspace_id}/facebook/pages/{page_id}")
def delete_facebook_page(workspace_id: str, page_id: str, user: dict[str, str] = Depends(current_user)) -> dict[str, str]:
    return operation(lambda: service().delete_facebook_page(user["id"], workspace_id, page_id))


@app.get("/api/v1/workspaces/{workspace_id}/posts")
def posts(workspace_id: str, status_filter: str | None = None, user: dict[str, str] = Depends(current_user)) -> list[dict[str, str]]:
    return operation(lambda: service().list_posts(user["id"], workspace_id, status_filter))


@app.get("/api/v1/workspaces/{workspace_id}/calendar")
def calendar(workspace_id: str, date_from: str, date_to: str, user: dict[str, str] = Depends(current_user)) -> list[dict[str, str]]:
    return operation(lambda: service().list_calendar(user["id"], workspace_id, date_from, date_to))


@app.get("/api/v1/workspaces/{workspace_id}/posts/export")
def export_posts(workspace_id: str, status_filter: str | None = None, user: dict[str, str] = Depends(current_user)) -> Response:
    csv_body = operation(lambda: service().export_posts_csv(user["id"], workspace_id, status_filter))
    headers = {"Content-Disposition": f'attachment; filename="autofb-posts-{workspace_id}.csv"'}
    return Response(content=csv_body, media_type="text/csv; charset=utf-8", headers=headers)
@app.get("/api/v1/workspaces/{workspace_id}/posts")
def posts(workspace_id: str, user: dict[str, str] = Depends(current_user)) -> list[dict[str, str]]:
    return operation(lambda: service().list_posts(user["id"], workspace_id))


@app.post("/api/v1/workspaces/{workspace_id}/posts", status_code=status.HTTP_201_CREATED)
def create_post(workspace_id: str, payload: PostRequest, user: dict[str, str] = Depends(current_user)) -> dict[str, str]:
    return operation(lambda: service().create_post(user["id"], workspace_id, payload.page_id, payload.body, payload.media_ids))


@app.patch("/api/v1/workspaces/{workspace_id}/posts/{post_id}")
def update_post(workspace_id: str, post_id: str, payload: PostUpdateRequest, user: dict[str, str] = Depends(current_user)) -> dict[str, str]:
    return operation(lambda: service().update_post(user["id"], workspace_id, post_id, payload.body, payload.media_ids))


@app.post("/api/v1/workspaces/{workspace_id}/posts/{post_id}/duplicate", status_code=status.HTTP_201_CREATED)
def duplicate_post(workspace_id: str, post_id: str, user: dict[str, str] = Depends(current_user)) -> dict[str, str]:
    return operation(lambda: service().duplicate_post(user["id"], workspace_id, post_id))


@app.post("/api/v1/workspaces/{workspace_id}/posts/{post_id}/approval")
def request_post_approval(workspace_id: str, post_id: str, payload: ApprovalRequest, user: dict[str, str] = Depends(current_user)) -> dict[str, str | None]:
    return operation(lambda: service().request_post_approval(user["id"], workspace_id, post_id, payload.comment))


@app.post("/api/v1/workspaces/{workspace_id}/posts/{post_id}/approval/review")
def review_post_approval(workspace_id: str, post_id: str, payload: ApprovalReviewRequest, user: dict[str, str] = Depends(current_user)) -> dict[str, str | None]:
    return operation(lambda: service().review_post_approval(user["id"], workspace_id, post_id, payload.decision, payload.comment))
    return operation(lambda: service().create_post(user["id"], workspace_id, payload.page_id, payload.body))


@app.post("/api/v1/workspaces/{workspace_id}/posts/{post_id}/schedule", status_code=status.HTTP_201_CREATED)
def schedule_post(workspace_id: str, post_id: str, payload: ScheduleRequest, user: dict[str, str] = Depends(current_user)) -> dict[str, str]:
    return operation(lambda: service().schedule_post(user["id"], workspace_id, post_id, payload.scheduled_at, payload.timezone))


@app.post("/api/v1/workspaces/{workspace_id}/posts/{post_id}/publish-now", status_code=status.HTTP_201_CREATED)
def publish_post_now(workspace_id: str, post_id: str, user: dict[str, str] = Depends(current_user)) -> dict[str, str]:
    return operation(lambda: service().publish_post_now(user["id"], workspace_id, post_id))


@app.post("/api/v1/workspaces/{workspace_id}/posts/{post_id}/retry", status_code=status.HTTP_201_CREATED)
def retry_failed_post(workspace_id: str, post_id: str, user: dict[str, str] = Depends(current_user)) -> dict[str, str]:
    return operation(lambda: service().retry_failed_post(user["id"], workspace_id, post_id))


@app.post("/api/v1/workspaces/{workspace_id}/posts/{post_id}/cancel")
def cancel_scheduled_post(workspace_id: str, post_id: str, user: dict[str, str] = Depends(current_user)) -> dict[str, int | str]:
    return operation(lambda: service().cancel_scheduled_post(user["id"], workspace_id, post_id))


@app.delete("/api/v1/workspaces/{workspace_id}/posts/{post_id}")
def delete_post(workspace_id: str, post_id: str, user: dict[str, str] = Depends(current_user)) -> dict[str, str]:
    return operation(lambda: service().delete_post(user["id"], workspace_id, post_id))


@app.get("/api/v1/workspaces/{workspace_id}/publish-jobs")
def publish_jobs(workspace_id: str, user: dict[str, str] = Depends(current_user)) -> list[dict[str, str]]:
    return operation(lambda: service().list_publish_jobs(user["id"], workspace_id))


@app.get("/api/v1/workspaces/{workspace_id}/publish-metrics")
def publish_metrics(workspace_id: str, user: dict[str, str] = Depends(current_user)) -> dict[str, int]:
    return operation(lambda: service().publish_metrics(user["id"], workspace_id))


@app.get("/api/v1/workspaces/{workspace_id}/publish-results")
def publish_results(workspace_id: str, user: dict[str, str] = Depends(current_user)) -> list[dict[str, str]]:
    return operation(lambda: service().list_publish_results(user["id"], workspace_id))


@app.get("/api/v1/workspaces/{workspace_id}/facebook/connections")
def facebook_connections(workspace_id: str, user: dict[str, str] = Depends(current_user)) -> list[dict[str, str]]:
    return operation(lambda: service().connection_health(user["id"], workspace_id))


@app.delete("/api/v1/workspaces/{workspace_id}/facebook/connections/{connection_id}")
def delete_facebook_connection(workspace_id: str, connection_id: str, user: dict[str, str] = Depends(current_user)) -> dict[str, str]:
    return operation(lambda: service().delete_facebook_connection(user["id"], workspace_id, connection_id))


@app.post("/api/v1/workspaces/{workspace_id}/facebook/connections/{connection_id}/diagnose")
def diagnose_facebook_connection(workspace_id: str, connection_id: str, user: dict[str, str] = Depends(current_user)) -> dict[str, object]:
    oauth = meta_oauth()
    encrypted_token = operation(lambda: service().connection_token_for_diagnostics(user["id"], workspace_id, connection_id))
    try:
        profile = oauth.inspect_access_token(encrypted_token)
    except OAuthError as exc:
        recorded = operation(lambda: service().record_connection_diagnostic(user["id"], workspace_id, connection_id, "invalid", str(exc)))
        return {"valid": False, **recorded}
    recorded = operation(lambda: service().record_connection_diagnostic(user["id"], workspace_id, connection_id, "valid"))
    return {**profile, **recorded}


@app.get("/api/v1/workspaces/{workspace_id}/facebook/oauth/status")
def facebook_oauth_status(workspace_id: str, user: dict[str, str] = Depends(current_user)) -> dict[str, object]:
    operation(lambda: service().list_members(user["id"], workspace_id))
    return oauth_environment_status()


@app.get("/api/v1/workspaces/{workspace_id}/notifications")
def notifications(workspace_id: str, user: dict[str, str] = Depends(current_user)) -> list[dict[str, str]]:
    return operation(lambda: service().list_notifications(user["id"], workspace_id))


@app.post("/api/v1/workspaces/{workspace_id}/notifications/read")
def mark_notifications_read(workspace_id: str, user: dict[str, str] = Depends(current_user)) -> dict[str, int]:
    return operation(lambda: service().mark_notifications_read(user["id"], workspace_id))


@app.delete("/api/v1/workspaces/{workspace_id}/notifications/read")
def clear_read_notifications(workspace_id: str, user: dict[str, str] = Depends(current_user)) -> dict[str, int]:
    return operation(lambda: service().clear_read_notifications(user["id"], workspace_id))


@app.get("/api/v1/workspaces/{workspace_id}/audit-logs")
def audit_logs(workspace_id: str, user: dict[str, str] = Depends(current_user)) -> list[dict[str, str]]:
    return operation(lambda: service().list_audit_logs(user["id"], workspace_id))


@app.get("/api/v1/workspaces/{workspace_id}/media")
def media(workspace_id: str, user: dict[str, str] = Depends(current_user)) -> list[dict[str, str]]:
    return operation(lambda: service().list_media(user["id"], workspace_id))


@app.post("/api/v1/workspaces/{workspace_id}/media", status_code=status.HTTP_201_CREATED)
def upload_media(workspace_id: str, file: UploadFile, user: dict[str, str] = Depends(current_user)) -> dict[str, str]:
    allowed = {"image/jpeg", "image/png", "video/mp4"}
    if file.content_type not in allowed:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Only JPEG, PNG, and MP4 media are supported")
    operation(lambda: service().assert_media_upload_allowed(user["id"], workspace_id))
    try:
        storage_path, safe_name, size = media_storage().save(
            workspace_id, file.filename or "upload", file.file, file.content_type
        )
    except MediaStorageError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    try:
        return operation(lambda: service().register_media(user["id"], workspace_id, safe_name, str(storage_path), file.content_type or "application/octet-stream", size))
    except Exception:
        media_storage().delete(storage_path)
        raise


@app.delete("/api/v1/workspaces/{workspace_id}/media/{media_id}")
def delete_media(workspace_id: str, media_id: str, user: dict[str, str] = Depends(current_user)) -> dict[str, str]:
    deleted = operation(lambda: service().delete_media(user["id"], workspace_id, media_id))
    media_storage().delete(deleted["storage_path"])
    return {"status": "deleted", "id": deleted["id"]}
    directory = Path(os.environ.get("AUTOFB_MEDIA_DIR", "media")) / workspace_id
    directory.mkdir(parents=True, exist_ok=True)
    safe_name = Path(file.filename or "upload").name
    storage_path = directory / f"{uuid.uuid4()}-{safe_name}"
    with storage_path.open("wb") as target:
        shutil.copyfileobj(file.file, target)
    return operation(lambda: service().register_media(user["id"], workspace_id, safe_name, str(storage_path), file.content_type or "application/octet-stream", storage_path.stat().st_size))
