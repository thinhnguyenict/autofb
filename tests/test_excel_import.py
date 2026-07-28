import tempfile
import unittest
from pathlib import Path

from autofb.web.database import Database
from autofb.web.service import AutoFBService, ServiceError
from tools.import_excel import import_rows


class ExcelImportTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.database = Database(Path(self.directory.name) / "autofb.db")
        self.database.initialize()
        self.service = AutoFBService(self.database)
        self.owner = self.service.register("importer@example.com", "importer-strong-password", "Importer")
        self.workspace = self.service.create_workspace(self.owner["id"], "Import workspace")
        self.service.save_facebook_connection(
            self.workspace["id"], self.owner["id"], "meta-import", "Meta Import", "encrypted", None,
            [{"facebook_page_id": "page-1", "name": "Page One", "encrypted_access_token": "encrypted-page"}],
        )

    def test_dry_run_validates_without_writing(self):
        result = import_rows(
            self.database,
            self.owner["email"],
            self.workspace["name"],
            [{"facebook_page_id": "page-1", "body": "Draft only"}],
            dry_run=True,
        )
        self.assertEqual(result, {"validated": 1, "created": 0, "scheduled": 0})
        self.assertEqual(self.service.list_posts(self.owner["id"], self.workspace["id"]), [])

    def test_imports_draft_and_scheduled_post(self):
        result = import_rows(
            self.database,
            self.owner["email"],
            self.workspace["name"],
            [
                {"facebook_page_id": "page-1", "body": "Draft only"},
                {"facebook_page_id": "page-1", "body": "Scheduled", "scheduled_at": "2030-06-01T10:00:00+00:00", "timezone": "UTC"},
            ],
        )
        self.assertEqual(result, {"validated": 2, "created": 2, "scheduled": 1})
        self.assertEqual({post["status"] for post in self.service.list_posts(self.owner["id"], self.workspace["id"])}, {"draft", "scheduled"})

    def test_invalid_page_rejects_all_rows_before_writing(self):
        with self.assertRaisesRegex(ServiceError, "Row 3"):
            import_rows(
                self.database,
                self.owner["email"],
                self.workspace["name"],
                [
                    {"facebook_page_id": "page-1", "body": "Would be valid"},
                    {"facebook_page_id": "missing", "body": "Invalid"},
                ],
            )
        self.assertEqual(self.service.list_posts(self.owner["id"], self.workspace["id"]), [])


if __name__ == "__main__":
    unittest.main()
