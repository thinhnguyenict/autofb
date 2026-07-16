import tempfile
import unittest
from pathlib import Path

from autofb.web.database import Database
from autofb.web.service import AutoFBService, ServiceError


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
