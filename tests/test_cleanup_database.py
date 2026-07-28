import tempfile
import unittest
from datetime import UTC, datetime
from pathlib import Path

from autofb.web.database import Database
from tools.cleanup_database import cleanup_database


class CleanupDatabaseTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.database = Database(Path(self.directory.name) / "autofb.db")
        self.database.initialize()
        with self.database.connect() as connection:
            connection.execute(
                "INSERT INTO users VALUES ('user-1', 'owner@example.com', 'hash', 'Owner', '2026-01-01T00:00:00+00:00')"
            )
            connection.execute(
                "INSERT INTO sessions VALUES ('expired', 'user-1', '2026-01-01T00:00:00+00:00', '2026-01-01T00:00:00+00:00')"
            )
            connection.execute(
                "INSERT INTO sessions VALUES ('active', 'user-1', '2027-01-01T00:00:00+00:00', '2026-01-01T00:00:00+00:00')"
            )

    def test_cleanup_removes_expired_but_keeps_active_records(self):
        removed = cleanup_database(
            self.database.path, current_time=datetime(2026, 7, 26, tzinfo=UTC)
        )
        self.assertEqual(removed["sessions"], 1)
        with self.database.connect() as connection:
            tokens = [row[0] for row in connection.execute("SELECT token_hash FROM sessions")]
        self.assertEqual(tokens, ["active"])

    def test_dry_run_reports_without_deleting(self):
        removed = cleanup_database(
            self.database.path, current_time=datetime(2026, 7, 26, tzinfo=UTC), dry_run=True
        )
        self.assertEqual(removed["sessions"], 1)
        with self.database.connect() as connection:
            self.assertEqual(connection.execute("SELECT COUNT(*) FROM sessions").fetchone()[0], 2)

    def test_rejects_naive_time_and_missing_database(self):
        with self.assertRaisesRegex(ValueError, "timezone-aware"):
            cleanup_database(self.database.path, current_time=datetime(2026, 7, 26))
        with self.assertRaises(FileNotFoundError):
            cleanup_database(Path(self.directory.name) / "missing.db")


if __name__ == "__main__":
    unittest.main()
