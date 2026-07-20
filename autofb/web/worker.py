"""Durable scheduled-post worker for the new workspace publishing pipeline."""
from __future__ import annotations

import json
import logging
import time
from datetime import UTC, datetime
from typing import Any, Callable


from .database import Database
from .service import now


class PublishWorker:
    MAX_ATTEMPTS = 3
    def __init__(
        self,
        database: Database,
        publisher: Callable[[str, str, str], str] | None = None,
        decryptor: Callable[[str], str] | None = None,
        media_publisher: Callable[[str, str, str, list[dict[str, str]]], str] | None = None,
    ) -> None:
        self.database = database
        self.publisher = publisher or self._publish_to_facebook
        self.decryptor = decryptor or self._configured_decryptor()
        self.media_publisher = media_publisher or self._publish_media_to_facebook

    @staticmethod
    def _configured_decryptor() -> Callable[[str], str]:
        from .oauth import MetaOAuth

        return MetaOAuth.from_environment().decrypt

    def run_once(self) -> int:
        """Claim and execute all due queued jobs; returns the number claimed."""
        claimed = self._claim_due_jobs()
        for job in claimed:
            try:
                remote_id = self._publish_job(job)
            except Exception as exc:  # Job errors are persisted and never crash the worker loop.
                retrying = self._handle_failure(job, str(exc))
                if retrying:
                    logging.info("Publish job %s failed and was requeued: %s", job["id"], exc)
                else:
                    logging.exception("Publish job %s failed permanently", job["id"])
            else:
                self._finish(job["id"], job["post_id"], "succeeded", None)
                logging.info("Publish job %s completed with remote post %s", job["id"], remote_id)
        return len(claimed)

    def run_forever(self, poll_seconds: int = 60) -> None:
        """Continuously poll for due jobs until the process is stopped."""
        if poll_seconds < 1:
            raise ValueError("poll_seconds must be at least 1")
        logging.info("Starting publish worker loop with %s second polling", poll_seconds)
        while True:
            self.run_once()
            time.sleep(poll_seconds)

    def _claim_due_jobs(self) -> list[dict[str, str]]:
        with self.database.connect() as conn:
            rows = conn.execute(
                """SELECT publish_jobs.id, publish_jobs.post_id, posts.body, facebook_pages.facebook_page_id,
                          facebook_pages.encrypted_access_token, publish_jobs.attempts
                   FROM publish_jobs JOIN posts ON posts.id = publish_jobs.post_id
                   JOIN facebook_pages ON facebook_pages.id = posts.page_id
                   WHERE publish_jobs.status = 'queued' AND publish_jobs.run_at <= ?""",
                (now(),),
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

    def _handle_failure(self, job: dict[str, str], error: str) -> bool:
        attempts = int(job["attempts"])
        if attempts < self.MAX_ATTEMPTS:
            from datetime import timedelta

            retry_at = (datetime.now(UTC) + timedelta(minutes=2 ** attempts)).isoformat()
            with self.database.connect() as conn:
                conn.execute("UPDATE publish_jobs SET status = 'queued', run_at = ?, last_error = ?, updated_at = ? WHERE id = ?", (retry_at, error, now(), job["id"]))
                conn.execute("UPDATE posts SET status = 'queued', updated_at = ? WHERE id = ?", (now(), job["post_id"]))
            return True
        self._finish(job["id"], job["post_id"], "failed", error)
        return False

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
        response.raise_for_status()
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
            with open(item["storage_path"], "rb") as handle:
                upload = requests.post(
                    f"https://graph.facebook.com/v25.0/{page_id}/photos",
                    data={"access_token": access_token, "published": "false"},
                    files={"source": (item["filename"], handle, item["content_type"])},
                    timeout=120,
                )
            upload.raise_for_status()
            upload_id = upload.json().get("id")
            if not upload_id:
                raise RuntimeError("Meta did not return an uploaded media id")
            uploaded_ids.append(str(upload_id))

        payload = {"message": body, "access_token": access_token}
        for index, media_id in enumerate(uploaded_ids):
            payload[f"attached_media[{index}]"] = json.dumps({"media_fbid": media_id})
        response = requests.post(f"https://graph.facebook.com/v25.0/{page_id}/feed", data=payload, timeout=60)
        response.raise_for_status()
        post_id = response.json().get("id")
        if not post_id:
            raise RuntimeError("Meta did not return a post id")
        return str(post_id)
