import sqlite3
import tempfile
import unittest
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path

from tools.restore_database import restore_database


def create_database(path: Path, value: str) -> None:
    with closing(sqlite3.connect(path)) as connection:
        connection.execute("CREATE TABLE content (value TEXT NOT NULL)")
        connection.execute("INSERT INTO content VALUES (?)", (value,))
        connection.commit()


def read_value(path: Path) -> str:
    with closing(sqlite3.connect(path)) as connection:
        return connection.execute("SELECT value FROM content").fetchone()[0]


class RestoreDatabaseToolTests(unittest.TestCase):
    def test_restores_backup_to_new_database(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            backup = root / "backup.db"
            target = root / "data" / "autofb.db"
            create_database(backup, "backup")

            restored, preserved = restore_database(backup, target)

            self.assertEqual(restored, target)
            self.assertIsNone(preserved)
            self.assertEqual(read_value(target), "backup")

    def test_force_restore_preserves_previous_database(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            backup = root / "backup.db"
            target = root / "autofb.db"
            create_database(backup, "backup")
            create_database(target, "current")

            _, preserved = restore_database(
                backup,
                target,
                force=True,
                now=datetime(2026, 7, 25, 12, 0, tzinfo=timezone.utc),
            )

            self.assertEqual(read_value(target), "backup")
            self.assertIsNotNone(preserved)
            self.assertEqual(read_value(preserved), "current")

    def test_refuses_to_overwrite_without_force(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            backup = root / "backup.db"
            target = root / "autofb.db"
            create_database(backup, "backup")
            create_database(target, "current")

            with self.assertRaises(FileExistsError):
                restore_database(backup, target)
            self.assertEqual(read_value(target), "current")

    def test_rejects_invalid_backup_without_creating_target(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            backup = root / "invalid.db"
            target = root / "autofb.db"
            backup.write_text("not sqlite", encoding="utf-8")

            with self.assertRaises(sqlite3.DatabaseError):
                restore_database(backup, target)
            self.assertFalse(target.exists())


if __name__ == "__main__":
    unittest.main()
