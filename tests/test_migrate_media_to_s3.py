import io
import tempfile
import unittest
from pathlib import Path

from autofb.web.database import Database
from autofb.web.storage import LocalMediaStorage
from tools.migrate_media_to_s3 import MediaMigrationError, migrate_media


class ObjectStorage:
    def __init__(self):
        self.objects = {}
        self.deleted = []

    def save(self, workspace_id, filename, source, content_type=None):
        path = f"s3://media/{workspace_id}/{filename}"
        self.objects[path] = source.read()
        return path, filename, len(self.objects[path])

    def delete(self, path):
        self.deleted.append(path)
        self.objects.pop(path, None)


class MediaMigrationTests(unittest.TestCase):
    def fixture(self, directory):
        root = Path(directory)
        database = Database(root / "autofb.db")
        database.initialize()
        local = LocalMediaStorage(root / "media")
        path, filename, size = local.save("workspace-1", "photo.jpg", io.BytesIO(b"image"), "image/jpeg")
        with database.connect() as connection:
            connection.execute("INSERT INTO users VALUES ('user-1', 'owner@example.com', 'hash', 'Owner', 'now')")
            connection.execute("INSERT INTO workspaces VALUES ('workspace-1', 'Workspace', 'user-1', 'now')")
            connection.execute(
                "INSERT INTO media_assets VALUES ('media-1', 'workspace-1', ?, ?, 'image/jpeg', ?, 'user-1', 'now')",
                (filename, str(path), size),
            )
        return database, local, path

    def test_migrates_database_path_and_optionally_deletes_local_file(self):
        with tempfile.TemporaryDirectory() as directory:
            database, local, old_path = self.fixture(directory)
            objects = ObjectStorage()
            report = migrate_media(database, local, objects, delete_local=True)
            with database.connect() as connection:
                storage_path = connection.execute("SELECT storage_path FROM media_assets").fetchone()[0]
            self.assertEqual(storage_path, "s3://media/workspace-1/photo.jpg")
            self.assertEqual(objects.objects[storage_path], b"image")
            self.assertFalse(old_path.exists())
            self.assertEqual(report, {"examined": 1, "migrated": 1, "skipped": 0, "local_deleted": 1})

    def test_dry_run_validates_without_uploading_or_updating(self):
        with tempfile.TemporaryDirectory() as directory:
            database, local, old_path = self.fixture(directory)
            objects = ObjectStorage()
            report = migrate_media(database, local, objects, dry_run=True, delete_local=True)
            with database.connect() as connection:
                storage_path = connection.execute("SELECT storage_path FROM media_assets").fetchone()[0]
            self.assertEqual(storage_path, str(old_path))
            self.assertTrue(old_path.exists())
            self.assertEqual(objects.objects, {})
            self.assertEqual(report, {"examined": 1, "migrated": 0, "skipped": 1, "local_deleted": 0})

    def test_concurrent_database_change_removes_new_object(self):
        with tempfile.TemporaryDirectory() as directory:
            database, local, old_path = self.fixture(directory)

            class ConcurrentStorage(ObjectStorage):
                def save(self, workspace_id, filename, source, content_type=None):
                    result = super().save(workspace_id, filename, source, content_type)
                    with database.connect() as connection:
                        connection.execute(
                            "UPDATE media_assets SET storage_path = 'changed-elsewhere' WHERE id = 'media-1'"
                        )
                    return result

            objects = ConcurrentStorage()
            with self.assertRaisesRegex(MediaMigrationError, "changed during"):
                migrate_media(database, local, objects)
            self.assertEqual(objects.objects, {})
            self.assertEqual(objects.deleted, ["s3://media/workspace-1/photo.jpg"])
            self.assertTrue(old_path.exists())


if __name__ == "__main__":
    unittest.main()
