"""FastAPI entrypoint for the first multi-tenant AutoFB application slice."""
from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path

from fastapi import Depends, FastAPI, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel, Field

from .database import Database
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


app = FastAPI(title="AutoFB API", version="0.1.0")


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
