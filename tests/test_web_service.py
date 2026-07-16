import tempfile
import unittest
from pathlib import Path

from autofb.web.database import Database
from autofb.web.service import AutoFBService, ServiceError
from autofb.web.worker import PublishWorker


class AutoFBServiceTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        database = Database(Path(self.directory.name) / "autofb.db")
        database.initialize()
        self.service = AutoFBService(database)
        self.owner = self.service.register("owner@example.com", "a-very-strong-password", "Owner")
        self.editor = self.service.register("editor@example.com", "another-strong-password", "Editor")

    def test_session_identifies_registered_user(self):
        token = self.service.login("owner@example.com", "a-very-strong-password")
        self.assertEqual(self.service.user_for_token(token)["id"], self.owner["id"])
        self.service.logout(token)
        self.assertIsNone(self.service.user_for_token(token))

    def test_owner_can_add_editor_to_workspace(self):
        workspace = self.service.create_workspace(self.owner["id"], "Garden team")
        member = self.service.add_member(self.owner["id"], workspace["id"], "editor@example.com", "editor")
        self.assertEqual(member["role"], "editor")
        self.assertEqual(self.service.list_workspaces(self.editor["id"])[0]["id"], workspace["id"])

    def test_member_without_management_role_cannot_add_people(self):
        workspace = self.service.create_workspace(self.owner["id"], "Garden team")
        self.service.add_member(self.owner["id"], workspace["id"], "editor@example.com", "editor")
        with self.assertRaisesRegex(ServiceError, "permission"):
            self.service.add_member(self.editor["id"], workspace["id"], "owner@example.com", "viewer")

    def test_rejects_short_password(self):
        with self.assertRaisesRegex(ServiceError, "12 characters"):
            self.service.register("new@example.com", "short", "New user")


if __name__ == "__main__":
    unittest.main()

class FacebookConnectionStateTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        database = Database(Path(self.directory.name) / "autofb.db")
        database.initialize()
        self.service = AutoFBService(database)
        self.owner = self.service.register("owner@example.com", "a-very-strong-password", "Owner")
        self.other = self.service.register("other@example.com", "another-strong-password", "Other")
        self.workspace = self.service.create_workspace(self.owner["id"], "Garden team")

    def test_oauth_state_is_one_time_and_binds_workspace(self):
        state = self.service.create_oauth_state(self.owner["id"], self.workspace["id"])
        context = self.service.consume_oauth_state(state)
        self.assertEqual(context["workspace_id"], self.workspace["id"])
        with self.assertRaisesRegex(ServiceError, "invalid or expired"):
            self.service.consume_oauth_state(state)

    def test_non_member_cannot_create_oauth_state(self):
        with self.assertRaisesRegex(ServiceError, "permission"):
            self.service.create_oauth_state(self.other["id"], self.workspace["id"])


class FacebookPageStorageTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        database = Database(Path(self.directory.name) / "autofb.db")
        database.initialize()
        self.service = AutoFBService(database)
        self.owner = self.service.register("owner@example.com", "a-very-strong-password", "Owner")
        self.workspace = self.service.create_workspace(self.owner["id"], "Garden team")

    def test_saves_page_metadata_without_returning_token(self):
        self.service.save_facebook_connection(
            self.workspace["id"], self.owner["id"], "meta-user", "Meta User", "encrypted-user-token", None,
            [{"facebook_page_id": "page-1", "name": "Garden", "encrypted_access_token": "encrypted-page-token"}],
        )
        pages = self.service.list_facebook_pages(self.owner["id"], self.workspace["id"])
        self.assertEqual(pages[0]["facebook_page_id"], "page-1")
        self.assertNotIn("encrypted_access_token", pages[0])


class ContentSchedulingTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory(); self.addCleanup(self.directory.cleanup)
        database = Database(Path(self.directory.name) / "autofb.db"); database.initialize()
        self.service = AutoFBService(database)
        self.owner = self.service.register("owner@example.com", "a-very-strong-password", "Owner")
        self.workspace = self.service.create_workspace(self.owner["id"], "Garden team")
        self.connection = self.service.save_facebook_connection(self.workspace["id"], self.owner["id"], "meta-user", "Meta", "enc-user", None, [{"facebook_page_id": "p1", "name": "Garden", "encrypted_access_token": "enc-page"}])
        self.page = self.service.list_facebook_pages(self.owner["id"], self.workspace["id"])[0]

    def test_create_and_schedule_post_creates_durable_job(self):
        post = self.service.create_post(self.owner["id"], self.workspace["id"], self.page["id"], "Hello Garden")
        scheduled = self.service.schedule_post(self.owner["id"], self.workspace["id"], post["id"], "2030-01-01T10:00:00+00:00", "UTC")
        self.assertTrue(scheduled["job_id"])
        self.assertEqual(self.service.list_posts(self.owner["id"], self.workspace["id"])[0]["status"], "scheduled")


class PublishWorkerTests(ContentSchedulingTests):
    def test_worker_claims_and_completes_due_job(self):
        post = self.service.create_post(self.owner["id"], self.workspace["id"], self.page["id"], "Hello")
        self.service.schedule_post(self.owner["id"], self.workspace["id"], post["id"], "2030-01-01T10:00:00+00:00", "UTC")
        with self.service.database.connect() as conn:
            conn.execute("UPDATE publish_jobs SET run_at = '2000-01-01T00:00:00+00:00'")
        calls = []
        worker = PublishWorker(self.service.database, publisher=lambda page, token, body: calls.append((page, token, body)) or "remote-id", decryptor=lambda token: "plain-token")
        self.assertEqual(worker.run_once(), 1)
        self.assertEqual(calls[0][1], "plain-token")
        self.assertEqual(self.service.list_posts(self.owner["id"], self.workspace["id"])[0]["status"], "published")


class PublishRetryTests(PublishWorkerTests):
    def test_transient_failure_requeues_job_with_error(self):
        post = self.service.create_post(self.owner["id"], self.workspace["id"], self.page["id"], "Hello")
        self.service.schedule_post(self.owner["id"], self.workspace["id"], post["id"], "2030-01-01T10:00:00+00:00", "UTC")
        with self.service.database.connect() as conn:
            conn.execute("UPDATE publish_jobs SET run_at = '2000-01-01T00:00:00+00:00'")
        worker = PublishWorker(self.service.database, publisher=lambda *_: (_ for _ in ()).throw(RuntimeError("temporary")), decryptor=lambda _: "token")
        worker.run_once()
        with self.service.database.connect() as conn:
            job = conn.execute("SELECT status, attempts, last_error FROM publish_jobs").fetchone()
        self.assertEqual(job["status"], "queued")
        self.assertEqual(job["attempts"], 1)
        self.assertEqual(job["last_error"], "temporary")

class OperationalVisibilityTests(FacebookPageStorageTests):
    def test_workspace_connection_health_and_notifications_are_scoped(self):
        connection = self.service.save_facebook_connection(
            self.workspace["id"], self.owner["id"], "meta-user", "Meta User", "enc", "2030-01-01T00:00:00+00:00", []
        )
        self.service.notify_workspace(self.workspace["id"], "token_expiring", "Reconnect Meta")
        self.assertEqual(self.service.connection_health(self.owner["id"], self.workspace["id"])[0]["id"], connection["id"])
        self.assertEqual(self.service.list_notifications(self.owner["id"], self.workspace["id"])[0]["type"], "token_expiring")
