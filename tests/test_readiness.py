import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from autofb.web.database import Database
from autofb.web.readiness import backup_readiness_report, readiness_report, worker_readiness_report


class ReadinessTests(unittest.TestCase):
    def test_reports_ready_for_available_database_and_media_storage(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            database_path = root / "autofb.db"
            sqlite3.connect(database_path).close()

            report = readiness_report(database_path, root / "media")

            self.assertEqual(report, {"status": "ready", "checks": {"database": "ok", "media_storage": "ok"}})

    def test_reports_database_failure_without_leaking_path(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            database_path = root / "missing" / "secret-name.db"

            report = readiness_report(database_path, root / "media")

            self.assertEqual(report["status"], "not_ready")
            self.assertEqual(report["checks"]["database"], "error")
            self.assertNotIn(str(database_path), str(report))

    def test_probe_does_not_create_a_missing_database(self):
        with tempfile.TemporaryDirectory() as directory:
            database_path = Path(directory) / "missing.db"
            report = readiness_report(database_path, Path(directory) / "media")
            self.assertEqual(report["checks"]["database"], "error")
            self.assertFalse(database_path.exists())

    def test_reports_unwritable_media_storage(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            database_path = root / "autofb.db"
            sqlite3.connect(database_path).close()
            with patch("autofb.web.readiness.tempfile.NamedTemporaryFile", side_effect=PermissionError):
                report = readiness_report(database_path, root / "media")

            self.assertEqual(report["status"], "not_ready")
            self.assertEqual(report["checks"]["media_storage"], "error")

    def test_reports_s3_storage_readiness_without_touching_local_media(self):
        class S3Client:
            def __init__(self):
                self.bucket = None

            def head_bucket(self, *, Bucket):
                self.bucket = Bucket

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            database_path = root / "autofb.db"
            sqlite3.connect(database_path).close()
            client = S3Client()
            report = readiness_report(
                database_path,
                root / "must-not-exist",
                media_backend="s3",
                s3_bucket="media-bucket",
                s3_client=client,
            )
            self.assertEqual(report["checks"]["media_storage"], "ok")
            self.assertEqual(client.bucket, "media-bucket")
            self.assertFalse((root / "must-not-exist").exists())

    def test_worker_probe_reports_missing_and_recent_heartbeat(self):
        with tempfile.TemporaryDirectory() as directory:
            database_path = Path(directory) / "autofb.db"
            database = Database(database_path)
            database.initialize()
            self.assertEqual(worker_readiness_report(database_path)["checks"]["worker"], "missing")
            with database.connect() as connection:
                connection.execute(
                    "INSERT INTO worker_heartbeats VALUES (?, 'idle', NULL, ?, ?)",
                    ("worker-1", "2099-01-01T00:00:00+00:00", "2026-01-01T00:00:00+00:00"),
                )
            self.assertEqual(worker_readiness_report(database_path), {"status": "ready", "checks": {"worker": "ok"}})

    def test_worker_probe_reports_stale_or_error_heartbeat(self):
        with tempfile.TemporaryDirectory() as directory:
            database_path = Path(directory) / "autofb.db"
            database = Database(database_path)
            database.initialize()
            with database.connect() as connection:
                connection.execute(
                    "INSERT INTO worker_heartbeats VALUES (?, 'error', ?, ?, ?)",
                    ("worker-1", "failure", "2099-01-01T00:00:00+00:00", "2026-01-01T00:00:00+00:00"),
                )
            self.assertEqual(worker_readiness_report(database_path)["checks"]["worker"], "stale")

    def test_backup_probe_requires_latest_run_to_be_recent_and_successful(self):
        with tempfile.TemporaryDirectory() as directory:
            database = Database(Path(directory) / "autofb.db")
            database.initialize()
            self.assertEqual(backup_readiness_report(database.path)["checks"]["backup"], "missing")
            with database.connect() as connection:
                connection.execute(
                    "INSERT INTO backup_runs VALUES (?, 'succeeded', ?, ?, NULL, ?)",
                    ("success", "backup.db", "digest", "2099-01-01T00:00:00+00:00"),
                )
            self.assertEqual(
                backup_readiness_report(database.path),
                {"status": "ready", "checks": {"backup": "ok"}},
            )
            with database.connect() as connection:
                connection.execute(
                    "INSERT INTO backup_runs VALUES (?, 'failed', NULL, NULL, ?, ?)",
                    ("failure", "OffsiteBackupError", "2099-01-02T00:00:00+00:00"),
                )
            self.assertEqual(backup_readiness_report(database.path)["checks"]["backup"], "failed")

    def test_backup_probe_rejects_stale_or_invalid_timestamps(self):
        with tempfile.TemporaryDirectory() as directory:
            database = Database(Path(directory) / "autofb.db")
            database.initialize()
            with database.connect() as connection:
                connection.execute(
                    "INSERT INTO backup_runs VALUES (?, 'succeeded', NULL, NULL, NULL, ?)",
                    ("stale", "2000-01-01T00:00:00+00:00"),
                )
            self.assertEqual(backup_readiness_report(database.path)["checks"]["backup"], "stale")
            with database.connect() as connection:
                connection.execute("UPDATE backup_runs SET created_at = 'not-a-date'")
            self.assertEqual(backup_readiness_report(database.path)["checks"]["backup"], "invalid")

    def test_backup_probe_does_not_create_a_missing_database(self):
        with tempfile.TemporaryDirectory() as directory:
            database_path = Path(directory) / "missing.db"
            self.assertEqual(backup_readiness_report(database_path)["checks"]["backup"], "unavailable")
            self.assertFalse(database_path.exists())


if __name__ == "__main__":
    unittest.main()
