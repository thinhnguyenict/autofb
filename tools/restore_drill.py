"""Perform a non-destructive restore drill against an AutoFB SQLite backup."""
from __future__ import annotations

import argparse
import json
import sqlite3
import tempfile
from contextlib import closing
from pathlib import Path

from tools.restore_database import restore_database


REQUIRED_TABLES = frozenset(
    {
        "users",
        "schema_migrations",
        "workspaces",
        "workspace_members",
        "sessions",
        "oauth_connections",
        "facebook_pages",
        "media_assets",
        "posts",
        "publish_jobs",
        "publish_results",
        "backup_runs",
    }
)
COUNTED_TABLES = ("users", "workspaces", "facebook_pages", "media_assets", "posts", "publish_jobs")


def restore_drill(backup_path: str | Path) -> dict[str, object]:
    """Restore into a temporary directory and verify the expected application schema."""
    source = Path(backup_path)
    if not source.is_file():
        raise FileNotFoundError(f"Backup does not exist: {source}")
    with tempfile.TemporaryDirectory(prefix="autofb-restore-drill-") as directory:
        restored = Path(directory) / "restored.db"
        restore_database(source, restored)
        with closing(sqlite3.connect(f"file:{restored}?mode=ro", uri=True)) as connection:
            integrity = connection.execute("PRAGMA integrity_check").fetchone()[0]
            table_names = {
                row[0]
                for row in connection.execute(
                    "SELECT name FROM sqlite_master WHERE type = 'table' AND name NOT LIKE 'sqlite_%'"
                )
            }
            missing = sorted(REQUIRED_TABLES - table_names)
            if missing:
                raise RuntimeError(f"Restore drill is missing required tables: {', '.join(missing)}")
            counts = {table: connection.execute(f'SELECT COUNT(*) FROM "{table}"').fetchone()[0] for table in COUNTED_TABLES}
            migration = connection.execute("SELECT MAX(version) FROM schema_migrations").fetchone()[0]
    return {
        "status": "passed",
        "integrity": integrity,
        "schema_version": migration,
        "table_count": len(table_names),
        "row_counts": counts,
    }


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(description="Restore an AutoFB backup temporarily and verify its schema.")
    result.add_argument("backup", help="Path to a local SQLite backup")
    return result


def main() -> int:
    report = restore_drill(parser().parse_args().backup)
    print(json.dumps(report, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
