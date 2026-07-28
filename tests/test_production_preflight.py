import tempfile
import unittest
from pathlib import Path

from autofb.web.database import Database
from tools.production_preflight import production_preflight


class ProductionPreflightTests(unittest.TestCase):
    def test_ready_report_does_not_expose_secret_values(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            database = Database(root / "autofb.db")
            database.initialize()
            with database.connect() as connection:
                connection.execute("INSERT INTO users VALUES ('u1', 'admin@example.com', 'hash', 'Admin', 'now')")
                connection.execute("INSERT INTO workspaces VALUES ('workspace-1', 'Pilot', 'u1', 'now')")
                connection.execute(
                    "INSERT INTO worker_heartbeats VALUES ('worker', 'idle', NULL, '2099-01-01T00:00:00+00:00', 'now')"
                )
                connection.execute(
                    "INSERT INTO backup_runs VALUES ('backup', 'succeeded', 'backup.db', 'abc', NULL, '2099-01-01T00:00:00+00:00')"
                )
                connection.execute(
                    "INSERT INTO oauth_connections VALUES ('connection-1', 'workspace-1', 'provider-1', 'Meta user', 'encrypted', '2099-01-01T00:00:00+00:00', 'now')"
                )
                connection.execute(
                    "INSERT INTO facebook_pages VALUES ('page-1', 'workspace-1', 'connection-1', 'facebook-page-1', 'Page', 'encrypted', 'now')"
                )
                connection.execute(
                    "INSERT INTO token_health_checks VALUES ('health-1', 'connection-1', 'valid', NULL, '2099-01-01T00:00:00+00:00')"
                )
            environment = {
                "META_APP_ID": "app-secret-id",
                "META_APP_SECRET": "never-print-this",
                "META_REDIRECT_URI": "https://tool.example/oauth/callback",
                "AUTOFB_TOKEN_ENCRYPTION_KEY": "valid-test-key",
                "AUTOFB_BACKUP_ALERT_URL": "https://alerts.example/backup",
                "AUTOFB_ERROR_WEBHOOK_URL": "https://errors.example/events",
                "AUTOFB_PUBLIC_URL": "https://tool.example",
                "AUTOFB_ENABLE_HSTS": "1",
                "AUTOFB_DATABASE_PATH": database.path,
                "AUTOFB_MEDIA_DIR": str(root / "media"),
            }
            report = production_preflight(environment, encryption_key_validator=lambda value: value == "valid-test-key")
            self.assertEqual(report["status"], "ready")
            self.assertEqual(report["checks"]["database_integrity"], "ok")
            self.assertEqual(report["checks"]["foreign_keys"], "ok")
            self.assertEqual(report["checks"]["recent_offsite_backup"], "ok")
            self.assertEqual(report["checks"]["oauth_public_host"], "ok")
            self.assertEqual(report["checks"]["hsts"], "ok")
            self.assertEqual(report["checks"]["facebook_connection"], "ok")
            self.assertEqual(report["checks"]["facebook_page"], "ok")
            self.assertEqual(report["checks"]["recent_meta_diagnostic"], "ok")
            self.assertNotIn("never-print-this", str(report))
            self.assertNotIn("valid-test-key", str(report))

    def test_missing_and_insecure_configuration_is_not_ready(self):
        with tempfile.TemporaryDirectory() as directory:
            report = production_preflight(
                {
                    "META_REDIRECT_URI": "http://localhost/callback",
                    "AUTOFB_DATABASE_PATH": str(Path(directory) / "missing.db"),
                    "AUTOFB_MEDIA_DIR": str(Path(directory) / "media"),
                },
                encryption_key_validator=lambda value: False,
            )
        self.assertEqual(report["status"], "not_ready")
        self.assertIn("META_APP_SECRET", report["missing_environment"])
        self.assertIn("oauth_https_callback", report["failed_checks"])
        self.assertIn("worker", report["failed_checks"])

    def test_localhost_oauth_callback_is_not_a_production_callback(self):
        with tempfile.TemporaryDirectory() as directory:
            database = Database(Path(directory) / "autofb.db")
            database.initialize()
            report = production_preflight(
                {
                    "META_APP_ID": "app",
                    "META_APP_SECRET": "secret",
                    "META_REDIRECT_URI": "https://localhost/oauth/callback",
                    "AUTOFB_TOKEN_ENCRYPTION_KEY": "key",
                    "AUTOFB_DATABASE_PATH": database.path,
                    "AUTOFB_MEDIA_DIR": str(Path(directory) / "media"),
                },
                encryption_key_validator=lambda value: True,
            )
        self.assertEqual(report["checks"]["oauth_https_callback"], "error")

    def test_webhooks_must_be_public_https_urls_without_embedded_credentials(self):
        with tempfile.TemporaryDirectory() as directory:
            database = Database(Path(directory) / "autofb.db")
            database.initialize()
            report = production_preflight(
                {
                    "META_APP_ID": "app",
                    "META_APP_SECRET": "secret",
                    "META_REDIRECT_URI": "https://tool.example/oauth/callback",
                    "AUTOFB_TOKEN_ENCRYPTION_KEY": "key",
                    "AUTOFB_BACKUP_ALERT_URL": "https://alerts.example/backup?token=secret",
                    "AUTOFB_ERROR_WEBHOOK_URL": "https://token@errors.example/events",
                    "AUTOFB_DATABASE_PATH": database.path,
                    "AUTOFB_MEDIA_DIR": str(Path(directory) / "media"),
                },
                encryption_key_validator=lambda value: True,
            )
        self.assertEqual(report["checks"]["backup_alert_webhook"], "error")
        self.assertEqual(report["checks"]["error_webhook"], "error")

    def test_public_origin_must_match_oauth_host_and_enable_hsts(self):
        with tempfile.TemporaryDirectory() as directory:
            database = Database(Path(directory) / "autofb.db")
            database.initialize()
            report = production_preflight(
                {
                    "META_APP_ID": "app",
                    "META_APP_SECRET": "secret",
                    "META_REDIRECT_URI": "https://oauth.example/api/v1/oauth/facebook/callback",
                    "AUTOFB_TOKEN_ENCRYPTION_KEY": "key",
                    "AUTOFB_BACKUP_ALERT_URL": "https://alerts.example/backup",
                    "AUTOFB_ERROR_WEBHOOK_URL": "https://errors.example/events",
                    "AUTOFB_PUBLIC_URL": "https://tool.example/path?token=secret",
                    "AUTOFB_ENABLE_HSTS": "0",
                    "AUTOFB_DATABASE_PATH": database.path,
                    "AUTOFB_MEDIA_DIR": str(Path(directory) / "media"),
                },
                encryption_key_validator=lambda value: True,
            )
        self.assertEqual(report["checks"]["public_url"], "error")
        self.assertEqual(report["checks"]["oauth_public_host"], "error")
        self.assertEqual(report["checks"]["hsts"], "error")

    def test_meta_connection_page_and_recent_valid_diagnostic_are_required(self):
        with tempfile.TemporaryDirectory() as directory:
            database = Database(Path(directory) / "autofb.db")
            database.initialize()
            report = production_preflight(
                {
                    "META_APP_ID": "app",
                    "META_APP_SECRET": "secret",
                    "META_REDIRECT_URI": "https://tool.example/api/v1/oauth/facebook/callback",
                    "AUTOFB_TOKEN_ENCRYPTION_KEY": "key",
                    "AUTOFB_BACKUP_ALERT_URL": "https://alerts.example/backup",
                    "AUTOFB_ERROR_WEBHOOK_URL": "https://errors.example/events",
                    "AUTOFB_PUBLIC_URL": "https://tool.example",
                    "AUTOFB_ENABLE_HSTS": "1",
                    "AUTOFB_DATABASE_PATH": database.path,
                    "AUTOFB_MEDIA_DIR": str(Path(directory) / "media"),
                },
                encryption_key_validator=lambda value: True,
            )
        self.assertEqual(report["checks"]["facebook_connection"], "error")
        self.assertEqual(report["checks"]["facebook_page"], "error")
        self.assertEqual(report["checks"]["recent_meta_diagnostic"], "error")


if __name__ == "__main__":
    unittest.main()
