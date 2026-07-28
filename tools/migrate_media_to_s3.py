#!/usr/bin/env python3
"""Migrate local media records to the configured S3-compatible backend."""
from __future__ import annotations

import argparse
import os
from pathlib import Path

from autofb.web.database import Database
from autofb.web.storage import LocalMediaStorage, S3MediaStorage


class MediaMigrationError(RuntimeError):
    pass


def migrate_media(
    database: Database,
    local_storage: LocalMediaStorage,
    object_storage: S3MediaStorage,
    *,
    dry_run: bool = False,
    delete_local: bool = False,
) -> dict[str, int]:
    """Copy local objects and conditionally replace each database storage path."""
    with database.connect() as connection:
        rows = connection.execute(
            """SELECT id, workspace_id, filename, storage_path, content_type
               FROM media_assets
               WHERE storage_path NOT LIKE 's3://%'
               ORDER BY created_at, id"""
        ).fetchall()

    report = {"examined": len(rows), "migrated": 0, "skipped": 0, "local_deleted": 0}
    for row in rows:
        old_path = row["storage_path"]
        if dry_run:
            with local_storage.open(old_path):
                pass
            report["skipped"] += 1
            continue

        with local_storage.open(old_path) as source:
            new_path, _, _ = object_storage.save(
                row["workspace_id"], row["filename"], source, row["content_type"]
            )
        try:
            with database.connect() as connection:
                updated = connection.execute(
                    "UPDATE media_assets SET storage_path = ? WHERE id = ? AND storage_path = ?",
                    (new_path, row["id"], old_path),
                ).rowcount
                if updated != 1:
                    raise MediaMigrationError("Media record changed during object migration")
        except Exception:
            object_storage.delete(new_path)
            raise
        report["migrated"] += 1
        if delete_local:
            local_storage.delete(old_path)
            report["local_deleted"] += 1
    return report


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(description="Migrate AutoFB local media to S3/MinIO.")
    result.add_argument("--database", default=os.environ.get("AUTOFB_DATABASE_PATH", "autofb.db"))
    result.add_argument("--media-dir", default=os.environ.get("AUTOFB_MEDIA_DIR", "media"))
    result.add_argument("--dry-run", action="store_true")
    result.add_argument("--delete-local", action="store_true")
    return result


def main() -> int:
    args = parser().parse_args()
    database_path = Path(args.database)
    if not database_path.is_file():
        raise SystemExit(f"Database does not exist: {database_path}")
    report = migrate_media(
        Database(database_path),
        LocalMediaStorage(args.media_dir),
        S3MediaStorage.from_environment(),
        dry_run=args.dry_run,
        delete_local=args.delete_local,
    )
    print(
        "Media migration complete: "
        f"examined={report['examined']} migrated={report['migrated']} "
        f"validated={report['skipped']} local_deleted={report['local_deleted']}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
