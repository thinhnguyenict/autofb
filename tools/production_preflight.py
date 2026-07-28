"""Validate production prerequisites without printing configured secrets."""
from __future__ import annotations

import json
import os
import sqlite3
from contextlib import closing
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Callable, Mapping
from urllib.parse import urlparse

from autofb.web.readiness import backup_readiness_report, readiness_report, worker_readiness_report
from tools.restore_drill import REQUIRED_TABLES


def public_https_url(value: str) -> bool:
    parsed = urlparse(value)
    host = (parsed.hostname or "").lower()
    return bool(
        parsed.scheme == "https"
        and parsed.netloc
        and host not in {"localhost", "127.0.0.1", "::1"}
        and parsed.username is None
        and parsed.password is None
        and not parsed.query
        and not parsed.fragment
    )


def production_preflight(
    environment: Mapping[str, str], *, encryption_key_validator: Callable[[str], bool]
) -> dict[str, object]:
    checks: dict[str, str] = {}
    required = (
        "META_APP_ID",
        "META_APP_SECRET",
        "META_REDIRECT_URI",
        "AUTOFB_TOKEN_ENCRYPTION_KEY",
        "AUTOFB_BACKUP_ALERT_URL",
        "AUTOFB_ERROR_WEBHOOK_URL",
        "AUTOFB_PUBLIC_URL",
        "AUTOFB_ENABLE_HSTS",
    )
    missing = [name for name in required if not environment.get(name, "").strip()]
    checks["required_environment"] = "ok" if not missing else "error"
    checks["oauth_https_callback"] = "ok" if public_https_url(environment.get("META_REDIRECT_URI", "")) else "error"
    checks["backup_alert_webhook"] = (
        "ok" if public_https_url(environment.get("AUTOFB_BACKUP_ALERT_URL", "")) else "error"
    )
    checks["error_webhook"] = (
        "ok" if public_https_url(environment.get("AUTOFB_ERROR_WEBHOOK_URL", "")) else "error"
    )
    public_url = urlparse(environment.get("AUTOFB_PUBLIC_URL", ""))
    public_origin = (
        public_https_url(environment.get("AUTOFB_PUBLIC_URL", ""))
        and public_url.path in {"", "/"}
        and not public_url.query
        and not public_url.fragment
    )
    checks["public_url"] = "ok" if public_origin else "error"
    redirect = urlparse(environment.get("META_REDIRECT_URI", ""))
    checks["oauth_public_host"] = (
        "ok"
        if public_origin and redirect.hostname and redirect.hostname.lower() == (public_url.hostname or "").lower()
        else "error"
    )
    checks["hsts"] = (
        "ok" if environment.get("AUTOFB_ENABLE_HSTS", "").strip().lower() in {"1", "true", "yes"} else "error"
    )
    key = environment.get("AUTOFB_TOKEN_ENCRYPTION_KEY", "")
    checks["token_encryption_key"] = "ok" if key and encryption_key_validator(key) else "error"

    database_path = environment.get("AUTOFB_DATABASE_PATH", "autofb.db")
    checks.update(
        readiness_report(
            database_path,
            environment.get("AUTOFB_MEDIA_DIR", "media"),
            media_backend=environment.get("AUTOFB_MEDIA_BACKEND", "local"),
            s3_bucket=environment.get("AUTOFB_S3_BUCKET", ""),
            s3_endpoint_url=environment.get("AUTOFB_S3_ENDPOINT_URL") or None,
            s3_region=environment.get("AUTOFB_S3_REGION") or None,
        )["checks"]
    )
    try:
        with closing(sqlite3.connect(f"file:{Path(database_path)}?mode=ro", uri=True)) as connection:
            tables = {row[0] for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")}
            checks["schema"] = "ok" if REQUIRED_TABLES <= tables else "error"
            integrity = connection.execute("PRAGMA integrity_check").fetchone()
            checks["database_integrity"] = "ok" if integrity and integrity[0] == "ok" else "error"
            checks["foreign_keys"] = "ok" if not connection.execute("PRAGMA foreign_key_check").fetchone() else "error"
            checks["admin_account"] = "ok" if connection.execute("SELECT COUNT(*) FROM users").fetchone()[0] else "error"
            checks["facebook_connection"] = (
                "ok" if connection.execute("SELECT 1 FROM oauth_connections LIMIT 1").fetchone() else "error"
            )
            checks["facebook_page"] = (
                "ok" if connection.execute("SELECT 1 FROM facebook_pages LIMIT 1").fetchone() else "error"
            )
            diagnostic_cutoff = (datetime.now(UTC) - timedelta(hours=24)).isoformat()
            recent_diagnostic = connection.execute(
                """SELECT 1
                   FROM facebook_pages
                   JOIN oauth_connections ON oauth_connections.id = facebook_pages.connection_id
                   JOIN token_health_checks ON token_health_checks.connection_id = oauth_connections.id
                   WHERE token_health_checks.id = (
                       SELECT latest.id FROM token_health_checks AS latest
                       WHERE latest.connection_id = oauth_connections.id
                       ORDER BY latest.checked_at DESC LIMIT 1
                   )
                     AND token_health_checks.status = 'valid'
                     AND token_health_checks.checked_at >= ?
                     AND (oauth_connections.expires_at IS NULL OR oauth_connections.expires_at > ?)
                   LIMIT 1""",
                (diagnostic_cutoff, datetime.now(UTC).isoformat()),
            ).fetchone()
            checks["recent_meta_diagnostic"] = "ok" if recent_diagnostic else "error"
    except sqlite3.Error:
        for name in (
            "schema",
            "database_integrity",
            "foreign_keys",
            "admin_account",
            "facebook_connection",
            "facebook_page",
            "recent_meta_diagnostic",
        ):
            checks[name] = "error"
    checks["recent_offsite_backup"] = (
        "ok" if backup_readiness_report(database_path)["checks"]["backup"] == "ok" else "error"
    )
    checks["worker"] = worker_readiness_report(database_path)["checks"]["worker"]
    failed = sorted(name for name, value in checks.items() if value != "ok")
    return {
        "status": "ready" if not failed else "not_ready",
        "checks": checks,
        "failed_checks": failed,
        "missing_environment": missing,
    }


def main() -> int:
    from cryptography.fernet import Fernet

    def valid_fernet_key(value: str) -> bool:
        try:
            Fernet(value.encode())
            return True
        except (TypeError, ValueError):
            return False

    report = production_preflight(os.environ, encryption_key_validator=valid_fernet_key)
    print(json.dumps(report, sort_keys=True))
    return 0 if report["status"] == "ready" else 1


if __name__ == "__main__":
    raise SystemExit(main())
