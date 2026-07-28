import io
import tempfile
import unittest
from pathlib import Path

from autofb.web.storage import (
    LocalMediaStorage,
    MediaStorageError,
    S3MediaStorage,
    safe_media_filename,
)


class FakeS3Client:
    def __init__(self):
        self.objects = {}
        self.upload_extra = None

    def upload_fileobj(self, source, bucket, key, **kwargs):
        self.objects[(bucket, key)] = source.read()
        self.upload_extra = kwargs

    def download_fileobj(self, bucket, key, target):
        target.write(self.objects[(bucket, key)])

    def delete_object(self, *, Bucket, Key):
        self.objects.pop((Bucket, Key), None)


class LocalMediaStorageTests(unittest.TestCase):
    def test_saves_sanitized_filename_and_deletes_file(self):
        with tempfile.TemporaryDirectory() as directory:
            storage = LocalMediaStorage(directory, max_bytes=20)
            path, filename, size = storage.save("workspace-1", "../../photo.jpg", io.BytesIO(b"image-data"))
            self.assertEqual(filename, "photo.jpg")
            self.assertEqual(size, 10)
            self.assertEqual(path.read_bytes(), b"image-data")
            self.assertEqual(path.parent, Path(directory).resolve() / "workspace-1")
            storage.delete(path)
            self.assertFalse(path.exists())

    def test_oversized_upload_is_removed(self):
        with tempfile.TemporaryDirectory() as directory:
            storage = LocalMediaStorage(directory, max_bytes=4)
            with self.assertRaisesRegex(MediaStorageError, "upload limit"):
                storage.save("workspace-1", "large.jpg", io.BytesIO(b"12345"))
            self.assertEqual(list(Path(directory).rglob("*.*")), [])

    def test_rejects_workspace_traversal_and_external_delete(self):
        with tempfile.TemporaryDirectory() as directory:
            storage = LocalMediaStorage(Path(directory) / "media")
            with self.assertRaisesRegex(MediaStorageError, "key is invalid"):
                storage.save("../outside", "photo.jpg", io.BytesIO(b"image"))
            outside = Path(directory) / "outside.jpg"
            outside.write_bytes(b"keep")
            with self.assertRaisesRegex(MediaStorageError, "outside configured"):
                storage.delete(outside)
            self.assertTrue(outside.exists())

    def test_sanitizes_windows_paths_control_characters_and_long_names(self):
        self.assertEqual(safe_media_filename(r"C:\temp\photo.jpg"), "photo.jpg")
        self.assertEqual(safe_media_filename("bad\r\nname.png"), "badname.png")
        shortened = safe_media_filename(f"{'a' * 300}.jpg")
        self.assertLessEqual(len(shortened.encode()), 255)
        self.assertTrue(shortened.endswith(".jpg"))
        self.assertLessEqual(len(safe_media_filename(f"{'ảnh' * 200}.png").encode()), 255)

    def test_rejects_non_canonical_workspace_storage_keys(self):
        with tempfile.TemporaryDirectory() as directory:
            storage = LocalMediaStorage(directory)
            for workspace_id in ("../outside", "bad key", "line\nbreak", "a" * 129):
                with self.subTest(workspace_id=workspace_id):
                    with self.assertRaisesRegex(MediaStorageError, "key is invalid"):
                        storage.save(workspace_id, "photo.jpg", io.BytesIO(b"image"))


class S3MediaStorageTests(unittest.TestCase):
    def test_upload_open_and_delete_object(self):
        client = FakeS3Client()
        storage = S3MediaStorage("media-bucket", prefix="tenant-media", max_bytes=20, client=client)

        path, filename, size = storage.save(
            "workspace-1", "../../photo.jpg", io.BytesIO(b"image-data"), "image/jpeg"
        )

        self.assertTrue(path.startswith("s3://media-bucket/tenant-media/workspace-1/"))
        self.assertTrue(path.endswith("-photo.jpg"))
        self.assertEqual(filename, "photo.jpg")
        self.assertEqual(size, 10)
        self.assertEqual(client.upload_extra, {"ExtraArgs": {"ContentType": "image/jpeg"}})
        with storage.open(path) as handle:
            self.assertEqual(handle.read(), b"image-data")
        storage.delete(path)
        self.assertEqual(client.objects, {})

    def test_rejects_oversized_upload_and_foreign_paths(self):
        client = FakeS3Client()
        storage = S3MediaStorage("media-bucket", prefix="tenant-media", max_bytes=4, client=client)
        with self.assertRaisesRegex(MediaStorageError, "upload limit"):
            storage.save("workspace-1", "large.jpg", io.BytesIO(b"12345"))
        self.assertEqual(client.objects, {})
        with self.assertRaisesRegex(MediaStorageError, "configured bucket"):
            storage.delete("s3://other-bucket/tenant-media/workspace-1/photo.jpg")
        with self.assertRaisesRegex(MediaStorageError, "configured prefix"):
            storage.delete("s3://media-bucket/outside/photo.jpg")

    def test_download_reapplies_size_limit(self):
        client = FakeS3Client()
        storage = S3MediaStorage("media-bucket", prefix="tenant-media", max_bytes=4, client=client)
        path = "s3://media-bucket/tenant-media/workspace-1/external.jpg"
        client.objects[("media-bucket", "tenant-media/workspace-1/external.jpg")] = b"12345"
        with self.assertRaisesRegex(MediaStorageError, "download limit"):
            with storage.open(path):
                pass

    def test_rejects_ambiguous_s3_prefix_segments(self):
        for prefix in ("../media", "media/../private", "media\n/private"):
            with self.subTest(prefix=prefix):
                with self.assertRaisesRegex(ValueError, "prefix"):
                    S3MediaStorage("media-bucket", prefix=prefix, client=FakeS3Client())


if __name__ == "__main__":
    unittest.main()
