import sqlite3
import tempfile
import unittest
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path

from tools.backup_database import backup_database


class BackupDatabaseToolTests(unittest.TestCase):
    def test_backup_is_consistent_and_applies_retention(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            database_path = root / "autofb.db"
            backup_directory = root / "backups"
            with closing(sqlite3.connect(database_path)) as connection:
                connection.execute("CREATE TABLE example (value TEXT NOT NULL)")
                connection.execute("INSERT INTO example VALUES ('first')")
                connection.commit()

            first = backup_database(
                database_path,
                backup_directory,
                keep=1,
                now=datetime(2026, 7, 25, 10, 0, tzinfo=timezone.utc),
            )
            with closing(sqlite3.connect(database_path)) as connection:
                connection.execute("INSERT INTO example VALUES ('second')")
                connection.commit()
            second = backup_database(
                database_path,
                backup_directory,
                keep=1,
                now=datetime(2026, 7, 25, 10, 1, tzinfo=timezone.utc),
            )

            self.assertFalse(first.exists())
            self.assertTrue(second.exists())
            with closing(sqlite3.connect(second)) as connection:
                values = [row[0] for row in connection.execute("SELECT value FROM example ORDER BY rowid")]
            self.assertEqual(values, ["first", "second"])

    def test_missing_database_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaises(FileNotFoundError):
                backup_database(Path(directory) / "missing.db", Path(directory) / "backups")

    def test_invalid_retention_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            database_path = Path(directory) / "autofb.db"
            sqlite3.connect(database_path).close()
            with self.assertRaises(ValueError):
                backup_database(database_path, Path(directory) / "backups", keep=0)


if __name__ == "__main__":
    unittest.main()
