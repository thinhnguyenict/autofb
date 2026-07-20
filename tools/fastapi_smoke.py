"""Smoke-test the AutoFB API contract with or without FastAPI installed."""
from __future__ import annotations

import importlib.util
import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def _fastapi_smoke(database_path: Path) -> None:
    from fastapi.testclient import TestClient

    from autofb.web.api import app, service

    os.environ["AUTOFB_DATABASE_PATH"] = str(database_path)
    service.cache_clear()
    client = TestClient(app)

    health = client.get("/healthz")
    health.raise_for_status()
    assert health.json() == {"status": "ok"}

    register = client.post(
        "/api/v1/auth/register",
        json={"email": "smoke@example.com", "password": "a-very-strong-password", "display_name": "Smoke"},
    )
    register.raise_for_status()

    login = client.post("/api/v1/auth/login", json={"email": "smoke@example.com", "password": "a-very-strong-password"})
    login.raise_for_status()
    token = login.json()["access_token"]

    workspace = client.post(
        "/api/v1/workspaces",
        json={"name": "Smoke workspace"},
        headers={"Authorization": f"Bearer {token}"},
    )
    workspace.raise_for_status()
    workspace_id = workspace.json()["id"]

    members = client.get(f"/api/v1/workspaces/{workspace_id}/members", headers={"Authorization": f"Bearer {token}"})
    members.raise_for_status()
    assert members.json()[0]["role"] == "owner"
    print("FastAPI smoke test passed")


def _service_contract_smoke(database_path: Path) -> None:
    from autofb.web.database import Database
    from autofb.web.service import AutoFBService

    database = Database(database_path)
    database.initialize()
    service = AutoFBService(database)
    owner = service.register("smoke@example.com", "a-very-strong-password", "Smoke")
    token = service.login("smoke@example.com", "a-very-strong-password")
    assert service.user_for_token(token)["id"] == owner["id"]
    workspace = service.create_workspace(owner["id"], "Smoke workspace")
    assert service.list_members(owner["id"], workspace["id"])[0]["role"] == "owner"
    print("Service contract smoke test passed; install reqs.txt to exercise FastAPI TestClient")


def main() -> None:
    with tempfile.TemporaryDirectory() as directory:
        database_path = Path(directory) / "autofb-smoke.db"
        if importlib.util.find_spec("fastapi") is None:
            _service_contract_smoke(database_path)
            return
        _fastapi_smoke(database_path)


if __name__ == "__main__":
    main()
