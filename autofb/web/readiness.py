"""Runtime dependency checks used by the API readiness probe."""
from __future__ import annotations

import sqlite3
import tempfile
from contextlib import closing
from datetime import UTC, datetime, timedelta
from pathlib import Path

from .storage import S3MediaStorage


def readiness_report(
    database_path: str | Path,
    media_directory: str | Path,
    *,
    media_backend: str = "local",
    s3_bucket: str = "",
    s3_endpoint_url: str | None = None,
    s3_region: str | None = None,
    s3_client=None,
) -> dict[str, object]:
    """Return readiness details without exposing filesystem paths or credentials."""
    checks: dict[str, str] = {}

    try:
        database_uri = Path(database_path).resolve().as_uri() + "?mode=rw"
        with closing(sqlite3.connect(database_uri, uri=True, timeout=2)) as connection:
            connection.execute("SELECT 1").fetchone()
        checks["database"] = "ok"
    except (OSError, sqlite3.Error):
        checks["database"] = "error"

    if media_backend == "s3":
        try:
            storage = S3MediaStorage(
                s3_bucket,
                client=s3_client,
                endpoint_url=s3_endpoint_url,
                region_name=s3_region,
            )
            storage.client.head_bucket(Bucket=storage.bucket)
            checks["media_storage"] = "ok"
        except Exception:
            checks["media_storage"] = "error"
    elif media_backend == "local":
        try:
            directory = Path(media_directory)
            directory.mkdir(parents=True, exist_ok=True)
            with tempfile.NamedTemporaryFile(prefix=".autofb-ready-", dir=directory):
                pass
            checks["media_storage"] = "ok"
        except OSError:
            checks["media_storage"] = "error"
    else:
        checks["media_storage"] = "error"

    return {"status": "ready" if all(value == "ok" for value in checks.values()) else "not_ready", "checks": checks}


def worker_readiness_report(database_path: str | Path, max_age_seconds: int = 300) -> dict[str, object]:
    """Report whether at least one worker has sent a recent, non-error heartbeat."""
    if max_age_seconds < 1:
        raise ValueError("max_age_seconds must be at least 1")
    try:
        database_uri = Path(database_path).resolve().as_uri() + "?mode=ro"
        with closing(sqlite3.connect(database_uri, uri=True, timeout=2)) as connection:
            connection.row_factory = sqlite3.Row
            row = connection.execute(
                "SELECT status, last_seen_at FROM worker_heartbeats ORDER BY last_seen_at DESC LIMIT 1"
            ).fetchone()
    except (OSError, sqlite3.Error):
        return {"status": "not_ready", "checks": {"worker": "unavailable"}}
    if row is None:
        return {"status": "not_ready", "checks": {"worker": "missing"}}
    try:
        last_seen = datetime.fromisoformat(row["last_seen_at"])
    except (TypeError, ValueError):
        return {"status": "not_ready", "checks": {"worker": "invalid"}}
    cutoff = datetime.now(UTC) - timedelta(seconds=max_age_seconds)
    worker_status = "ok" if last_seen >= cutoff and row["status"] != "error" else "stale"
    return {
        "status": "ready" if worker_status == "ok" else "not_ready",
        "checks": {"worker": worker_status},
    }


def backup_readiness_report(database_path: str | Path, max_age_seconds: int = 172800) -> dict[str, object]:
    """Report whether the latest off-site backup completed successfully and recently."""
    if max_age_seconds < 1:
        raise ValueError("max_age_seconds must be at least 1")
    try:
        database_uri = Path(database_path).resolve().as_uri() + "?mode=ro"
        with closing(sqlite3.connect(database_uri, uri=True, timeout=2)) as connection:
            connection.row_factory = sqlite3.Row
            row = connection.execute(
                "SELECT status, created_at FROM backup_runs ORDER BY created_at DESC LIMIT 1"
            ).fetchone()
    except (OSError, sqlite3.Error):
        return {"status": "not_ready", "checks": {"backup": "unavailable"}}
    if row is None:
        return {"status": "not_ready", "checks": {"backup": "missing"}}
    if row["status"] != "succeeded":
        return {"status": "not_ready", "checks": {"backup": "failed"}}
    try:
        created_at = datetime.fromisoformat(row["created_at"])
        if created_at.tzinfo is None:
            raise ValueError("backup timestamp must include a timezone")
    except (TypeError, ValueError):
        return {"status": "not_ready", "checks": {"backup": "invalid"}}
    cutoff = datetime.now(UTC) - timedelta(seconds=max_age_seconds)
    backup_status = "ok" if created_at >= cutoff else "stale"
    return {
        "status": "ready" if backup_status == "ok" else "not_ready",
        "checks": {"backup": backup_status},
    }
