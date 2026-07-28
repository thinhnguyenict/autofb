import tempfile
import unittest
from pathlib import Path

from autofb.web.database import Database
from tools.offsite_backup import (
    OffsiteBackupError,
    destination_url,
    prepare_backup,
    record_backup_run,
    send_backup_failure_alert,
    upload_backup,
    validate_interval,
)


class Response:
    status_code = 201


class OffsiteBackupTests(unittest.TestCase):
    def test_upload_uses_https_put_digest_and_bearer_token(self):
        with tempfile.TemporaryDirectory() as directory:
            backup = Path(directory) / "autofb test.db"
            backup.write_bytes(b"sqlite-backup")
            captured = {}

            def uploader(url, *, data, headers, timeout):
                captured.update(url=url, body=data.read(), headers=headers, timeout=timeout)
                return Response()

            result = upload_backup(
                backup,
                "https://backup.example/objects/{filename}",
                bearer_token="secret-token",
                uploader=uploader,
            )

            self.assertEqual(captured["url"], "https://backup.example/objects/autofb%20test.db")
            self.assertEqual(captured["body"], b"sqlite-backup")
            self.assertEqual(captured["headers"]["Authorization"], "Bearer secret-token")
            self.assertTrue(captured["headers"]["Digest"].startswith("sha-256="))
            self.assertEqual(captured["timeout"], 120)
            self.assertEqual(result["size_bytes"], len(b"sqlite-backup"))
            self.assertEqual(len(result["sha256"]), 64)

    def test_rejects_http_and_missing_filename_placeholder(self):
        with tempfile.TemporaryDirectory() as directory:
            backup = Path(directory) / "backup.db"
            backup.write_bytes(b"backup")
            with self.assertRaisesRegex(OffsiteBackupError, "HTTPS"):
                upload_backup(backup, "http://backup.example/{filename}")
            with self.assertRaisesRegex(OffsiteBackupError, "placeholder"):
                destination_url("https://backup.example/static.db", backup.name)

    def test_rejects_missing_backup(self):
        with self.assertRaises(FileNotFoundError):
            upload_backup("missing.db", "https://backup.example/{filename}")

    def test_backup_interval_is_zero_or_at_least_one_minute(self):
        self.assertEqual(validate_interval(0), 0)
        self.assertEqual(validate_interval(3600), 3600)
        with self.assertRaisesRegex(OffsiteBackupError, "at least 60"):
            validate_interval(30)
        with self.assertRaisesRegex(OffsiteBackupError, "at least 60"):
            validate_interval(-1)

    def test_prepare_backup_runs_restore_drill_before_upload(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            database = Database(root / "autofb.db")
            database.initialize()

            backup, report = prepare_backup(database.path, root / "backups", keep=2)

            self.assertTrue(backup.is_file())
            self.assertEqual(report["status"], "passed")
            self.assertEqual(report["integrity"], "ok")
            self.assertEqual(report["schema_version"], 1)

    def test_backup_run_status_contains_no_secret_error_message(self):
        with tempfile.TemporaryDirectory() as directory:
            database = Database(Path(directory) / "autofb.db")
            database.initialize()
            record_backup_run(database.path, "failed", filename="backup.db", error_type="OffsiteBackupError")
            with database.connect() as connection:
                row = connection.execute("SELECT status, filename, error_type FROM backup_runs").fetchone()
            self.assertEqual(dict(row), {"status": "failed", "filename": "backup.db", "error_type": "OffsiteBackupError"})

    def test_failure_alert_contains_only_secret_free_operational_fields(self):
        captured = {}

        def sender(url, *, json, headers, timeout):
            captured.update(url=url, payload=json, headers=headers, timeout=timeout)
            return Response()

        send_backup_failure_alert(
            "https://alerts.example/hooks/backup",
            "OffsiteBackupError",
            bearer_token="alert-secret",
            sender=sender,
        )

        self.assertEqual(captured["url"], "https://alerts.example/hooks/backup")
        self.assertEqual(captured["headers"]["Authorization"], "Bearer alert-secret")
        self.assertEqual(captured["timeout"], 15)
        self.assertEqual(
            set(captured["payload"]),
            {"service", "event", "status", "error_type", "occurred_at"},
        )
        self.assertEqual(captured["payload"]["error_type"], "OffsiteBackupError")
        self.assertNotIn("alert-secret", str(captured["payload"]))

    def test_failure_alert_requires_https_and_success_response(self):
        with self.assertRaisesRegex(OffsiteBackupError, "HTTPS"):
            send_backup_failure_alert("http://alerts.example/hook", "RuntimeError", sender=lambda *args, **kwargs: Response())

        class FailedResponse:
            status_code = 503

        with self.assertRaisesRegex(OffsiteBackupError, "HTTP 503"):
            send_backup_failure_alert(
                "https://alerts.example/hook",
                "RuntimeError",
                sender=lambda *args, **kwargs: FailedResponse(),
            )


if __name__ == "__main__":
    unittest.main()
