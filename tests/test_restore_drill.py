import sqlite3
import tempfile
import unittest
from pathlib import Path

from autofb.web.database import Database
from tools.restore_drill import restore_drill


class RestoreDrillTests(unittest.TestCase):
    def test_restore_drill_validates_schema_and_counts_rows(self):
        with tempfile.TemporaryDirectory() as directory:
            backup = Path(directory) / "backup.db"
            database = Database(backup)
            database.initialize()
            with database.connect() as connection:
                connection.execute(
                    "INSERT INTO users VALUES (?, ?, ?, ?, ?)",
                    ("user-1", "owner@example.com", "hash", "Owner", "2026-07-26T00:00:00+00:00"),
                )

            report = restore_drill(backup)

            self.assertEqual(report["status"], "passed")
            self.assertEqual(report["integrity"], "ok")
            self.assertEqual(report["schema_version"], 1)
            self.assertEqual(report["row_counts"]["users"], 1)

    def test_restore_drill_rejects_unrelated_valid_sqlite_file(self):
        with tempfile.TemporaryDirectory() as directory:
            backup = Path(directory) / "wrong.db"
            with sqlite3.connect(backup) as connection:
                connection.execute("CREATE TABLE unrelated(value TEXT)")
            with self.assertRaisesRegex(RuntimeError, "missing required tables"):
                restore_drill(backup)

    def test_restore_drill_rejects_missing_file(self):
        with self.assertRaises(FileNotFoundError):
            restore_drill("missing-backup.db")


if __name__ == "__main__":
    unittest.main()
