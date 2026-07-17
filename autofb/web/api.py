"""FastAPI entrypoint for the first multi-tenant AutoFB application slice."""
from __future__ import annotations

import os
import shutil
import uuid
from datetime import UTC, datetime, timedelta
from functools import lru_cache
from pathlib import Path

from fastapi import Depends, FastAPI, HTTPException, UploadFile, status
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel, Field

from .database import Database
from .oauth import MetaOAuth, MetaOAuthSettings, OAuthError
from .service import AutoFBService, ServiceError

bearer = HTTPBearer(auto_error=False)


class RegisterRequest(BaseModel):
    email: str
    password: str = Field(min_length=12, max_length=256)
    display_name: str = Field(min_length=1, max_length=120)


class LoginRequest(BaseModel):
    email: str
    password: str


class WorkspaceRequest(BaseModel):
    name: str = Field(min_length=1, max_length=120)


class AddMemberRequest(BaseModel):
    email: str
    role: str


class PostRequest(BaseModel):
    page_id: str
    body: str = Field(min_length=1, max_length=5000)


class ScheduleRequest(BaseModel):
    scheduled_at: str
    timezone: str = Field(min_length=1, max_length=64)


@lru_cache
def service() -> AutoFBService:
    database = Database(Path(os.environ.get("AUTOFB_DATABASE_PATH", "autofb.db")))
    database.initialize()
    return AutoFBService(database)


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
    except ServiceError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc


def meta_oauth() -> MetaOAuth:
    try:
        return MetaOAuth(MetaOAuthSettings.from_environment())
    except OAuthError as exc:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(exc)) from exc


app = FastAPI(title="AutoFB API", version="0.1.0")
STATIC_DIR = Path(__file__).with_name("static")
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


@app.get("/", include_in_schema=False)
def dashboard() -> FileResponse:
    return FileResponse(STATIC_DIR / "index.html")


@app.get("/healthz")
def healthz() -> dict[str, str]:
    service()
    return {"status": "ok"}


@app.post("/api/v1/auth/register", status_code=status.HTTP_201_CREATED)
def register(payload: RegisterRequest) -> dict[str, str]:
    return operation(lambda: service().register(payload.email, payload.password, payload.display_name))


@app.post("/api/v1/auth/login")
def login(payload: LoginRequest) -> dict[str, str]:
    token = operation(lambda: service().login(payload.email, payload.password))
    return {"access_token": token, "token_type": "bearer"}


@app.post("/api/v1/auth/logout", status_code=status.HTTP_204_NO_CONTENT)
def logout(credentials: HTTPAuthorizationCredentials | None = Depends(bearer)) -> None:
    if credentials is not None and credentials.scheme.lower() == "bearer":
        service().logout(credentials.credentials)


@app.get("/api/v1/me")
def me(user: dict[str, str] = Depends(current_user)) -> dict[str, str]:
    return user


@app.get("/api/v1/workspaces")
def workspaces(user: dict[str, str] = Depends(current_user)) -> list[dict[str, str]]:
    return service().list_workspaces(user["id"])


@app.post("/api/v1/workspaces", status_code=status.HTTP_201_CREATED)
def create_workspace(payload: WorkspaceRequest, user: dict[str, str] = Depends(current_user)) -> dict[str, str]:
    return operation(lambda: service().create_workspace(user["id"], payload.name))


@app.put("/api/v1/workspaces/{workspace_id}/members")
def add_member(workspace_id: str, payload: AddMemberRequest, user: dict[str, str] = Depends(current_user)) -> dict[str, str]:
    return operation(lambda: service().add_member(user["id"], workspace_id, payload.email, payload.role))


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


@app.get("/api/v1/workspaces/{workspace_id}/posts")
def posts(workspace_id: str, user: dict[str, str] = Depends(current_user)) -> list[dict[str, str]]:
    return operation(lambda: service().list_posts(user["id"], workspace_id))


@app.post("/api/v1/workspaces/{workspace_id}/posts", status_code=status.HTTP_201_CREATED)
def create_post(workspace_id: str, payload: PostRequest, user: dict[str, str] = Depends(current_user)) -> dict[str, str]:
    return operation(lambda: service().create_post(user["id"], workspace_id, payload.page_id, payload.body))


@app.post("/api/v1/workspaces/{workspace_id}/posts/{post_id}/schedule", status_code=status.HTTP_201_CREATED)
def schedule_post(workspace_id: str, post_id: str, payload: ScheduleRequest, user: dict[str, str] = Depends(current_user)) -> dict[str, str]:
    return operation(lambda: service().schedule_post(user["id"], workspace_id, post_id, payload.scheduled_at, payload.timezone))


@app.get("/api/v1/workspaces/{workspace_id}/facebook/connections")
def facebook_connections(workspace_id: str, user: dict[str, str] = Depends(current_user)) -> list[dict[str, str]]:
    return operation(lambda: service().connection_health(user["id"], workspace_id))


@app.get("/api/v1/workspaces/{workspace_id}/notifications")
def notifications(workspace_id: str, user: dict[str, str] = Depends(current_user)) -> list[dict[str, str]]:
    return operation(lambda: service().list_notifications(user["id"], workspace_id))


@app.get("/api/v1/workspaces/{workspace_id}/media")
def media(workspace_id: str, user: dict[str, str] = Depends(current_user)) -> list[dict[str, str]]:
    return operation(lambda: service().list_media(user["id"], workspace_id))


@app.post("/api/v1/workspaces/{workspace_id}/media", status_code=status.HTTP_201_CREATED)
def upload_media(workspace_id: str, file: UploadFile, user: dict[str, str] = Depends(current_user)) -> dict[str, str]:
    allowed = {"image/jpeg", "image/png", "video/mp4"}
    if file.content_type not in allowed:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Only JPEG, PNG, and MP4 media are supported")
    directory = Path(os.environ.get("AUTOFB_MEDIA_DIR", "media")) / workspace_id
    directory.mkdir(parents=True, exist_ok=True)
    safe_name = Path(file.filename or "upload").name
    storage_path = directory / f"{uuid.uuid4()}-{safe_name}"
    with storage_path.open("wb") as target:
        shutil.copyfileobj(file.file, target)
    return operation(lambda: service().register_media(user["id"], workspace_id, safe_name, str(storage_path), file.content_type or "application/octet-stream", storage_path.stat().st_size))
