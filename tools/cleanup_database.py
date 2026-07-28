"""Remove expired operational records from the AutoFB SQLite database."""
from __future__ import annotations

import argparse
import json
import os
import sqlite3
from datetime import UTC, datetime, timedelta
from pathlib import Path


def cleanup_database(
    database_path: str | Path,
    *,
    current_time: datetime | None = None,
    dry_run: bool = False,
) -> dict[str, int]:
    path = Path(database_path)
    if not path.is_file():
        raise FileNotFoundError(f"Database does not exist: {path}")
    timestamp = current_time or datetime.now(UTC)
    if timestamp.tzinfo is None:
        raise ValueError("current_time must be timezone-aware")
    cutoffs = {
        "sessions": timestamp.isoformat(),
        "oauth_states": timestamp.isoformat(),
        "auth_login_attempts": (timestamp - timedelta(days=1)).isoformat(),
        "worker_heartbeats": (timestamp - timedelta(days=7)).isoformat(),
        "token_health_checks": (timestamp - timedelta(days=90)).isoformat(),
    }
    predicates = {
        "sessions": "expires_at <= ?",
        "oauth_states": "expires_at <= ?",
        "auth_login_attempts": "updated_at <= ?",
        "worker_heartbeats": "last_seen_at <= ?",
        "token_health_checks": "checked_at <= ?",
    }
    connection = sqlite3.connect(path)
    try:
        connection.execute("PRAGMA foreign_keys = ON")
        removed: dict[str, int] = {}
        for table, predicate in predicates.items():
            count = connection.execute(
                f'SELECT COUNT(*) FROM "{table}" WHERE {predicate}', (cutoffs[table],)
            ).fetchone()[0]
            removed[table] = count
            if not dry_run:
                connection.execute(f'DELETE FROM "{table}" WHERE {predicate}', (cutoffs[table],))
        if dry_run:
            connection.rollback()
        else:
            connection.commit()
        return removed
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(description="Delete expired AutoFB operational records.")
    result.add_argument("--database", default=os.environ.get("AUTOFB_DATABASE_PATH", "autofb.db"))
    result.add_argument("--dry-run", action="store_true")
    return result


def main() -> int:
    args = parser().parse_args()
    removed = cleanup_database(args.database, dry_run=args.dry_run)
    print(json.dumps({"dry_run": args.dry_run, "records": removed, "total": sum(removed.values())}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
