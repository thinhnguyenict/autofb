"""Media storage boundary with a safe local-volume implementation."""
from __future__ import annotations

import os
import re
import tempfile
import uuid
from contextlib import contextmanager
from pathlib import Path
from typing import BinaryIO, Iterator
from urllib.parse import urlparse


class MediaStorageError(ValueError):
    pass


WORKSPACE_KEY_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,127}$")
CONTROL_CHARACTERS = re.compile(r"[\x00-\x1f\x7f]")


def safe_workspace_key(workspace_id: str) -> str:
    if not WORKSPACE_KEY_PATTERN.fullmatch(workspace_id or ""):
        raise MediaStorageError("Workspace storage key is invalid")
    return workspace_id


def safe_media_filename(filename: str) -> str:
    candidate = (filename or "upload").replace("\\", "/").rsplit("/", 1)[-1]
    candidate = CONTROL_CHARACTERS.sub("", candidate).strip()
    if candidate in {"", ".", ".."}:
        candidate = "upload"
    if len(candidate.encode()) > 255:
        stem, suffix = os.path.splitext(candidate)
        while len(suffix.encode()) > 64:
            suffix = suffix[:-1]
        byte_budget = 255 - len(suffix.encode())
        while len(stem.encode()) > byte_budget:
            stem = stem[:-1]
        candidate = f"{stem or 'upload'}{suffix}"
    return candidate


class _LimitedWriter:
    def __init__(self, target: BinaryIO, max_bytes: int) -> None:
        self.target = target
        self.max_bytes = max_bytes
        self.size = 0

    def write(self, data: bytes) -> int:
        self.size += len(data)
        if self.size > self.max_bytes:
            raise MediaStorageError(f"Stored media exceeds the {self.max_bytes} byte download limit")
        return self.target.write(data)


class LocalMediaStorage:
    def __init__(self, root: str | Path, max_bytes: int = 100 * 1024 * 1024) -> None:
        if max_bytes < 1:
            raise ValueError("max_bytes must be positive")
        self.root = Path(root).resolve()
        self.max_bytes = max_bytes

    @classmethod
    def from_environment(cls) -> "LocalMediaStorage":
        return cls(
            os.environ.get("AUTOFB_MEDIA_DIR", "media"),
            int(os.environ.get("AUTOFB_MEDIA_MAX_BYTES", str(100 * 1024 * 1024))),
        )

    def save(
        self, workspace_id: str, filename: str, source: BinaryIO, content_type: str | None = None
    ) -> tuple[Path, str, int]:
        workspace_id = safe_workspace_key(workspace_id)
        safe_name = safe_media_filename(filename)
        directory = (self.root / workspace_id).resolve()
        if self.root not in directory.parents:
            raise MediaStorageError("Workspace storage path escapes media root")
        directory.mkdir(parents=True, exist_ok=True)
        destination = directory / f"{uuid.uuid4()}-{safe_name}"
        size = 0
        try:
            with destination.open("xb") as target:
                while chunk := source.read(1024 * 1024):
                    size += len(chunk)
                    if size > self.max_bytes:
                        raise MediaStorageError(f"Media exceeds the {self.max_bytes} byte upload limit")
                    target.write(chunk)
            if size == 0:
                raise MediaStorageError("Media file is empty")
        except Exception:
            destination.unlink(missing_ok=True)
            raise
        return destination, safe_name, size

    def delete(self, storage_path: str | Path) -> None:
        path = Path(storage_path).resolve()
        if self.root != path and self.root not in path.parents:
            raise MediaStorageError("Refusing to delete media outside configured storage")
        path.unlink(missing_ok=True)

    @contextmanager
    def open(self, storage_path: str | Path) -> Iterator[BinaryIO]:
        path = Path(storage_path).resolve()
        if self.root != path and self.root not in path.parents:
            raise MediaStorageError("Refusing to read media outside configured storage")
        with path.open("rb") as handle:
            yield handle


class S3MediaStorage:
    """S3-compatible storage using opaque object keys and bounded upload spooling."""

    def __init__(
        self,
        bucket: str,
        *,
        prefix: str = "autofb-media",
        max_bytes: int = 100 * 1024 * 1024,
        client=None,
        endpoint_url: str | None = None,
        region_name: str | None = None,
    ) -> None:
        if not bucket or "/" in bucket:
            raise ValueError("S3 bucket is required and cannot contain slashes")
        if max_bytes < 1:
            raise ValueError("max_bytes must be positive")
        self.bucket = bucket
        self.prefix = prefix.strip("/")
        if self.prefix and any(
            part in {"", ".", ".."} or CONTROL_CHARACTERS.search(part)
            for part in self.prefix.split("/")
        ):
            raise ValueError("S3 prefix contains an invalid path segment")
        self.max_bytes = max_bytes
        if client is None:
            import boto3

            client = boto3.client("s3", endpoint_url=endpoint_url, region_name=region_name)
        self.client = client

    @classmethod
    def from_environment(cls) -> "S3MediaStorage":
        return cls(
            os.environ.get("AUTOFB_S3_BUCKET", ""),
            prefix=os.environ.get("AUTOFB_S3_PREFIX", "autofb-media"),
            max_bytes=int(os.environ.get("AUTOFB_MEDIA_MAX_BYTES", str(100 * 1024 * 1024))),
            endpoint_url=os.environ.get("AUTOFB_S3_ENDPOINT_URL") or None,
            region_name=os.environ.get("AUTOFB_S3_REGION") or None,
        )

    def _key(self, workspace_id: str, filename: str) -> tuple[str, str]:
        workspace_id = safe_workspace_key(workspace_id)
        safe_name = safe_media_filename(filename)
        parts = [part for part in (self.prefix, workspace_id, f"{uuid.uuid4()}-{safe_name}") if part]
        return "/".join(parts), safe_name

    def save(
        self, workspace_id: str, filename: str, source: BinaryIO, content_type: str | None = None
    ) -> tuple[str, str, int]:
        key, safe_name = self._key(workspace_id, filename)
        size = 0
        with tempfile.SpooledTemporaryFile(max_size=8 * 1024 * 1024) as temporary:
            while chunk := source.read(1024 * 1024):
                size += len(chunk)
                if size > self.max_bytes:
                    raise MediaStorageError(f"Media exceeds the {self.max_bytes} byte upload limit")
                temporary.write(chunk)
            if size == 0:
                raise MediaStorageError("Media file is empty")
            temporary.seek(0)
            extra = {"ContentType": content_type} if content_type else None
            kwargs = {"ExtraArgs": extra} if extra else {}
            self.client.upload_fileobj(temporary, self.bucket, key, **kwargs)
        return f"s3://{self.bucket}/{key}", safe_name, size

    def _object_key(self, storage_path: str | Path) -> str:
        parsed = urlparse(str(storage_path))
        key = parsed.path.lstrip("/")
        if parsed.scheme != "s3" or parsed.netloc != self.bucket or not key:
            raise MediaStorageError("S3 media path does not belong to the configured bucket")
        if self.prefix and not key.startswith(f"{self.prefix}/"):
            raise MediaStorageError("S3 media path is outside the configured prefix")
        return key

    def delete(self, storage_path: str | Path) -> None:
        self.client.delete_object(Bucket=self.bucket, Key=self._object_key(storage_path))

    @contextmanager
    def open(self, storage_path: str | Path) -> Iterator[BinaryIO]:
        with tempfile.SpooledTemporaryFile(max_size=8 * 1024 * 1024) as temporary:
            limited = _LimitedWriter(temporary, self.max_bytes)
            self.client.download_fileobj(self.bucket, self._object_key(storage_path), limited)
            temporary.seek(0)
            yield temporary


def media_storage_from_environment() -> LocalMediaStorage | S3MediaStorage:
    backend = os.environ.get("AUTOFB_MEDIA_BACKEND", "local").strip().lower()
    if backend == "local":
        return LocalMediaStorage.from_environment()
    if backend == "s3":
        return S3MediaStorage.from_environment()
    raise MediaStorageError("AUTOFB_MEDIA_BACKEND must be local or s3")


@contextmanager
def open_stored_media(storage_path: str | Path) -> Iterator[BinaryIO]:
    storage = media_storage_from_environment()
    with storage.open(storage_path) as handle:
        yield handle
