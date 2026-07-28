import tempfile
import unittest
from pathlib import Path

from tools.create_admin import create_admin
from autofb.web.database import Database
from autofb.web.service import AutoFBService


class CreateAdminToolTests(unittest.TestCase):
    def test_create_admin_is_idempotent_and_creates_workspace(self):
        with tempfile.TemporaryDirectory() as directory:
            database_path = Path(directory) / "autofb.db"
            first = create_admin(database_path, "admin@example.com", "a-very-strong-password", "Admin", "Ops")
            second = create_admin(database_path, "admin@example.com", "another-strong-password", "Admin", "Ops")
            self.assertEqual(first["user_id"], second["user_id"])
            self.assertEqual(first["workspace_id"], second["workspace_id"])
            service = AutoFBService(Database(database_path))
            workspaces = service.list_workspaces(first["user_id"])
            self.assertEqual(workspaces[0]["name"], "Ops")


if __name__ == "__main__":
    unittest.main()
