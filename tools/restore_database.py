"""Validate and atomically restore an AutoFB SQLite backup."""
from __future__ import annotations

import argparse
import os
import sqlite3
import tempfile
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path


def _verified_copy(source: Path, destination: Path) -> None:
    with closing(sqlite3.connect(source)) as source_connection:
        integrity = source_connection.execute("PRAGMA integrity_check").fetchone()
        if not integrity or integrity[0] != "ok":
            raise RuntimeError(f"SQLite integrity check failed: {integrity}")
        with closing(sqlite3.connect(destination)) as destination_connection:
            source_connection.backup(destination_connection)
            restored_integrity = destination_connection.execute("PRAGMA integrity_check").fetchone()
            if not restored_integrity or restored_integrity[0] != "ok":
                raise RuntimeError(f"Restored database integrity check failed: {restored_integrity}")


def restore_database(
    backup_path: str | Path,
    database_path: str | Path,
    *,
    force: bool = False,
    now: datetime | None = None,
) -> tuple[Path, Path | None]:
    """Restore ``backup_path`` atomically and optionally preserve the old database."""
    source = Path(backup_path)
    target = Path(database_path)
    if not source.is_file():
        raise FileNotFoundError(f"Backup does not exist: {source}")
    if source.resolve() == target.resolve():
        raise ValueError("Backup and database paths must be different")
    if target.exists() and not force:
        raise FileExistsError(f"Database already exists: {target}; use --force to replace it")

    target.parent.mkdir(parents=True, exist_ok=True)
    preserved: Path | None = None
    timestamp = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    if target.exists():
        preserved = target.with_name(f"{target.stem}.pre-restore-{timestamp:%Y%m%dT%H%M%SZ}{target.suffix}")
        if preserved.exists():
            raise FileExistsError(f"Safety backup already exists: {preserved}")
        _verified_copy(target, preserved)

    temporary_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(prefix=f".{target.name}.", suffix=".restore", dir=target.parent, delete=False) as temporary:
            temporary_path = Path(temporary.name)
        _verified_copy(source, temporary_path)
        os.replace(temporary_path, target)
    except Exception:
        if temporary_path is not None:
            temporary_path.unlink(missing_ok=True)
        raise
    return target, preserved


def parser() -> argparse.ArgumentParser:
    argument_parser = argparse.ArgumentParser(
        description="Restore a verified AutoFB SQLite backup. Stop API and worker containers before running."
    )
    argument_parser.add_argument("backup", help="Path to the SQLite backup file.")
    argument_parser.add_argument("--database", default=os.environ.get("AUTOFB_DATABASE_PATH", "autofb.db"))
    argument_parser.add_argument("--force", action="store_true", help="Replace an existing database after preserving a safety copy.")
    return argument_parser


def main() -> int:
    args = parser().parse_args()
    restored, preserved = restore_database(args.backup, args.database, force=args.force)
    print(f"Database restored: {restored}")
    if preserved is not None:
        print(f"Previous database preserved: {preserved}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
