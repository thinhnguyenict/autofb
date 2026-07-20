from __future__ import annotations

import sqlite3
import uuid
import secrets
from hashlib import sha256
from datetime import UTC, datetime, timedelta
from typing import Any

from .database import Database
from .security import hash_password, new_session_token, token_digest, verify_password

ROLES = frozenset({"owner", "admin", "editor", "publisher", "viewer"})
MANAGE_MEMBERS = frozenset({"owner", "admin"})


class ServiceError(ValueError):
    pass


def now() -> str:
    return datetime.now(UTC).isoformat()


def identifier() -> str:
    return str(uuid.uuid4())


class AutoFBService:
    def __init__(self, database: Database) -> None:
        self.database = database

    def register(self, email: str, password: str, display_name: str) -> dict[str, str]:
        email = email.strip().lower()
        display_name = display_name.strip()
        if not email or "@" not in email:
            raise ServiceError("A valid email address is required")
        if not display_name:
            raise ServiceError("Display name is required")
        try:
            password_hash = hash_password(password)
        except ValueError as exc:
            raise ServiceError(str(exc)) from exc
        user = {"id": identifier(), "email": email, "display_name": display_name, "created_at": now()}
        try:
            with self.database.connect() as conn:
                conn.execute(
                    "INSERT INTO users(id, email, password_hash, display_name, created_at) VALUES (?, ?, ?, ?, ?)",
                    (user["id"], email, password_hash, display_name, user["created_at"]),
                )
        except sqlite3.IntegrityError as exc:
            raise ServiceError("Email is already registered") from exc
        return user

    def login(self, email: str, password: str) -> str:
        with self.database.connect() as conn:
            user = conn.execute("SELECT id, password_hash FROM users WHERE email = ?", (email.strip().lower(),)).fetchone()
            if user is None or not verify_password(password, user["password_hash"]):
                raise ServiceError("Invalid email or password")
            token = new_session_token()
            expires_at = (datetime.now(UTC) + timedelta(days=7)).isoformat()
            conn.execute(
                "INSERT INTO sessions(token_hash, user_id, expires_at, created_at) VALUES (?, ?, ?, ?)",
                (token_digest(token), user["id"], expires_at, now()),
            )
        return token

    def logout(self, token: str) -> None:
        with self.database.connect() as conn:
            conn.execute("DELETE FROM sessions WHERE token_hash = ?", (token_digest(token),))

    def user_for_token(self, token: str) -> dict[str, str] | None:
        with self.database.connect() as conn:
            row = conn.execute(
                """SELECT users.id, users.email, users.display_name, users.created_at
                   FROM sessions JOIN users ON users.id = sessions.user_id
                   WHERE sessions.token_hash = ? AND sessions.expires_at > ?""",
                (token_digest(token), now()),
            ).fetchone()
        return dict(row) if row else None

    def create_workspace(self, actor_id: str, name: str) -> dict[str, str]:
        name = name.strip()
        if not name:
            raise ServiceError("Workspace name is required")
        workspace = {"id": identifier(), "name": name, "owner_id": actor_id, "created_at": now(), "role": "owner"}
        with self.database.connect() as conn:
            conn.execute("INSERT INTO workspaces(id, name, owner_id, created_at) VALUES (?, ?, ?, ?)",
                         (workspace["id"], name, actor_id, workspace["created_at"]))
            conn.execute("INSERT INTO workspace_members(workspace_id, user_id, role, created_at) VALUES (?, ?, ?, ?)",
                         (workspace["id"], actor_id, "owner", workspace["created_at"]))
            self._audit(conn, workspace["id"], actor_id, "workspace.created", "workspace", workspace["id"])
        return workspace

    def list_workspaces(self, user_id: str) -> list[dict[str, str]]:
        with self.database.connect() as conn:
            rows = conn.execute(
                """SELECT workspaces.id, workspaces.name, workspaces.owner_id, workspaces.created_at, workspace_members.role
                   FROM workspace_members JOIN workspaces ON workspaces.id = workspace_members.workspace_id
                   WHERE workspace_members.user_id = ? ORDER BY workspaces.created_at""", (user_id,)
            ).fetchall()
        return [dict(row) for row in rows]

    def add_member(self, actor_id: str, workspace_id: str, email: str, role: str) -> dict[str, str]:
        if role not in ROLES or role == "owner":
            raise ServiceError("Role must be admin, editor, publisher, or viewer")
        with self.database.connect() as conn:
            self._require_role(conn, actor_id, workspace_id, MANAGE_MEMBERS)
            user = conn.execute("SELECT id, email, display_name FROM users WHERE email = ?", (email.strip().lower(),)).fetchone()
            if user is None:
                raise ServiceError("User must register before being added to a workspace")
            conn.execute(
                "INSERT INTO workspace_members(workspace_id, user_id, role, created_at) VALUES (?, ?, ?, ?) "
                "ON CONFLICT(workspace_id, user_id) DO UPDATE SET role = excluded.role",
                (workspace_id, user["id"], role, now()),
            )
            self._audit(conn, workspace_id, actor_id, "workspace.member_upserted", "user", user["id"])
            return {"id": user["id"], "email": user["email"], "display_name": user["display_name"], "role": role}

    def list_members(self, actor_id: str, workspace_id: str) -> list[dict[str, str]]:
        with self.database.connect() as conn:
            self._require_role(conn, actor_id, workspace_id, ROLES)
            rows = conn.execute(
                """SELECT users.id, users.email, users.display_name, workspace_members.role, workspace_members.created_at
                   FROM workspace_members JOIN users ON users.id = workspace_members.user_id
                   WHERE workspace_members.workspace_id = ?
                   ORDER BY CASE workspace_members.role
                       WHEN 'owner' THEN 0 WHEN 'admin' THEN 1 WHEN 'publisher' THEN 2
                       WHEN 'editor' THEN 3 ELSE 4 END, users.email""",
                (workspace_id,),
            ).fetchall()
        return [dict(row) for row in rows]


    def create_oauth_state(self, actor_id: str, workspace_id: str) -> str:
        with self.database.connect() as conn:
            self._require_role(conn, actor_id, workspace_id, MANAGE_MEMBERS)
            state = secrets.token_urlsafe(32)
            conn.execute("DELETE FROM oauth_states WHERE expires_at <= ?", (now(),))
            conn.execute(
                "INSERT INTO oauth_states(state_hash, workspace_id, actor_id, expires_at, created_at) VALUES (?, ?, ?, ?, ?)",
                (sha256(state.encode()).hexdigest(), workspace_id, actor_id, (datetime.now(UTC) + timedelta(minutes=10)).isoformat(), now()),
            )
            return state

    def consume_oauth_state(self, state: str) -> dict[str, str]:
        with self.database.connect() as conn:
            row = conn.execute("SELECT workspace_id, actor_id, expires_at FROM oauth_states WHERE state_hash = ?", (sha256(state.encode()).hexdigest(),)).fetchone()
            conn.execute("DELETE FROM oauth_states WHERE state_hash = ?", (sha256(state.encode()).hexdigest(),))
            if row is None or row["expires_at"] <= now():
                raise ServiceError("OAuth state is invalid or expired")
            return {"workspace_id": row["workspace_id"], "actor_id": row["actor_id"]}

    def save_facebook_connection(self, workspace_id: str, actor_id: str, provider_user_id: str, display_name: str, encrypted_access_token: str, expires_at: str | None, pages: list[dict[str, str]]) -> dict[str, str]:
        if not provider_user_id:
            raise ServiceError("Meta did not return a user identity")
        with self.database.connect() as conn:
            connection = conn.execute("SELECT id FROM oauth_connections WHERE workspace_id = ? AND provider_user_id = ?", (workspace_id, provider_user_id)).fetchone()
            connection_id = connection["id"] if connection else identifier()
            conn.execute(
                "INSERT INTO oauth_connections(id, workspace_id, provider_user_id, display_name, encrypted_access_token, expires_at, created_at) VALUES (?, ?, ?, ?, ?, ?, ?) "
                "ON CONFLICT(workspace_id, provider_user_id) DO UPDATE SET display_name = excluded.display_name, encrypted_access_token = excluded.encrypted_access_token, expires_at = excluded.expires_at",
                (connection_id, workspace_id, provider_user_id, display_name, encrypted_access_token, expires_at, now()),
            )
            for page in pages:
                conn.execute(
                    "INSERT INTO facebook_pages(id, workspace_id, connection_id, facebook_page_id, name, encrypted_access_token, created_at) VALUES (?, ?, ?, ?, ?, ?, ?) "
                    "ON CONFLICT(workspace_id, facebook_page_id) DO UPDATE SET connection_id = excluded.connection_id, name = excluded.name, encrypted_access_token = excluded.encrypted_access_token",
                    (identifier(), workspace_id, connection_id, page["facebook_page_id"], page["name"], page["encrypted_access_token"], now()),
                )
            self._audit(conn, workspace_id, actor_id, "facebook.connection_saved", "oauth_connection", connection_id)
        return {"id": connection_id, "display_name": display_name, "pages_imported": str(len(pages))}

    def list_facebook_pages(self, actor_id: str, workspace_id: str) -> list[dict[str, str]]:
        with self.database.connect() as conn:
            self._require_role(conn, actor_id, workspace_id, ROLES)
            rows = conn.execute("SELECT id, facebook_page_id, name, connection_id, created_at FROM facebook_pages WHERE workspace_id = ? ORDER BY name", (workspace_id,)).fetchall()
        return [dict(row) for row in rows]




    def register_media(self, actor_id: str, workspace_id: str, filename: str, storage_path: str, content_type: str, size_bytes: int) -> dict[str, str]:
        if not filename or size_bytes < 1:
            raise ServiceError("A non-empty media file is required")
        with self.database.connect() as conn:
            self._require_role(conn, actor_id, workspace_id, frozenset({"owner", "admin", "editor", "publisher"}))
            media = {"id": identifier(), "workspace_id": workspace_id, "filename": filename, "storage_path": storage_path, "content_type": content_type, "size_bytes": str(size_bytes), "created_at": now()}
            conn.execute("INSERT INTO media_assets(id, workspace_id, filename, storage_path, content_type, size_bytes, created_by, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)", (media["id"], workspace_id, filename, storage_path, content_type, size_bytes, actor_id, media["created_at"]))
            self._audit(conn, workspace_id, actor_id, "media.uploaded", "media_asset", media["id"])
        return media

    def list_media(self, actor_id: str, workspace_id: str) -> list[dict[str, str]]:
        with self.database.connect() as conn:
            self._require_role(conn, actor_id, workspace_id, ROLES)
            rows = conn.execute("SELECT id, filename, content_type, size_bytes, created_at FROM media_assets WHERE workspace_id = ? ORDER BY created_at DESC", (workspace_id,)).fetchall()
        return [dict(row) for row in rows]

    def connection_health(self, actor_id: str, workspace_id: str) -> list[dict[str, str]]:
        with self.database.connect() as conn:
            self._require_role(conn, actor_id, workspace_id, ROLES)
            rows = conn.execute("SELECT id, display_name, expires_at, created_at FROM oauth_connections WHERE workspace_id = ? ORDER BY created_at DESC", (workspace_id,)).fetchall()
        return [dict(row) for row in rows]

    def list_notifications(self, actor_id: str, workspace_id: str) -> list[dict[str, str]]:
        with self.database.connect() as conn:
            self._require_role(conn, actor_id, workspace_id, ROLES)
            rows = conn.execute("SELECT id, type, message, read_at, created_at FROM notifications WHERE workspace_id = ? AND user_id = ? ORDER BY created_at DESC", (workspace_id, actor_id)).fetchall()
        return [dict(row) for row in rows]

    def mark_notifications_read(self, actor_id: str, workspace_id: str) -> dict[str, int]:
        with self.database.connect() as conn:
            self._require_role(conn, actor_id, workspace_id, ROLES)
            updated = conn.execute(
                "UPDATE notifications SET read_at = ? WHERE workspace_id = ? AND user_id = ? AND read_at IS NULL",
                (now(), workspace_id, actor_id),
            ).rowcount
        return {"updated": updated}

    def list_audit_logs(self, actor_id: str, workspace_id: str, limit: int = 25) -> list[dict[str, str]]:
        with self.database.connect() as conn:
            self._require_role(conn, actor_id, workspace_id, frozenset({"owner", "admin"}))
            rows = conn.execute(
                """SELECT audit_logs.id, audit_logs.action, audit_logs.entity_type, audit_logs.entity_id,
                          audit_logs.created_at, users.display_name AS actor_name
                   FROM audit_logs LEFT JOIN users ON users.id = audit_logs.actor_id
                   WHERE audit_logs.workspace_id = ?
                   ORDER BY audit_logs.created_at DESC
                   LIMIT ?""",
                (workspace_id, limit),
            ).fetchall()
        return [dict(row) for row in rows]

    def notify_workspace(self, workspace_id: str, kind: str, message: str) -> None:
        with self.database.connect() as conn:
            members = conn.execute("SELECT user_id FROM workspace_members WHERE workspace_id = ?", (workspace_id,)).fetchall()
            for member in members:
                conn.execute("INSERT INTO notifications(id, workspace_id, user_id, type, message, created_at) VALUES (?, ?, ?, ?, ?, ?)", (identifier(), workspace_id, member["user_id"], kind, message, now()))

    def create_post(self, actor_id: str, workspace_id: str, page_id: str, body: str, media_ids: list[str] | None = None) -> dict[str, str]:
    def create_post(self, actor_id: str, workspace_id: str, page_id: str, body: str) -> dict[str, str]:
        body = body.strip()
        if not body:
            raise ServiceError("Post body is required")
        with self.database.connect() as conn:
            self._require_role(conn, actor_id, workspace_id, frozenset({"owner", "admin", "editor", "publisher"}))
            page = conn.execute("SELECT id FROM facebook_pages WHERE id = ? AND workspace_id = ?", (page_id, workspace_id)).fetchone()
            if page is None:
                raise ServiceError("Page does not belong to this workspace")
            timestamp = now(); post = {"id": identifier(), "workspace_id": workspace_id, "page_id": page_id, "body": body, "status": "draft", "created_at": timestamp, "updated_at": timestamp}
            conn.execute("INSERT INTO posts(id, workspace_id, page_id, body, status, created_by, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)", (post["id"], workspace_id, page_id, body, "draft", actor_id, timestamp, timestamp))
            for sort_order, media_id in enumerate(media_ids or []):
                media = conn.execute("SELECT id FROM media_assets WHERE id = ? AND workspace_id = ?", (media_id, workspace_id)).fetchone()
                if media is None:
                    raise ServiceError("Media does not belong to this workspace")
                conn.execute("INSERT INTO post_media(post_id, media_asset_id, sort_order) VALUES (?, ?, ?)", (post["id"], media_id, sort_order))
            self._audit(conn, workspace_id, actor_id, "post.created", "post", post["id"])
        return post

    def schedule_post(self, actor_id: str, workspace_id: str, post_id: str, scheduled_at: str, timezone: str) -> dict[str, str]:
        try:
            run_at = datetime.fromisoformat(scheduled_at.replace("Z", "+00:00"))
        except ValueError as exc:
            raise ServiceError("scheduled_at must be ISO-8601") from exc
        if run_at.tzinfo is None or run_at <= datetime.now(UTC):
            raise ServiceError("scheduled_at must be a future timezone-aware time")
        with self.database.connect() as conn:
            self._require_role(conn, actor_id, workspace_id, frozenset({"owner", "admin", "editor", "publisher"}))
            post = conn.execute("SELECT id FROM posts WHERE id = ? AND workspace_id = ?", (post_id, workspace_id)).fetchone()
            if post is None:
                raise ServiceError("Post does not belong to this workspace")
            timestamp = now(); schedule_id = identifier(); job_id = identifier()
            conn.execute("INSERT INTO schedules(id, post_id, scheduled_at, timezone, created_at) VALUES (?, ?, ?, ?, ?) ON CONFLICT(post_id) DO UPDATE SET scheduled_at = excluded.scheduled_at, timezone = excluded.timezone", (schedule_id, post_id, scheduled_at, timezone, timestamp))
            conn.execute("UPDATE posts SET status = 'scheduled', updated_at = ? WHERE id = ?", (timestamp, post_id))
            conn.execute("INSERT INTO publish_jobs(id, post_id, status, run_at, attempts, created_at, updated_at) VALUES (?, ?, 'queued', ?, 0, ?, ?)", (job_id, post_id, scheduled_at, timestamp, timestamp))
            self._audit(conn, workspace_id, actor_id, "post.scheduled", "post", post_id)
        return {"id": schedule_id, "post_id": post_id, "scheduled_at": scheduled_at, "timezone": timezone, "job_id": job_id}

    def list_posts(self, actor_id: str, workspace_id: str) -> list[dict[str, str]]:
        with self.database.connect() as conn:
            self._require_role(conn, actor_id, workspace_id, ROLES)
            rows = conn.execute("SELECT posts.id, posts.page_id, posts.body, posts.status, posts.created_at, schedules.scheduled_at, schedules.timezone, COUNT(post_media.media_asset_id) AS media_count FROM posts LEFT JOIN schedules ON schedules.post_id = posts.id LEFT JOIN post_media ON post_media.post_id = posts.id WHERE posts.workspace_id = ? GROUP BY posts.id, schedules.scheduled_at, schedules.timezone ORDER BY COALESCE(schedules.scheduled_at, posts.created_at)", (workspace_id,)).fetchall()
        return [dict(row) for row in rows]

    def list_publish_jobs(self, actor_id: str, workspace_id: str) -> list[dict[str, str]]:
        with self.database.connect() as conn:
            self._require_role(conn, actor_id, workspace_id, frozenset({"owner", "admin", "publisher"}))
            rows = conn.execute(
                """SELECT publish_jobs.id, publish_jobs.post_id, publish_jobs.status, publish_jobs.run_at,
                          publish_jobs.attempts, publish_jobs.last_error, publish_jobs.updated_at,
                          posts.body, facebook_pages.name AS page_name
                   FROM publish_jobs JOIN posts ON posts.id = publish_jobs.post_id
                   JOIN facebook_pages ON facebook_pages.id = posts.page_id
                   WHERE posts.workspace_id = ?
                   ORDER BY publish_jobs.run_at DESC""",
                (workspace_id,),
            ).fetchall()
        return [dict(row) for row in rows]

    def cancel_scheduled_post(self, actor_id: str, workspace_id: str, post_id: str) -> dict[str, int | str]:
        with self.database.connect() as conn:
            self._require_role(conn, actor_id, workspace_id, frozenset({"owner", "admin", "publisher"}))
            post = conn.execute(
                "SELECT id, status FROM posts WHERE id = ? AND workspace_id = ?",
                (post_id, workspace_id),
            ).fetchone()
            if post is None:
                raise ServiceError("Post does not belong to this workspace")
            if post["status"] not in {"scheduled", "queued"}:
                raise ServiceError("Only scheduled or queued posts can be cancelled")
            timestamp = now()
            conn.execute("DELETE FROM schedules WHERE post_id = ?", (post_id,))
            updated_jobs = conn.execute(
                "UPDATE publish_jobs SET status = 'failed', last_error = ?, updated_at = ? WHERE post_id = ? AND status IN ('queued', 'running')",
                ("cancelled before publish", timestamp, post_id),
            ).rowcount
            conn.execute("UPDATE posts SET status = 'draft', updated_at = ? WHERE id = ?", (timestamp, post_id))
            self._audit(conn, workspace_id, actor_id, "post.cancelled", "post", post_id)
        return {"post_id": post_id, "updated_jobs": updated_jobs}

            rows = conn.execute("SELECT posts.id, posts.page_id, posts.body, posts.status, posts.created_at, schedules.scheduled_at, schedules.timezone FROM posts LEFT JOIN schedules ON schedules.post_id = posts.id WHERE posts.workspace_id = ? ORDER BY COALESCE(schedules.scheduled_at, posts.created_at)", (workspace_id,)).fetchall()
        return [dict(row) for row in rows]

    def _require_role(self, conn: Any, user_id: str, workspace_id: str, allowed: frozenset[str]) -> str:
        row = conn.execute("SELECT role FROM workspace_members WHERE workspace_id = ? AND user_id = ?", (workspace_id, user_id)).fetchone()
        if row is None or row["role"] not in allowed:
            raise ServiceError("You do not have permission for this workspace")
        return row["role"]

    @staticmethod
    def _audit(conn: Any, workspace_id: str, actor_id: str, action: str, entity_type: str, entity_id: str) -> None:
        conn.execute(
            "INSERT INTO audit_logs(id, workspace_id, actor_id, action, entity_type, entity_id, created_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (identifier(), workspace_id, actor_id, action, entity_type, entity_id, now()),
        )
