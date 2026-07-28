"""Durable scheduled-post worker for the new workspace publishing pipeline."""
from __future__ import annotations

import json
import logging
import os
import time
import uuid
from datetime import UTC, datetime, timedelta
from email.utils import parsedate_to_datetime
from typing import Any, Callable


from .database import Database
from .service import identifier, now
from .storage import open_stored_media


class ProviderRateLimitError(RuntimeError):
    def __init__(self, retry_after_seconds: int) -> None:
        self.retry_after_seconds = max(1, min(retry_after_seconds, 3600))
        super().__init__(f"Meta rate limit reached; retry after {self.retry_after_seconds} seconds")


class PublishWorker:
    MAX_ATTEMPTS = 3

    def __init__(
        self,
        database: Database,
        publisher: Callable[[str, str, str], str] | None = None,
        decryptor: Callable[[str], str] | None = None,
        media_publisher: Callable[[str, str, str, list[dict[str, str]]], str] | None = None,
        worker_id: str | None = None,
        batch_size: int | None = None,
        min_publish_interval: float | None = None,
        sleeper: Callable[[float], None] = time.sleep,
    ) -> None:
        self.database = database
        self.publisher = publisher or self._publish_to_facebook
        self.decryptor = decryptor or self._configured_decryptor()
        self.media_publisher = media_publisher or self._publish_media_to_facebook
        self.worker_id = worker_id or os.environ.get("AUTOFB_WORKER_ID") or str(uuid.uuid4())
        self.batch_size = batch_size if batch_size is not None else int(os.environ.get("AUTOFB_WORKER_BATCH_SIZE", "10"))
        if self.batch_size < 1 or self.batch_size > 100:
            raise ValueError("batch_size must be between 1 and 100")
        self.min_publish_interval = (
            min_publish_interval
            if min_publish_interval is not None
            else float(os.environ.get("AUTOFB_WORKER_MIN_PUBLISH_INTERVAL_SECONDS", "0"))
        )
        if self.min_publish_interval < 0 or self.min_publish_interval > 60:
            raise ValueError("min_publish_interval must be between 0 and 60 seconds")
        self.sleeper = sleeper
        self.started_at = now()

    @staticmethod
    def _configured_decryptor() -> Callable[[str], str]:
        encryption_key = os.environ.get("AUTOFB_TOKEN_ENCRYPTION_KEY", "")
        if not encryption_key:
            raise RuntimeError("AUTOFB_TOKEN_ENCRYPTION_KEY is required to decrypt page tokens")
        from cryptography.fernet import Fernet

        cipher = Fernet(encryption_key.encode())
        return lambda value: cipher.decrypt(value.encode()).decode()

    def run_once(self) -> int:
        """Claim and execute all due queued jobs; returns the number claimed."""
        self._heartbeat("running")
        try:
            self._requeue_stale_running_jobs()
            claimed = self._claim_due_jobs()
            for index, job in enumerate(claimed):
                if index and self.min_publish_interval:
                    self.sleeper(self.min_publish_interval)
                try:
                    remote_id = self._publish_job(job)
                except Exception as exc:  # Job errors are persisted and never crash the worker loop.
                    self._record_result(job, "failed", None, str(exc))
                    retrying = self._handle_failure(job, exc)
                    if retrying:
                        logging.info("Publish job %s failed and was requeued: %s", job["id"], exc)
                    else:
                        logging.exception("Publish job %s failed permanently", job["id"])
                else:
                    self._complete_success(job, remote_id)
                    logging.info("Publish job %s completed with remote post %s", job["id"], remote_id)
        except Exception as exc:
            self._heartbeat("error", str(exc))
            raise
        self._heartbeat("idle")
        return len(claimed)

    def _heartbeat(self, status: str, error: str | None = None) -> None:
        with self.database.connect() as conn:
            conn.execute(
                """INSERT INTO worker_heartbeats(worker_id, status, last_error, last_seen_at, started_at)
                   VALUES (?, ?, ?, ?, ?)
                   ON CONFLICT(worker_id) DO UPDATE SET status = excluded.status,
                       last_error = excluded.last_error, last_seen_at = excluded.last_seen_at""",
                (self.worker_id, status, error[:1000] if error else None, now(), self.started_at),
            )

    def run_forever(self, poll_seconds: int = 60) -> None:
        """Continuously poll for due jobs until the process is stopped."""
        if poll_seconds < 1:
            raise ValueError("poll_seconds must be at least 1")
        logging.info("Starting publish worker loop with %s second polling", poll_seconds)
        while True:
            self.run_once()
            time.sleep(poll_seconds)

    def _requeue_stale_running_jobs(self, max_age_minutes: int = 15) -> int:
        cutoff = (datetime.now(UTC) - timedelta(minutes=max_age_minutes)).isoformat()
        timestamp = now()
        with self.database.connect() as conn:
            stale = conn.execute(
                """SELECT publish_jobs.id, publish_jobs.post_id,
                          (SELECT remote_post_id FROM publish_results
                           WHERE publish_results.job_id = publish_jobs.id
                             AND publish_results.status = 'succeeded'
                           ORDER BY publish_results.created_at DESC LIMIT 1) AS remote_post_id
                   FROM publish_jobs
                   WHERE publish_jobs.status = 'running' AND publish_jobs.updated_at <= ?""",
                (cutoff,),
            ).fetchall()
            for job in stale:
                if job["remote_post_id"]:
                    conn.execute(
                        "UPDATE publish_jobs SET status = 'succeeded', last_error = NULL, updated_at = ? WHERE id = ?",
                        (timestamp, job["id"]),
                    )
                    conn.execute("UPDATE posts SET status = 'published', updated_at = ? WHERE id = ?", (timestamp, job["post_id"]))
                    continue
                conn.execute(
                    "UPDATE publish_jobs SET status = 'queued', last_error = ?, updated_at = ? WHERE id = ?",
                    ("Recovered stale running job", timestamp, job["id"]),
                )
                conn.execute("UPDATE posts SET status = 'queued', updated_at = ? WHERE id = ?", (timestamp, job["post_id"]))
        return len(stale)

    def _claim_due_jobs(self) -> list[dict[str, str]]:
        with self.database.connect() as conn:
            rows = conn.execute(
                """SELECT publish_jobs.id, publish_jobs.post_id, posts.body, facebook_pages.facebook_page_id,
                          facebook_pages.encrypted_access_token, publish_jobs.attempts
                   FROM publish_jobs JOIN posts ON posts.id = publish_jobs.post_id
                   JOIN facebook_pages ON facebook_pages.id = posts.page_id
                   WHERE publish_jobs.status = 'queued' AND publish_jobs.run_at <= ?
                   ORDER BY publish_jobs.run_at, publish_jobs.created_at
                   LIMIT ?""",
                (now(), self.batch_size),
            ).fetchall()
            claimed = []
            for row in rows:
                updated = conn.execute(
                    "UPDATE publish_jobs SET status = 'running', attempts = attempts + 1, updated_at = ? WHERE id = ? AND status = 'queued'",
                    (now(), row["id"]),
                ).rowcount
                if updated:
                    item = dict(row)
                    item["access_token"] = self.decryptor(item.pop("encrypted_access_token"))
                    media = conn.execute(
                        """SELECT media_assets.id, media_assets.filename, media_assets.storage_path, media_assets.content_type
                           FROM post_media JOIN media_assets ON media_assets.id = post_media.media_asset_id
                           WHERE post_media.post_id = ? ORDER BY post_media.sort_order""",
                        (item["post_id"],),
                    ).fetchall()
                    item["media"] = [dict(asset) for asset in media]
                    claimed.append(item)
            return claimed

    def _publish_job(self, job: dict[str, Any]) -> str:
        media = job.get("media") or []
        if media:
            return self.media_publisher(job["facebook_page_id"], job["access_token"], job["body"], media)
        return self.publisher(job["facebook_page_id"], job["access_token"], job["body"])

    def _handle_failure(self, job: dict[str, str], failure: Exception) -> bool:
        attempts = int(job["attempts"])
        error = str(failure)
        if attempts < self.MAX_ATTEMPTS:
            if isinstance(failure, ProviderRateLimitError):
                delay = timedelta(seconds=failure.retry_after_seconds)
            else:
                delay = timedelta(minutes=2 ** attempts)
            retry_at = (datetime.now(UTC) + delay).isoformat()
            with self.database.connect() as conn:
                conn.execute("UPDATE publish_jobs SET status = 'queued', run_at = ?, last_error = ?, updated_at = ? WHERE id = ?", (retry_at, error, now(), job["id"]))
                conn.execute("UPDATE posts SET status = 'queued', updated_at = ? WHERE id = ?", (now(), job["post_id"]))
            return True
        self._finish(job["id"], job["post_id"], "failed", error)
        return False

    def _record_result(self, job: dict[str, Any], status: str, remote_id: str | None, error: str | None) -> None:
        attempt_number = int(job["attempts"]) + 1
        with self.database.connect() as conn:
            conn.execute(
                "INSERT INTO publish_results(id, job_id, post_id, status, attempt, remote_post_id, error, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (identifier(), job["id"], job["post_id"], status, attempt_number, remote_id, error, now()),
            )

    def _complete_success(self, job: dict[str, Any], remote_id: str) -> None:
        """Persist the result and terminal states in one transaction."""
        timestamp = now()
        attempt_number = int(job["attempts"]) + 1
        with self.database.connect() as conn:
            conn.execute(
                "INSERT INTO publish_results(id, job_id, post_id, status, attempt, remote_post_id, error, created_at) VALUES (?, ?, ?, 'succeeded', ?, ?, NULL, ?)",
                (identifier(), job["id"], job["post_id"], attempt_number, remote_id, timestamp),
            )
            conn.execute(
                "UPDATE publish_jobs SET status = 'succeeded', last_error = NULL, updated_at = ? WHERE id = ?",
                (timestamp, job["id"]),
            )
            conn.execute("UPDATE posts SET status = 'published', updated_at = ? WHERE id = ?", (timestamp, job["post_id"]))

    def _finish(self, job_id: str, post_id: str, status: str, error: str | None) -> None:
        post_status = "published" if status == "succeeded" else "failed"
        with self.database.connect() as conn:
            conn.execute("UPDATE publish_jobs SET status = ?, last_error = ?, updated_at = ? WHERE id = ?", (status, error, now(), job_id))
            conn.execute("UPDATE posts SET status = ?, updated_at = ? WHERE id = ?", (post_status, now(), post_id))

    @staticmethod
    def _publish_to_facebook(page_id: str, access_token: str, body: str) -> str:
        import requests

        response = requests.post(
            f"https://graph.facebook.com/v25.0/{page_id}/feed",
            data={"message": body, "access_token": access_token},
            timeout=60,
        )
        PublishWorker._raise_for_status(response)
        data = response.json()
        post_id = data.get("id")
        if not post_id:
            raise RuntimeError("Meta did not return a post id")
        return str(post_id)

    @staticmethod
    def _publish_media_to_facebook(page_id: str, access_token: str, body: str, media: list[dict[str, str]]) -> str:
        if any(not item["content_type"].startswith("image/") for item in media):
            raise RuntimeError("Only image attachments are supported by the scheduled feed worker")

        import requests

        uploaded_ids = []
        for item in media:
            with open_stored_media(item["storage_path"]) as handle:
                upload = requests.post(
                    f"https://graph.facebook.com/v25.0/{page_id}/photos",
                    data={"access_token": access_token, "published": "false"},
                    files={"source": (item["filename"], handle, item["content_type"])},
                    timeout=120,
                )
            PublishWorker._raise_for_status(upload)
            upload_id = upload.json().get("id")
            if not upload_id:
                raise RuntimeError("Meta did not return an uploaded media id")
            uploaded_ids.append(str(upload_id))

        payload = {"message": body, "access_token": access_token}
        for index, media_id in enumerate(uploaded_ids):
            payload[f"attached_media[{index}]"] = json.dumps({"media_fbid": media_id})
        response = requests.post(f"https://graph.facebook.com/v25.0/{page_id}/feed", data=payload, timeout=60)
        PublishWorker._raise_for_status(response)
        post_id = response.json().get("id")
        if not post_id:
            raise RuntimeError("Meta did not return a post id")
        return str(post_id)

    @staticmethod
    def _raise_for_status(response: Any) -> None:
        if response.status_code == 429:
            raise ProviderRateLimitError(
                PublishWorker._retry_after_seconds(response.headers.get("Retry-After"))
            )
        response.raise_for_status()

    @staticmethod
    def _retry_after_seconds(value: str | None, current_time: datetime | None = None) -> int:
        """Parse Retry-After delta-seconds or an RFC 7231 HTTP-date."""
        if value is None:
            return 60
        try:
            return max(1, int(value.strip()))
        except (TypeError, ValueError):
            pass
        try:
            retry_at = parsedate_to_datetime(value)
            if retry_at.tzinfo is None:
                retry_at = retry_at.replace(tzinfo=UTC)
            seconds = int((retry_at - (current_time or datetime.now(UTC))).total_seconds())
            return max(1, seconds)
        except (TypeError, ValueError, OverflowError):
            return 60
