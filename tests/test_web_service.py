import os
import json
import tempfile
import unittest
from datetime import UTC, datetime, timedelta
from pathlib import Path

from autofb.web.database import Database
from autofb.web.service import AuthenticationThrottled, AutoFBService, ServiceError
from autofb.web.worker import ProviderRateLimitError, PublishWorker


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

    def test_repeated_login_failures_temporarily_lock_identifier(self):
        for _ in range(5):
            with self.assertRaisesRegex(ServiceError, "Invalid email"):
                self.service.login("owner@example.com", "wrong-password")
        with self.assertRaisesRegex(AuthenticationThrottled, "Too many login attempts"):
            self.service.login("owner@example.com", "a-very-strong-password")

    def test_successful_login_clears_previous_failures(self):
        for _ in range(4):
            with self.assertRaises(ServiceError):
                self.service.login("owner@example.com", "wrong-password")
        self.assertTrue(self.service.login("owner@example.com", "a-very-strong-password"))
        with self.service.database.connect() as conn:
            attempts = conn.execute("SELECT COUNT(*) FROM auth_login_attempts").fetchone()[0]
        self.assertEqual(attempts, 0)

    def test_unknown_email_failures_are_recorded_without_storing_email(self):
        with self.assertRaisesRegex(ServiceError, "Invalid email"):
            self.service.login("missing@example.com", "wrong-password")
        with self.service.database.connect() as conn:
            row = conn.execute("SELECT email_hash, failed_count FROM auth_login_attempts").fetchone()
        self.assertEqual(row["failed_count"], 1)
        self.assertNotIn("missing@example.com", row["email_hash"])

    def test_change_password_rotates_sessions_and_accepts_new_password(self):
        token = self.service.login("owner@example.com", "a-very-strong-password")
        changed = self.service.change_password(self.owner["id"], "a-very-strong-password", "new-strong-password")
        self.assertEqual(changed["status"], "password_changed")
        self.assertIsNone(self.service.user_for_token(token))
        with self.assertRaisesRegex(ServiceError, "Invalid email"):
            self.service.login("owner@example.com", "a-very-strong-password")
        self.assertTrue(self.service.login("owner@example.com", "new-strong-password"))

    def test_change_password_requires_current_password(self):
        with self.assertRaisesRegex(ServiceError, "Current password"):
            self.service.change_password(self.owner["id"], "wrong-password", "new-strong-password")

    def test_user_can_update_display_name(self):
        updated = self.service.update_profile(self.owner["id"], "New Owner")
        self.assertEqual(updated["display_name"], "New Owner")
        token = self.service.login("owner@example.com", "a-very-strong-password")
        self.assertEqual(self.service.user_for_token(token)["display_name"], "New Owner")

    def test_update_profile_rejects_blank_display_name(self):
        with self.assertRaisesRegex(ServiceError, "Display name"):
            self.service.update_profile(self.owner["id"], "   ")

    def test_owner_can_add_editor_to_workspace(self):
        workspace = self.service.create_workspace(self.owner["id"], "Garden team")
        member = self.service.add_member(self.owner["id"], workspace["id"], "editor@example.com", "editor")
        self.assertEqual(member["role"], "editor")
        self.assertEqual(self.service.list_workspaces(self.editor["id"])[0]["id"], workspace["id"])
        members = self.service.list_members(self.owner["id"], workspace["id"])
        self.assertEqual([item["role"] for item in members], ["owner", "editor"])

    def test_member_without_management_role_cannot_add_people(self):
        workspace = self.service.create_workspace(self.owner["id"], "Garden team")
        self.service.add_member(self.owner["id"], workspace["id"], "editor@example.com", "editor")
        with self.assertRaisesRegex(ServiceError, "permission"):
            self.service.add_member(self.editor["id"], workspace["id"], "owner@example.com", "viewer")

    def test_owner_can_rename_workspace(self):
        workspace = self.service.create_workspace(self.owner["id"], "Garden team")
        renamed = self.service.update_workspace(self.owner["id"], workspace["id"], "River team")
        self.assertEqual(renamed["name"], "River team")
        self.assertEqual(self.service.list_workspaces(self.owner["id"])[0]["name"], "River team")

    def test_owner_can_export_workspace_without_secrets(self):
        workspace = self.service.create_workspace(self.owner["id"], "Export team")
        self.service.save_facebook_connection(
            workspace["id"], self.owner["id"], "provider-secret-id", "Meta User", "encrypted-user-secret", None,
            [{"facebook_page_id": "page-export", "name": "Export Page", "encrypted_access_token": "encrypted-page-secret"}],
        )
        exported = self.service.export_workspace_data(self.owner["id"], workspace["id"])
        serialized = json.dumps(exported)
        self.assertEqual(exported["workspace"]["name"], "Export team")
        self.assertEqual(exported["schema_version"], 1)
        self.assertNotIn("encrypted-user-secret", serialized)
        self.assertNotIn("encrypted-page-secret", serialized)
        self.assertNotIn("provider-secret-id", serialized)

    def test_viewer_cannot_export_workspace(self):
        workspace = self.service.create_workspace(self.owner["id"], "Private export")
        self.service.add_member(self.owner["id"], workspace["id"], self.editor["email"], "viewer")
        with self.assertRaisesRegex(ServiceError, "permission"):
            self.service.export_workspace_data(self.editor["id"], workspace["id"])

    def test_member_without_management_role_cannot_rename_workspace(self):
        workspace = self.service.create_workspace(self.owner["id"], "Garden team")
        self.service.add_member(self.owner["id"], workspace["id"], "editor@example.com", "editor")
        with self.assertRaisesRegex(ServiceError, "permission"):
            self.service.update_workspace(self.editor["id"], workspace["id"], "Nope")

    def test_owner_can_remove_non_owner_member(self):
        workspace = self.service.create_workspace(self.owner["id"], "Garden team")
        member = self.service.add_member(self.owner["id"], workspace["id"], "editor@example.com", "editor")
        removed = self.service.remove_member(self.owner["id"], workspace["id"], member["id"])
        self.assertEqual(removed["status"], "removed")
        self.assertEqual([item["id"] for item in self.service.list_members(self.owner["id"], workspace["id"])], [self.owner["id"]])

    def test_workspace_owner_cannot_be_removed(self):
        workspace = self.service.create_workspace(self.owner["id"], "Garden team")
        with self.assertRaisesRegex(ServiceError, "owner cannot be removed"):
            self.service.remove_member(self.owner["id"], workspace["id"], self.owner["id"])

    def test_owner_deletes_workspace_then_erases_account(self):
        workspace = self.service.create_workspace(self.owner["id"], "Disposable")
        media_path = Path(self.directory.name) / "private.jpg"
        media_path.write_bytes(b"private")
        self.service.register_media(self.owner["id"], workspace["id"], "private.jpg", str(media_path), "image/jpeg", 7)
        deleted_workspace = self.service.delete_workspace(self.owner["id"], workspace["id"])
        self.assertEqual(deleted_workspace["media_paths"], [str(media_path)])
        self.assertEqual(self.service.list_workspaces(self.owner["id"]), [])

        token = self.service.login("owner@example.com", "a-very-strong-password")
        self.assertEqual(self.service.delete_account(self.owner["id"], "a-very-strong-password")["status"], "deleted")
        self.assertIsNone(self.service.user_for_token(token))
        with self.assertRaisesRegex(ServiceError, "Invalid email"):
            self.service.login("owner@example.com", "a-very-strong-password")
        with self.service.database.connect() as conn:
            redacted = conn.execute("SELECT email, display_name FROM users WHERE id = ?", (self.owner["id"],)).fetchone()
        self.assertTrue(redacted["email"].endswith("@invalid.local"))
        self.assertEqual(redacted["display_name"], "Deleted user")

    def test_account_deletion_requires_owned_workspaces_to_be_deleted(self):
        self.service.create_workspace(self.owner["id"], "Still owned")
        with self.assertRaisesRegex(ServiceError, "owned workspaces"):
            self.service.delete_account(self.owner["id"], "a-very-strong-password")

    def test_non_owner_cannot_delete_workspace(self):
        workspace = self.service.create_workspace(self.owner["id"], "Protected")
        self.service.add_member(self.owner["id"], workspace["id"], self.editor["email"], "admin")
        with self.assertRaisesRegex(ServiceError, "permission"):
            self.service.delete_workspace(self.editor["id"], workspace["id"])

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

    def test_owner_can_import_manual_page_token(self):
        page = self.service.import_facebook_page(
            self.owner["id"],
            self.workspace["id"],
            "page-1",
            "Garden",
            "encrypted-page-token",
            "2030-01-01T00:00:00+00:00",
        )
        self.assertEqual(page["facebook_page_id"], "page-1")
        self.assertEqual(self.service.list_facebook_pages(self.owner["id"], self.workspace["id"])[0]["name"], "Garden")

    def test_non_manager_cannot_import_manual_page_token(self):
        viewer = self.service.register("viewer@example.com", "viewer-strong-password", "Viewer")
        self.service.add_member(self.owner["id"], self.workspace["id"], "viewer@example.com", "viewer")
        with self.assertRaisesRegex(ServiceError, "permission"):
            self.service.import_facebook_page(viewer["id"], self.workspace["id"], "page-1", "Garden", "encrypted")

    def test_owner_can_delete_unused_facebook_page(self):
        page = self.service.import_facebook_page(self.owner["id"], self.workspace["id"], "page-1", "Garden", "encrypted")
        deleted = self.service.delete_facebook_page(self.owner["id"], self.workspace["id"], page["id"])
        self.assertEqual(deleted["status"], "deleted")
        self.assertEqual(self.service.list_facebook_pages(self.owner["id"], self.workspace["id"]), [])

    def test_delete_facebook_page_rejects_page_used_by_posts(self):
        page = self.service.import_facebook_page(self.owner["id"], self.workspace["id"], "page-1", "Garden", "encrypted")
        self.service.create_post(self.owner["id"], self.workspace["id"], page["id"], "Hello")
        with self.assertRaisesRegex(ServiceError, "used by posts"):
            self.service.delete_facebook_page(self.owner["id"], self.workspace["id"], page["id"])


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
        jobs = self.service.list_publish_jobs(self.owner["id"], self.workspace["id"])
        self.assertEqual(jobs[0]["id"], scheduled["job_id"])
        self.assertEqual(jobs[0]["page_name"], "Garden")

    def test_calendar_lists_only_posts_in_requested_range(self):
        january = self.service.create_post(self.owner["id"], self.workspace["id"], self.page["id"], "January")
        february = self.service.create_post(self.owner["id"], self.workspace["id"], self.page["id"], "February")
        self.service.schedule_post(self.owner["id"], self.workspace["id"], january["id"], "2030-01-15T10:00:00+00:00", "UTC")
        self.service.schedule_post(self.owner["id"], self.workspace["id"], february["id"], "2030-02-15T10:00:00+00:00", "UTC")

        entries = self.service.list_calendar(
            self.owner["id"], self.workspace["id"], "2030-01-01T00:00:00+00:00", "2030-02-01T00:00:00+00:00"
        )
        self.assertEqual([entry["body"] for entry in entries], ["January"])
        self.assertEqual(entries[0]["page_name"], "Garden")

    def test_calendar_rejects_invalid_or_excessive_range(self):
        with self.assertRaisesRegex(ServiceError, "after start"):
            self.service.list_calendar(self.owner["id"], self.workspace["id"], "2030-02-01", "2030-01-01")
        with self.assertRaisesRegex(ServiceError, "366 days"):
            self.service.list_calendar(self.owner["id"], self.workspace["id"], "2030-01-01", "2032-01-01")

    def test_editor_requires_owner_approval_before_scheduling(self):
        editor = self.service.register("approval-editor@example.com", "approval-editor-password", "Approval Editor")
        self.service.add_member(self.owner["id"], self.workspace["id"], editor["email"], "editor")
        post = self.service.create_post(editor["id"], self.workspace["id"], self.page["id"], "Review this")
        with self.assertRaisesRegex(ServiceError, "must be approved"):
            self.service.schedule_post(editor["id"], self.workspace["id"], post["id"], "2030-03-01T10:00:00+00:00", "UTC")
        requested = self.service.request_post_approval(editor["id"], self.workspace["id"], post["id"], "Please review")
        self.assertEqual(requested["status"], "pending")
        with self.assertRaisesRegex(ServiceError, "must be approved"):
            self.service.publish_post_now(editor["id"], self.workspace["id"], post["id"])
        reviewed = self.service.review_post_approval(self.owner["id"], self.workspace["id"], post["id"], "approved", "Looks good")
        self.assertEqual(reviewed["status"], "approved")
        self.assertEqual(self.service.list_notifications(editor["id"], self.workspace["id"])[0]["type"], "approval_reviewed")
        scheduled = self.service.schedule_post(editor["id"], self.workspace["id"], post["id"], "2030-03-01T10:00:00+00:00", "UTC")
        self.assertTrue(scheduled["job_id"])

    def test_editor_cannot_review_approval(self):
        editor = self.service.register("review-editor@example.com", "review-editor-password", "Review Editor")
        self.service.add_member(self.owner["id"], self.workspace["id"], editor["email"], "editor")
        post = self.service.create_post(editor["id"], self.workspace["id"], self.page["id"], "No self approval")
        self.service.request_post_approval(editor["id"], self.workspace["id"], post["id"])
        with self.assertRaisesRegex(ServiceError, "permission"):
            self.service.review_post_approval(editor["id"], self.workspace["id"], post["id"], "approved")

    def test_workspace_summary_counts_content_and_unread_notifications(self):
        self.service.register_media(self.owner["id"], self.workspace["id"], "rose.jpg", "/media/rose.jpg", "image/jpeg", 42)
        post = self.service.create_post(self.owner["id"], self.workspace["id"], self.page["id"], "Hello summary")
        self.service.schedule_post(self.owner["id"], self.workspace["id"], post["id"], "2030-01-01T10:00:00+00:00", "UTC")
        self.service.notify_workspace(self.workspace["id"], "token_expiring", "Reconnect Meta")
        summary = self.service.workspace_summary(self.owner["id"], self.workspace["id"])
        self.assertEqual(summary["members"], 1)
        self.assertEqual(summary["pages"], 1)
        self.assertEqual(summary["media"], 1)
        self.assertEqual(summary["posts"], 1)
        self.assertEqual(summary["queued_jobs"], 1)
        self.assertEqual(summary["unread_notifications"], 1)

    def test_list_posts_can_filter_by_status(self):
        draft = self.service.create_post(self.owner["id"], self.workspace["id"], self.page["id"], "Draft only")
        queued = self.service.create_post(self.owner["id"], self.workspace["id"], self.page["id"], "Queue only")
        self.service.publish_post_now(self.owner["id"], self.workspace["id"], queued["id"])
        filtered = self.service.list_posts(self.owner["id"], self.workspace["id"], "queued")
        self.assertEqual([post["id"] for post in filtered], [queued["id"]])
        self.assertEqual(self.service.list_posts(self.owner["id"], self.workspace["id"], "draft")[0]["id"], draft["id"])
        with self.assertRaisesRegex(ServiceError, "status filter"):
            self.service.list_posts(self.owner["id"], self.workspace["id"], "unknown")

    def test_export_posts_csv_respects_status_filter(self):
        self.service.create_post(self.owner["id"], self.workspace["id"], self.page["id"], "Draft export")
        queued = self.service.create_post(self.owner["id"], self.workspace["id"], self.page["id"], "Queued export")
        self.service.publish_post_now(self.owner["id"], self.workspace["id"], queued["id"])
        csv_body = self.service.export_posts_csv(self.owner["id"], self.workspace["id"], "queued")
        self.assertIn("status,body", csv_body)
        self.assertIn("Queued export", csv_body)
        self.assertNotIn("Draft export", csv_body)

    def test_publish_post_now_creates_immediate_job(self):
        post = self.service.create_post(self.owner["id"], self.workspace["id"], self.page["id"], "Hello now")
        queued = self.service.publish_post_now(self.owner["id"], self.workspace["id"], post["id"])
        self.assertTrue(queued["job_id"])
        self.assertEqual(self.service.list_posts(self.owner["id"], self.workspace["id"])[0]["status"], "queued")
        jobs = self.service.list_publish_jobs(self.owner["id"], self.workspace["id"])
        self.assertEqual(jobs[0]["id"], queued["job_id"])
        self.assertEqual(jobs[0]["status"], "queued")

    def test_rescheduling_reuses_schedule_and_queued_job(self):
        post = self.service.create_post(self.owner["id"], self.workspace["id"], self.page["id"], "Reschedule")
        first = self.service.schedule_post(
            self.owner["id"], self.workspace["id"], post["id"], "2030-01-01T10:00:00+00:00", "UTC"
        )
        second = self.service.schedule_post(
            self.owner["id"], self.workspace["id"], post["id"], "2030-01-02T10:00:00+00:00", "UTC"
        )
        self.assertEqual(second["id"], first["id"])
        self.assertEqual(second["job_id"], first["job_id"])
        jobs = self.service.list_publish_jobs(self.owner["id"], self.workspace["id"])
        self.assertEqual(len(jobs), 1)
        self.assertEqual(jobs[0]["run_at"], "2030-01-02T10:00:00+00:00")

    def test_publish_now_reuses_existing_queued_job(self):
        post = self.service.create_post(self.owner["id"], self.workspace["id"], self.page["id"], "Publish once")
        scheduled = self.service.schedule_post(
            self.owner["id"], self.workspace["id"], post["id"], "2030-01-01T10:00:00+00:00", "UTC"
        )
        immediate = self.service.publish_post_now(self.owner["id"], self.workspace["id"], post["id"])
        self.assertEqual(immediate["job_id"], scheduled["job_id"])
        self.assertEqual(len(self.service.list_publish_jobs(self.owner["id"], self.workspace["id"])), 1)

    def test_retry_failed_post_creates_new_job(self):
        post = self.service.create_post(self.owner["id"], self.workspace["id"], self.page["id"], "Hello retry")
        with self.service.database.connect() as conn:
            conn.execute("UPDATE posts SET status = 'failed' WHERE id = ?", (post["id"],))
        retried = self.service.retry_failed_post(self.owner["id"], self.workspace["id"], post["id"])
        self.assertTrue(retried["job_id"])
        self.assertEqual(self.service.list_posts(self.owner["id"], self.workspace["id"])[0]["status"], "queued")
        jobs = self.service.list_publish_jobs(self.owner["id"], self.workspace["id"])
        self.assertEqual(jobs[0]["id"], retried["job_id"])

    def test_retry_rejects_non_failed_post(self):
        post = self.service.create_post(self.owner["id"], self.workspace["id"], self.page["id"], "Hello draft")
        with self.assertRaisesRegex(ServiceError, "Only failed"):
            self.service.retry_failed_post(self.owner["id"], self.workspace["id"], post["id"])

    def test_duplicate_post_copies_body_and_media_as_draft(self):
        media = self.service.register_media(self.owner["id"], self.workspace["id"], "rose.jpg", "/media/rose.jpg", "image/jpeg", 42)
        post = self.service.create_post(self.owner["id"], self.workspace["id"], self.page["id"], "Reuse this", [media["id"]])
        duplicated = self.service.duplicate_post(self.owner["id"], self.workspace["id"], post["id"])
        self.assertNotEqual(duplicated["id"], post["id"])
        self.assertEqual(duplicated["body"], "Reuse this")
        posts = self.service.list_posts(self.owner["id"], self.workspace["id"])
        copied = next(item for item in posts if item["id"] == duplicated["id"])
        self.assertEqual(copied["status"], "draft")
        self.assertEqual(copied["media_count"], 1)

    def test_update_draft_post_changes_body(self):
        post = self.service.create_post(self.owner["id"], self.workspace["id"], self.page["id"], "Old body")
        updated = self.service.update_post(self.owner["id"], self.workspace["id"], post["id"], "New body")
        self.assertEqual(updated["body"], "New body")
        self.assertEqual(self.service.list_posts(self.owner["id"], self.workspace["id"])[0]["body"], "New body")

    def test_update_rejects_scheduled_post(self):
        post = self.service.create_post(self.owner["id"], self.workspace["id"], self.page["id"], "Keep schedule")
        self.service.schedule_post(self.owner["id"], self.workspace["id"], post["id"], "2030-01-01T10:00:00+00:00", "UTC")
        with self.assertRaisesRegex(ServiceError, "Only draft or failed"):
            self.service.update_post(self.owner["id"], self.workspace["id"], post["id"], "Edited")

    def test_delete_draft_post_removes_it_from_workspace(self):
        post = self.service.create_post(self.owner["id"], self.workspace["id"], self.page["id"], "Remove me")
        deleted = self.service.delete_post(self.owner["id"], self.workspace["id"], post["id"])
        self.assertEqual(deleted["status"], "deleted")
        self.assertEqual(self.service.list_posts(self.owner["id"], self.workspace["id"]), [])

    def test_delete_rejects_scheduled_post(self):
        post = self.service.create_post(self.owner["id"], self.workspace["id"], self.page["id"], "Keep schedule")
        self.service.schedule_post(self.owner["id"], self.workspace["id"], post["id"], "2030-01-01T10:00:00+00:00", "UTC")
        with self.assertRaisesRegex(ServiceError, "Only draft or failed"):
            self.service.delete_post(self.owner["id"], self.workspace["id"], post["id"])

    def test_cancel_scheduled_post_removes_schedule_and_job(self):
        post = self.service.create_post(self.owner["id"], self.workspace["id"], self.page["id"], "Hello Garden")
        self.service.schedule_post(self.owner["id"], self.workspace["id"], post["id"], "2030-01-01T10:00:00+00:00", "UTC")
        result = self.service.cancel_scheduled_post(self.owner["id"], self.workspace["id"], post["id"])
        self.assertEqual(result["updated_jobs"], 1)
        self.assertEqual(self.service.list_posts(self.owner["id"], self.workspace["id"])[0]["status"], "draft")
        self.assertEqual(self.service.list_publish_jobs(self.owner["id"], self.workspace["id"])[0]["status"], "failed")


class PublishWorkerTests(ContentSchedulingTests):
    def test_meta_rate_limit_parses_retry_after_and_caps_delay(self):
        class Response:
            status_code = 429
            headers = {"Retry-After": "9999"}

            def raise_for_status(self):
                raise AssertionError("generic status handler should not run")

        with self.assertRaises(ProviderRateLimitError) as raised:
            PublishWorker._raise_for_status(Response())
        self.assertEqual(raised.exception.retry_after_seconds, 3600)

    def test_meta_retry_after_supports_http_date_and_invalid_fallback(self):
        current = datetime(2026, 7, 26, 12, 0, tzinfo=UTC)
        self.assertEqual(
            PublishWorker._retry_after_seconds("Sun, 26 Jul 2026 12:05:00 GMT", current),
            300,
        )
        self.assertEqual(PublishWorker._retry_after_seconds("not-a-date", current), 60)
        self.assertEqual(PublishWorker._retry_after_seconds(None, current), 60)
        self.assertEqual(PublishWorker._retry_after_seconds("0", current), 1)

    def test_rate_limited_job_uses_provider_retry_delay(self):
        post = self.service.create_post(self.owner["id"], self.workspace["id"], self.page["id"], "Rate limited")
        queued = self.service.publish_post_now(self.owner["id"], self.workspace["id"], post["id"])
        with self.service.database.connect() as conn:
            conn.execute("UPDATE publish_jobs SET status = 'running', attempts = 1 WHERE id = ?", (queued["job_id"],))
        worker = PublishWorker(self.service.database, publisher=lambda *_: "unused", decryptor=lambda token: token)
        before = datetime.now(UTC)

        self.assertTrue(
            worker._handle_failure(
                {"id": queued["job_id"], "post_id": post["id"], "attempts": 1},
                ProviderRateLimitError(300),
            )
        )
        with self.service.database.connect() as conn:
            job = conn.execute("SELECT run_at, last_error FROM publish_jobs WHERE id = ?", (queued["job_id"],)).fetchone()
        retry_at = datetime.fromisoformat(job["run_at"])
        self.assertGreaterEqual(retry_at, before + timedelta(seconds=299))
        self.assertIn("retry after 300", job["last_error"])

    def test_worker_rejects_invalid_batch_size(self):
        for value in (0, 101):
            with self.subTest(value=value), self.assertRaisesRegex(ValueError, "batch_size"):
                PublishWorker(
                    self.service.database,
                    publisher=lambda *_: "remote-id",
                    decryptor=lambda token: token,
                    batch_size=value,
                )

    def test_worker_limits_each_poll_to_configured_batch(self):
        for index in range(3):
            post = self.service.create_post(
                self.owner["id"], self.workspace["id"], self.page["id"], f"Batch post {index}"
            )
            self.service.publish_post_now(self.owner["id"], self.workspace["id"], post["id"])
        with self.service.database.connect() as conn:
            conn.execute("UPDATE publish_jobs SET run_at = '2000-01-01T00:00:00+00:00'")
        calls = []
        worker = PublishWorker(
            self.service.database,
            publisher=lambda page, token, body: calls.append(body) or f"remote-{len(calls)}",
            decryptor=lambda token: token,
            batch_size=2,
        )

        self.assertEqual(worker.run_once(), 2)
        self.assertEqual(len(calls), 2)
        statuses = [job["status"] for job in self.service.list_publish_jobs(self.owner["id"], self.workspace["id"])]
        self.assertEqual(statuses.count("queued"), 1)
        self.assertEqual(worker.run_once(), 1)
        self.assertEqual(len(calls), 3)

    def test_worker_paces_provider_deliveries_within_batch(self):
        for index in range(3):
            post = self.service.create_post(
                self.owner["id"], self.workspace["id"], self.page["id"], f"Paced post {index}"
            )
            self.service.publish_post_now(self.owner["id"], self.workspace["id"], post["id"])
        with self.service.database.connect() as conn:
            conn.execute("UPDATE publish_jobs SET run_at = '2000-01-01T00:00:00+00:00'")
        sleeps = []
        worker = PublishWorker(
            self.service.database,
            publisher=lambda page, token, body: f"remote-{body}",
            decryptor=lambda token: token,
            batch_size=3,
            min_publish_interval=1.5,
            sleeper=sleeps.append,
        )

        self.assertEqual(worker.run_once(), 3)
        self.assertEqual(sleeps, [1.5, 1.5])

    def test_worker_rejects_invalid_publish_interval(self):
        for value in (-0.1, 60.1):
            with self.subTest(value=value), self.assertRaisesRegex(ValueError, "min_publish_interval"):
                PublishWorker(
                    self.service.database,
                    publisher=lambda *_: "remote-id",
                    decryptor=lambda token: token,
                    min_publish_interval=value,
                )

    def test_worker_loop_rejects_invalid_poll_interval(self):
        worker = PublishWorker(self.service.database, publisher=lambda *_: "remote-id", decryptor=lambda token: "plain-token")
        with self.assertRaisesRegex(ValueError, "poll_seconds"):
            worker.run_forever(0)

    def test_worker_records_idle_heartbeat_after_poll(self):
        worker = PublishWorker(
            self.service.database,
            publisher=lambda page_id, token, body: "remote-unused",
            decryptor=lambda token: token,
            worker_id="worker-test",
        )
        self.assertEqual(worker.run_once(), 0)
        with self.service.database.connect() as conn:
            heartbeat = conn.execute(
                "SELECT status, last_error FROM worker_heartbeats WHERE worker_id = 'worker-test'"
            ).fetchone()
        self.assertEqual(dict(heartbeat), {"status": "idle", "last_error": None})

    def test_publish_metrics_count_jobs_and_results(self):
        post = self.service.create_post(self.owner["id"], self.workspace["id"], self.page["id"], "Hello metrics")
        self.service.publish_post_now(self.owner["id"], self.workspace["id"], post["id"])
        metrics = self.service.publish_metrics(self.owner["id"], self.workspace["id"])
        self.assertEqual(metrics["jobs_queued"], 1)
        with self.service.database.connect() as conn:
            conn.execute("UPDATE publish_jobs SET run_at = '2000-01-01T00:00:00+00:00'")
        worker = PublishWorker(self.service.database, publisher=lambda page, token, body: "remote-metrics", decryptor=lambda token: "plain-token")
        worker.run_once()
        metrics = self.service.publish_metrics(self.owner["id"], self.workspace["id"])
        self.assertEqual(metrics["jobs_succeeded"], 1)
        self.assertEqual(metrics["results_succeeded"], 1)

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
        results = self.service.list_publish_results(self.owner["id"], self.workspace["id"])
        self.assertEqual(results[0]["status"], "succeeded")
        self.assertEqual(results[0]["remote_post_id"], "remote-id")

    def test_worker_recovers_stale_running_job(self):
        post = self.service.create_post(self.owner["id"], self.workspace["id"], self.page["id"], "Hello recover")
        queued = self.service.publish_post_now(self.owner["id"], self.workspace["id"], post["id"])
        with self.service.database.connect() as conn:
            conn.execute(
                "UPDATE publish_jobs SET status = 'running', updated_at = ? WHERE id = ?",
                ("2000-01-01T00:00:00+00:00", queued["job_id"]),
            )
        worker = PublishWorker(self.service.database, publisher=lambda page, token, body: "remote-recovered", decryptor=lambda token: "plain-token")
        self.assertEqual(worker.run_once(), 1)
        self.assertEqual(self.service.list_posts(self.owner["id"], self.workspace["id"])[0]["status"], "published")

    def test_worker_finalizes_stale_job_with_existing_success_without_republishing(self):
        post = self.service.create_post(self.owner["id"], self.workspace["id"], self.page["id"], "Already delivered")
        queued = self.service.publish_post_now(self.owner["id"], self.workspace["id"], post["id"])
        with self.service.database.connect() as conn:
            conn.execute(
                "UPDATE publish_jobs SET status = 'running', attempts = 1, updated_at = ? WHERE id = ?",
                ("2000-01-01T00:00:00+00:00", queued["job_id"]),
            )
            conn.execute(
                """INSERT INTO publish_results(id, job_id, post_id, status, attempt, remote_post_id, error, created_at)
                   VALUES ('result-existing', ?, ?, 'succeeded', 1, 'remote-existing', NULL, '2000-01-01T00:00:01+00:00')""",
                (queued["job_id"], post["id"]),
            )
        calls = []
        worker = PublishWorker(
            self.service.database,
            publisher=lambda *args: calls.append(args) or "duplicate-remote-id",
            decryptor=lambda token: "plain-token",
        )

        self.assertEqual(worker.run_once(), 0)
        self.assertEqual(calls, [])
        self.assertEqual(self.service.list_posts(self.owner["id"], self.workspace["id"])[0]["status"], "published")
        job = self.service.list_publish_jobs(self.owner["id"], self.workspace["id"])[0]
        self.assertEqual(job["status"], "succeeded")
        self.assertEqual(len(self.service.list_publish_results(self.owner["id"], self.workspace["id"])), 1)

    def test_worker_passes_attached_media_to_media_publisher(self):
        media = self.service.register_media(self.owner["id"], self.workspace["id"], "rose.jpg", "/media/rose.jpg", "image/jpeg", 42)
        post = self.service.create_post(self.owner["id"], self.workspace["id"], self.page["id"], "Hello with media", [media["id"]])
        self.service.schedule_post(self.owner["id"], self.workspace["id"], post["id"], "2030-01-01T10:00:00+00:00", "UTC")
        with self.service.database.connect() as conn:
            conn.execute("UPDATE publish_jobs SET run_at = '2000-01-01T00:00:00+00:00'")
        calls = []
        worker = PublishWorker(
            self.service.database,
            publisher=lambda *_: "text-remote-id",
            media_publisher=lambda page, token, body, attachments: calls.append((page, token, body, attachments)) or "media-remote-id",
            decryptor=lambda token: "plain-token",
        )
        self.assertEqual(worker.run_once(), 1)
        self.assertEqual(calls[0][0], "p1")
        self.assertEqual(calls[0][1], "plain-token")
        self.assertEqual(calls[0][3][0]["filename"], "rose.jpg")


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
        results = self.service.list_publish_results(self.owner["id"], self.workspace["id"])
        self.assertEqual(results[0]["status"], "failed")
        self.assertEqual(results[0]["error"], "temporary")

    def test_default_decryptor_missing_key_error_does_not_require_meta_oauth_settings(self):
        previous = {
            "AUTOFB_TOKEN_ENCRYPTION_KEY": os.environ.get("AUTOFB_TOKEN_ENCRYPTION_KEY"),
            "META_APP_ID": os.environ.get("META_APP_ID"),
            "META_APP_SECRET": os.environ.get("META_APP_SECRET"),
            "META_REDIRECT_URI": os.environ.get("META_REDIRECT_URI"),
        }
        try:
            os.environ.pop("AUTOFB_TOKEN_ENCRYPTION_KEY", None)
            os.environ.pop("META_APP_ID", None)
            os.environ.pop("META_APP_SECRET", None)
            os.environ.pop("META_REDIRECT_URI", None)
            with self.assertRaisesRegex(RuntimeError, "AUTOFB_TOKEN_ENCRYPTION_KEY"):
                PublishWorker._configured_decryptor()
        finally:
            for name, value in previous.items():
                if value is None:
                    os.environ.pop(name, None)
                else:
                    os.environ[name] = value

class OperationalVisibilityTests(FacebookPageStorageTests):
    def test_workspace_connection_health_and_notifications_are_scoped(self):
        connection = self.service.save_facebook_connection(
            self.workspace["id"], self.owner["id"], "meta-user", "Meta User", "enc", "2030-01-01T00:00:00+00:00", []
        )
        self.service.notify_workspace(self.workspace["id"], "token_expiring", "Reconnect Meta")
        self.assertEqual(self.service.connection_health(self.owner["id"], self.workspace["id"])[0]["id"], connection["id"])
        self.assertEqual(self.service.list_notifications(self.owner["id"], self.workspace["id"])[0]["type"], "token_expiring")
        result = self.service.mark_notifications_read(self.owner["id"], self.workspace["id"])
        self.assertEqual(result["updated"], 1)
        self.assertIsNotNone(self.service.list_notifications(self.owner["id"], self.workspace["id"])[0]["read_at"])
        cleared = self.service.clear_read_notifications(self.owner["id"], self.workspace["id"])
        self.assertEqual(cleared["deleted"], 1)
        self.assertEqual(self.service.list_notifications(self.owner["id"], self.workspace["id"]), [])

    def test_connection_health_classifies_expiry(self):
        reference = datetime(2030, 1, 1, tzinfo=UTC)
        cases = [
            ("expired", "2029-12-31T00:00:00+00:00"),
            ("expiring", "2030-01-05T00:00:00+00:00"),
            ("healthy", "2030-02-01T00:00:00+00:00"),
            ("unknown", None),
        ]
        for index, (expected, expiry) in enumerate(cases):
            self.service.save_facebook_connection(
                self.workspace["id"], self.owner["id"], f"health-{index}", expected, "enc", expiry, []
            )
        health = {
            item["display_name"]: item["health"]
            for item in self.service.connection_health(self.owner["id"], self.workspace["id"], reference)
        }
        self.assertEqual(health, {name: name for name, _ in cases})

    def test_owner_can_delete_unused_connection(self):
        connection = self.service.save_facebook_connection(
            self.workspace["id"], self.owner["id"], "unused-user", "Unused", "enc", None, []
        )
        result = self.service.delete_facebook_connection(self.owner["id"], self.workspace["id"], connection["id"])
        self.assertEqual(result["status"], "deleted")
        self.assertNotIn(connection["id"], [item["id"] for item in self.service.connection_health(self.owner["id"], self.workspace["id"])])

    def test_connection_diagnostic_history_is_scoped_and_visible(self):
        connection = self.service.save_facebook_connection(
            self.workspace["id"], self.owner["id"], "diagnostic-user", "Diagnostic", "encrypted-secret", None, []
        )
        encrypted = self.service.connection_token_for_diagnostics(self.owner["id"], self.workspace["id"], connection["id"])
        self.assertEqual(encrypted, "encrypted-secret")
        recorded = self.service.record_connection_diagnostic(
            self.owner["id"], self.workspace["id"], connection["id"], "invalid", "Token expired"
        )
        self.assertEqual(recorded["status"], "invalid")
        health = next(item for item in self.service.connection_health(self.owner["id"], self.workspace["id"]) if item["id"] == connection["id"])
        self.assertEqual(health["live_status"], "invalid")
        self.assertTrue(health["last_checked_at"])

    def test_viewer_cannot_access_connection_token_for_diagnostics(self):
        viewer = self.service.register("diagnostic-viewer@example.com", "diagnostic-viewer-password", "Viewer")
        self.service.add_member(self.owner["id"], self.workspace["id"], viewer["email"], "viewer")
        connection = self.service.save_facebook_connection(
            self.workspace["id"], self.owner["id"], "private-diagnostic", "Private", "encrypted-private", None, []
        )
        with self.assertRaisesRegex(ServiceError, "permission"):
            self.service.connection_token_for_diagnostics(viewer["id"], self.workspace["id"], connection["id"])

    def test_connection_used_by_post_cannot_be_deleted(self):
        connection = self.service.save_facebook_connection(
            self.workspace["id"], self.owner["id"], "used-user", "Used", "enc", None,
            [{"facebook_page_id": "used-page", "name": "Used Page", "encrypted_access_token": "enc-page"}],
        )
        page = self.service.list_facebook_pages(self.owner["id"], self.workspace["id"])[0]
        post = self.service.create_post(self.owner["id"], self.workspace["id"], page["id"], "Keep connection")
        self.assertTrue(post["id"])
        with self.assertRaisesRegex(ServiceError, "used by posts"):
            self.service.delete_facebook_connection(self.owner["id"], self.workspace["id"], connection["id"])

    def test_clear_read_notifications_keeps_unread_notifications(self):
        self.service.notify_workspace(self.workspace["id"], "token_expiring", "Reconnect Meta")
        cleared = self.service.clear_read_notifications(self.owner["id"], self.workspace["id"])
        self.assertEqual(cleared["deleted"], 0)
        self.assertEqual(len(self.service.list_notifications(self.owner["id"], self.workspace["id"])), 1)

    def test_owner_can_view_audit_logs_but_viewer_cannot(self):
        other = self.service.register("other@example.com", "another-strong-password", "Other")
        self.service.add_member(self.owner["id"], self.workspace["id"], "other@example.com", "viewer")
        logs = self.service.list_audit_logs(self.owner["id"], self.workspace["id"])
        self.assertEqual(logs[0]["action"], "workspace.member_upserted")
        self.assertEqual(logs[0]["actor_name"], "Owner")
        with self.assertRaisesRegex(ServiceError, "permission"):
            self.service.list_audit_logs(other["id"], self.workspace["id"])

class MediaLibraryTests(FacebookPageStorageTests):
    def test_registers_and_scopes_media_metadata(self):
        asset = self.service.register_media(self.owner["id"], self.workspace["id"], "rose.jpg", "/media/rose.jpg", "image/jpeg", 42)
        assets = self.service.list_media(self.owner["id"], self.workspace["id"])
        self.assertEqual(assets[0]["id"], asset["id"])
        self.assertNotIn("storage_path", assets[0])

    def test_delete_unused_media_removes_metadata(self):
        asset = self.service.register_media(self.owner["id"], self.workspace["id"], "rose.jpg", "/media/rose.jpg", "image/jpeg", 42)
        deleted = self.service.delete_media(self.owner["id"], self.workspace["id"], asset["id"])
        self.assertEqual(deleted["storage_path"], "/media/rose.jpg")
        self.assertEqual(self.service.list_media(self.owner["id"], self.workspace["id"]), [])

class PostMediaTests(FacebookPageStorageTests):
    def test_post_can_attach_own_workspace_media(self):
        media = self.service.register_media(self.owner["id"], self.workspace["id"], "rose.jpg", "/media/rose.jpg", "image/jpeg", 42)
        self.service.save_facebook_connection(self.workspace["id"], self.owner["id"], "meta-user", "Meta", "enc-user", None, [{"facebook_page_id": "p1", "name": "Garden", "encrypted_access_token": "enc-page"}])
        page = self.service.list_facebook_pages(self.owner["id"], self.workspace["id"])[0]
        post = self.service.create_post(self.owner["id"], self.workspace["id"], page["id"], "Hello", [media["id"]])
        with self.service.database.connect() as conn:
            attached = conn.execute("SELECT media_asset_id FROM post_media WHERE post_id = ?", (post["id"],)).fetchone()
        self.assertEqual(attached["media_asset_id"], media["id"])
        self.assertEqual(self.service.list_posts(self.owner["id"], self.workspace["id"])[0]["media_count"], 1)

    def test_delete_rejects_media_attached_to_post(self):
        media = self.service.register_media(self.owner["id"], self.workspace["id"], "rose.jpg", "/media/rose.jpg", "image/jpeg", 42)
        self.service.save_facebook_connection(self.workspace["id"], self.owner["id"], "meta-user", "Meta", "enc-user", None, [{"facebook_page_id": "p1", "name": "Garden", "encrypted_access_token": "enc-page"}])
        page = self.service.list_facebook_pages(self.owner["id"], self.workspace["id"])[0]
        self.service.create_post(self.owner["id"], self.workspace["id"], page["id"], "Hello", [media["id"]])
        with self.assertRaisesRegex(ServiceError, "attached"):
            self.service.delete_media(self.owner["id"], self.workspace["id"], media["id"])
