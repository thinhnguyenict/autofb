"""Create a verified SQLite backup and upload it to an HTTPS object endpoint."""
from __future__ import annotations

import argparse
import base64
import hashlib
import os
import sqlite3
import sys
import time
import uuid
from contextlib import closing
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import quote

from tools.backup_database import backup_database
from tools.restore_drill import restore_drill


class OffsiteBackupError(RuntimeError):
    pass


def validate_interval(seconds: int) -> int:
    if seconds < 0 or 0 < seconds < 60:
        raise OffsiteBackupError("Backup interval must be 0 or at least 60 seconds")
    return seconds


def sha256_digest(path: Path) -> tuple[str, str]:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    raw = digest.digest()
    return digest.hexdigest(), base64.b64encode(raw).decode()


def destination_url(template: str, filename: str) -> str:
    if "{filename}" not in template:
        raise OffsiteBackupError("Off-site backup URL must contain the {filename} placeholder")
    return template.replace("{filename}", quote(filename, safe=""))


def upload_backup(
    backup: str | Path,
    url_template: str,
    *,
    bearer_token: str | None = None,
    allow_insecure_http: bool = False,
    uploader=None,
) -> dict[str, object]:
    source = Path(backup)
    if not source.is_file():
        raise FileNotFoundError(f"Backup does not exist: {source}")
    url = destination_url(url_template, source.name)
    if not url.startswith("https://") and not allow_insecure_http:
        raise OffsiteBackupError("Off-site backup URL must use HTTPS")
    hexadecimal_digest, encoded_digest = sha256_digest(source)
    headers = {
        "Content-Type": "application/vnd.sqlite3",
        "Content-Length": str(source.stat().st_size),
        "Digest": f"sha-256={encoded_digest}",
        "X-AutoFB-SHA256": hexadecimal_digest,
    }
    if bearer_token:
        headers["Authorization"] = f"Bearer {bearer_token}"
    request_errors: tuple[type[BaseException], ...] = (OSError,)
    if uploader is None:
        try:
            import requests
        except ImportError as exc:
            raise OffsiteBackupError("The requests package is required for off-site backup uploads") from exc
        put = requests.put
        request_errors = (OSError, requests.RequestException)
    else:
        put = uploader
    try:
        with source.open("rb") as handle:
            response = put(url, data=handle, headers=headers, timeout=120)
    except request_errors as exc:
        raise OffsiteBackupError(f"Off-site upload failed: {exc}") from exc
    status = response.status_code
    if not 200 <= status < 300:
        raise OffsiteBackupError(f"Off-site upload returned HTTP {status}")
    return {"filename": source.name, "size_bytes": source.stat().st_size, "sha256": hexadecimal_digest}


def send_backup_failure_alert(
    webhook_url: str,
    error_type: str,
    *,
    bearer_token: str | None = None,
    allow_insecure_http: bool = False,
    sender=None,
) -> None:
    """Send a minimal failure event without backup paths, destinations or exception messages."""
    if not webhook_url.startswith("https://") and not allow_insecure_http:
        raise OffsiteBackupError("Backup alert URL must use HTTPS")
    payload = {
        "service": "autofb-backup",
        "event": "offsite_backup_failed",
        "status": "failed",
        "error_type": error_type,
        "occurred_at": datetime.now(UTC).isoformat(),
    }
    headers = {"Content-Type": "application/json"}
    if bearer_token:
        headers["Authorization"] = f"Bearer {bearer_token}"
    request_errors: tuple[type[BaseException], ...] = (OSError,)
    if sender is None:
        try:
            import requests
        except ImportError as exc:
            raise OffsiteBackupError("The requests package is required for backup alerts") from exc
        post = requests.post
        request_errors = (OSError, requests.RequestException)
    else:
        post = sender
    try:
        response = post(webhook_url, json=payload, headers=headers, timeout=15)
    except request_errors as exc:
        raise OffsiteBackupError("Backup failure alert delivery failed") from exc
    if not 200 <= response.status_code < 300:
        raise OffsiteBackupError(f"Backup failure alert returned HTTP {response.status_code}")


def prepare_backup(database: str | Path, output: str | Path, *, keep: int) -> tuple[Path, dict[str, object]]:
    """Create a backup and prove it can be restored before any remote upload."""
    backup = backup_database(database, output, keep=keep)
    return backup, restore_drill(backup)


def record_backup_run(
    database: str | Path,
    status: str,
    *,
    filename: str | None = None,
    sha256: str | None = None,
    error_type: str | None = None,
) -> None:
    """Persist secret-free backup status for preflight and operator monitoring."""
    if status not in {"succeeded", "failed"}:
        raise ValueError("backup status must be succeeded or failed")
    with closing(sqlite3.connect(database)) as connection:
        connection.execute(
            "INSERT INTO backup_runs(id, status, filename, sha256, error_type, created_at) VALUES (?, ?, ?, ?, ?, ?)",
            (str(uuid.uuid4()), status, filename, sha256, error_type, datetime.now(UTC).isoformat()),
        )
        connection.commit()


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(description="Create and upload a verified AutoFB database backup.")
    result.add_argument("--database", default=os.environ.get("AUTOFB_DATABASE_PATH", "autofb.db"))
    result.add_argument("--output", default=os.environ.get("AUTOFB_BACKUP_DIRECTORY", "backups"))
    result.add_argument("--keep", type=int, default=int(os.environ.get("AUTOFB_BACKUP_KEEP", "7")))
    result.add_argument("--url", default=os.environ.get("AUTOFB_OFFSITE_BACKUP_URL", ""))
    result.add_argument("--token", default=os.environ.get("AUTOFB_OFFSITE_BACKUP_TOKEN", ""))
    result.add_argument("--alert-url", default=os.environ.get("AUTOFB_BACKUP_ALERT_URL", ""))
    result.add_argument("--alert-token", default=os.environ.get("AUTOFB_BACKUP_ALERT_TOKEN", ""))
    result.add_argument("--allow-insecure-http", action="store_true")
    result.add_argument(
        "--interval-seconds",
        type=int,
        default=int(os.environ.get("AUTOFB_BACKUP_INTERVAL_SECONDS", "0")),
        help="Repeat forever at this interval; 0 creates one backup",
    )
    return result


def main() -> int:
    args = parser().parse_args()
    if not args.url:
        raise SystemExit("AUTOFB_OFFSITE_BACKUP_URL or --url is required")
    interval = validate_interval(args.interval_seconds)
    while True:
        backup = None
        try:
            backup, drill = prepare_backup(args.database, args.output, keep=args.keep)
            uploaded = upload_backup(
                backup,
                args.url,
                bearer_token=args.token or None,
                allow_insecure_http=args.allow_insecure_http,
            )
        except Exception as exc:
            error_type = type(exc).__name__
            record_backup_run(
                args.database,
                "failed",
                filename=backup.name if backup else None,
                error_type=error_type,
            )
            if args.alert_url:
                try:
                    send_backup_failure_alert(
                        args.alert_url,
                        error_type,
                        bearer_token=args.alert_token or None,
                        allow_insecure_http=args.allow_insecure_http,
                    )
                except Exception:
                    print("Backup failure alert could not be delivered", file=sys.stderr, flush=True)
            raise
        record_backup_run(
            args.database, "succeeded", filename=uploaded["filename"], sha256=uploaded["sha256"]
        )
        print(
            f"Off-site backup uploaded: {uploaded['filename']} "
            f"({uploaded['size_bytes']} bytes, sha256={uploaded['sha256']}, "
            f"schema_version={drill['schema_version']})",
            flush=True,
        )
        if interval == 0:
            return 0
        time.sleep(interval)


if __name__ == "__main__":
    raise SystemExit(main())
