"""Smoke-test the AutoFB FastAPI app with an isolated SQLite database."""
from __future__ import annotations

import os
import tempfile
import importlib.util
from pathlib import Path

if importlib.util.find_spec("fastapi") is None:
    raise SystemExit("Missing dependency: fastapi. Run `python -m pip install -r reqs.txt` before this smoke test.")

from fastapi.testclient import TestClient
from autofb.web.api import app, service


def main() -> None:
    with tempfile.TemporaryDirectory() as directory:
        os.environ["AUTOFB_DATABASE_PATH"] = str(Path(directory) / "autofb-smoke.db")
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


if __name__ == "__main__":
    main()
