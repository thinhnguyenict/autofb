"""Atomically re-encrypt stored Meta tokens with a replacement Fernet key."""
from __future__ import annotations

import json
import os
import sqlite3
from pathlib import Path
from typing import Callable


def rotate_token_key(
    database_path: str | Path,
    decryptor: Callable[[str], str],
    encryptor: Callable[[str], str],
) -> dict[str, int]:
    path = Path(database_path)
    if not path.is_file():
        raise FileNotFoundError(f"Database does not exist: {path}")
    connection = sqlite3.connect(path)
    connection.row_factory = sqlite3.Row
    try:
        connection.execute("BEGIN IMMEDIATE")
        connections = connection.execute(
            "SELECT id, encrypted_access_token FROM oauth_connections"
        ).fetchall()
        pages = connection.execute(
            "SELECT id, encrypted_access_token FROM facebook_pages"
        ).fetchall()
        # Transform every value before the first write. A bad old key therefore
        # cannot leave the database with a mixture of old and new ciphertext.
        connection_updates = [
            (encryptor(decryptor(row["encrypted_access_token"])), row["id"]) for row in connections
        ]
        page_updates = [
            (encryptor(decryptor(row["encrypted_access_token"])), row["id"]) for row in pages
        ]
        connection.executemany(
            "UPDATE oauth_connections SET encrypted_access_token = ? WHERE id = ?", connection_updates
        )
        connection.executemany(
            "UPDATE facebook_pages SET encrypted_access_token = ? WHERE id = ?", page_updates
        )
        connection.commit()
        return {"oauth_connections": len(connection_updates), "facebook_pages": len(page_updates)}
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()


def main() -> int:
    database_path = os.environ.get("AUTOFB_DATABASE_PATH", "autofb.db")
    old_key = os.environ.get("AUTOFB_OLD_TOKEN_ENCRYPTION_KEY", "")
    new_key = os.environ.get("AUTOFB_NEW_TOKEN_ENCRYPTION_KEY", "")
    if not old_key or not new_key:
        raise SystemExit("AUTOFB_OLD_TOKEN_ENCRYPTION_KEY and AUTOFB_NEW_TOKEN_ENCRYPTION_KEY are required")
    if old_key == new_key:
        raise SystemExit("Old and new token encryption keys must differ")
    from cryptography.fernet import Fernet

    old_cipher = Fernet(old_key.encode())
    new_cipher = Fernet(new_key.encode())
    report = rotate_token_key(
        database_path,
        lambda value: old_cipher.decrypt(value.encode()).decode(),
        lambda value: new_cipher.encrypt(value.encode()).decode(),
    )
    print(json.dumps({"status": "rotated", "records": report, "total": sum(report.values())}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
