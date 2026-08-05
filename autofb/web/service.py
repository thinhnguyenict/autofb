from __future__ import annotations

import csv
import io
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
LOGIN_ATTEMPT_LIMIT = 5
LOGIN_ATTEMPT_WINDOW = timedelta(minutes=15)
LOGIN_LOCK_DURATION = timedelta(minutes=15)
_DUMMY_PASSWORD_HASH = (
    "scrypt$s8jwAtt5xwpwh4hv8mbyKg==$"
    "WgGXRKyqS4TUVsR2jo70fqsBrCkmnicR4yUs9iBXEBZcbtOuRCvc3vJDNc3F9Q5arU2fiGpgSGHO5siFFLdCbw=="
)


class ServiceError(ValueError):
    pass


class AuthenticationThrottled(ServiceError):
    """Raised when repeated login failures temporarily lock an identifier."""


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
        normalized_email = email.strip().lower()
        email_hash = sha256(normalized_email.encode()).hexdigest()
        current_time = datetime.now(UTC)
        invalid_credentials = False
        with self.database.connect() as conn:
            attempt = conn.execute(
                "SELECT failed_count, window_started_at, locked_until FROM auth_login_attempts WHERE email_hash = ?",
                (email_hash,),
            ).fetchone()
            if attempt is not None and attempt["locked_until"]:
                locked_until = datetime.fromisoformat(attempt["locked_until"])
                if locked_until > current_time:
                    raise AuthenticationThrottled("Too many login attempts; try again later")

            user = conn.execute(
                "SELECT id, password_hash FROM users WHERE email = ?", (normalized_email,)
            ).fetchone()
            password_hash = user["password_hash"] if user is not None else _DUMMY_PASSWORD_HASH
            if not verify_password(password, password_hash) or user is None:
                self._record_login_failure(conn, email_hash, attempt, current_time)
                invalid_credentials = True
            else:
                conn.execute("DELETE FROM auth_login_attempts WHERE email_hash = ?", (email_hash,))
                token = new_session_token()
                expires_at = (current_time + timedelta(days=7)).isoformat()
                conn.execute(
                    "INSERT INTO sessions(token_hash, user_id, expires_at, created_at) VALUES (?, ?, ?, ?)",
                    (token_digest(token), user["id"], expires_at, now()),
                )
        if invalid_credentials:
            raise ServiceError("Invalid email or password")
        return token

    @staticmethod
    def _record_login_failure(
        conn: sqlite3.Connection, email_hash: str, attempt: sqlite3.Row | None, current_time: datetime
    ) -> None:
        window_started = current_time
        failed_count = 1
        if attempt is not None:
            previous_window = datetime.fromisoformat(attempt["window_started_at"])
            if previous_window + LOGIN_ATTEMPT_WINDOW > current_time:
                window_started = previous_window
                failed_count = attempt["failed_count"] + 1
        locked_until = None
        if failed_count >= LOGIN_ATTEMPT_LIMIT:
            locked_until = (current_time + LOGIN_LOCK_DURATION).isoformat()
        conn.execute(
            """INSERT INTO auth_login_attempts(
                   email_hash, failed_count, window_started_at, locked_until, updated_at
               ) VALUES (?, ?, ?, ?, ?)
               ON CONFLICT(email_hash) DO UPDATE SET
                   failed_count = excluded.failed_count,
                   window_started_at = excluded.window_started_at,
                   locked_until = excluded.locked_until,
                   updated_at = excluded.updated_at""",
            (email_hash, failed_count, window_started.isoformat(), locked_until, current_time.isoformat()),
        )

    def logout(self, token: str) -> None:
        with self.database.connect() as conn:
            conn.execute("DELETE FROM sessions WHERE token_hash = ?", (token_digest(token),))

    def change_password(self, user_id: str, current_password: str, new_password: str) -> dict[str, str]:
        try:
            new_hash = hash_password(new_password)
        except ValueError as exc:
            raise ServiceError(str(exc)) from exc
        with self.database.connect() as conn:
            user = conn.execute("SELECT password_hash FROM users WHERE id = ?", (user_id,)).fetchone()
            if user is None or not verify_password(current_password, user["password_hash"]):
                raise ServiceError("Current password is incorrect")
            conn.execute("UPDATE users SET password_hash = ? WHERE id = ?", (new_hash, user_id))
            conn.execute("DELETE FROM sessions WHERE user_id = ?", (user_id,))
        return {"status": "password_changed"}

    def update_profile(self, user_id: str, display_name: str) -> dict[str, str]:
        display_name = display_name.strip()
        if not display_name:
            raise ServiceError("Display name is required")
        with self.database.connect() as conn:
            user = conn.execute("SELECT id, email, created_at FROM users WHERE id = ?", (user_id,)).fetchone()
            if user is None:
                raise ServiceError("User does not exist")
            conn.execute("UPDATE users SET display_name = ? WHERE id = ?", (display_name, user_id))
        return {"id": user_id, "email": user["email"], "display_name": display_name, "created_at": user["created_at"]}

    def user_for_token(self, token: str) -> dict[str, str] | None:
        with self.database.connect() as conn:
            row = conn.execute(
                """SELECT users.id, users.email, users.display_name, users.created_at
                   FROM sessions JOIN users ON users.id = sessions.user_id
                   WHERE sessions.token_hash = ? AND sessions.expires_at > ?""",
                (token_digest(token), now()),
            ).fetchone()
        return dict(row) if row else None

    def delete_account(self, actor_id: str, password: str) -> dict[str, str]:
        """Erase personal login data while retaining pseudonymous content history."""
        with self.database.connect() as conn:
            user = conn.execute("SELECT password_hash FROM users WHERE id = ?", (actor_id,)).fetchone()
            if user is None or not verify_password(password, user["password_hash"]):
                raise ServiceError("Current password is incorrect")
            owned = conn.execute("SELECT 1 FROM workspaces WHERE owner_id = ? LIMIT 1", (actor_id,)).fetchone()
            if owned is not None:
                raise ServiceError("Delete owned workspaces before deleting the account")
            conn.execute("DELETE FROM sessions WHERE user_id = ?", (actor_id,))
            conn.execute("DELETE FROM oauth_states WHERE actor_id = ?", (actor_id,))
            conn.execute("DELETE FROM notifications WHERE user_id = ?", (actor_id,))
            conn.execute("DELETE FROM workspace_members WHERE user_id = ?", (actor_id,))
            conn.execute("UPDATE audit_logs SET actor_id = NULL WHERE actor_id = ?", (actor_id,))
            redacted_email = f"deleted-{identifier()}@invalid.local"
            conn.execute(
                "UPDATE users SET email = ?, display_name = 'Deleted user', password_hash = ? WHERE id = ?",
                (redacted_email, hash_password(secrets.token_urlsafe(32)), actor_id),
            )
        return {"status": "deleted"}

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

    def update_workspace(self, actor_id: str, workspace_id: str, name: str) -> dict[str, str]:
        name = name.strip()
        if not name:
            raise ServiceError("Workspace name is required")
        with self.database.connect() as conn:
            self._require_role(conn, actor_id, workspace_id, MANAGE_MEMBERS)
            workspace = conn.execute("SELECT id, owner_id, created_at FROM workspaces WHERE id = ?", (workspace_id,)).fetchone()
            if workspace is None:
                raise ServiceError("Workspace does not exist")
            conn.execute("UPDATE workspaces SET name = ? WHERE id = ?", (name, workspace_id))
            self._audit(conn, workspace_id, actor_id, "workspace.updated", "workspace", workspace_id)
        return {"id": workspace_id, "name": name, "owner_id": workspace["owner_id"], "created_at": workspace["created_at"]}

    def delete_workspace(self, actor_id: str, workspace_id: str) -> dict[str, Any]:
        with self.database.connect() as conn:
            self._require_role(conn, actor_id, workspace_id, frozenset({"owner"}))
            media_paths = [
                row["storage_path"]
                for row in conn.execute("SELECT storage_path FROM media_assets WHERE workspace_id = ?", (workspace_id,)).fetchall()
            ]
            self._audit(conn, workspace_id, actor_id, "workspace.deleted", "workspace", workspace_id)
            conn.execute("DELETE FROM posts WHERE workspace_id = ?", (workspace_id,))
            conn.execute("DELETE FROM media_assets WHERE workspace_id = ?", (workspace_id,))
            conn.execute("DELETE FROM oauth_connections WHERE workspace_id = ?", (workspace_id,))
            conn.execute("DELETE FROM workspaces WHERE id = ?", (workspace_id,))
        return {"id": workspace_id, "status": "deleted", "media_paths": media_paths}

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

    def remove_member(self, actor_id: str, workspace_id: str, member_id: str) -> dict[str, str]:
        with self.database.connect() as conn:
            self._require_role(conn, actor_id, workspace_id, MANAGE_MEMBERS)
            member = conn.execute("SELECT role FROM workspace_members WHERE workspace_id = ? AND user_id = ?", (workspace_id, member_id)).fetchone()
            if member is None:
                raise ServiceError("Member does not belong to this workspace")
            if member["role"] == "owner":
                raise ServiceError("Workspace owner cannot be removed")
            conn.execute("DELETE FROM workspace_members WHERE workspace_id = ? AND user_id = ?", (workspace_id, member_id))
            self._audit(conn, workspace_id, actor_id, "workspace.member_removed", "user", member_id)
        return {"id": member_id, "status": "removed"}

    def workspace_summary(self, actor_id: str, workspace_id: str) -> dict[str, int]:
        with self.database.connect() as conn:
            self._require_role(conn, actor_id, workspace_id, ROLES)
            counts = {
                "members": "SELECT COUNT(*) FROM workspace_members WHERE workspace_id = ?",
                "pages": "SELECT COUNT(*) FROM facebook_pages WHERE workspace_id = ?",
                "media": "SELECT COUNT(*) FROM media_assets WHERE workspace_id = ?",
                "posts": "SELECT COUNT(*) FROM posts WHERE workspace_id = ?",
                "queued_jobs": "SELECT COUNT(*) FROM publish_jobs JOIN posts ON posts.id = publish_jobs.post_id WHERE posts.workspace_id = ? AND publish_jobs.status = 'queued'",
                "unread_notifications": "SELECT COUNT(*) FROM notifications WHERE workspace_id = ? AND user_id = ? AND read_at IS NULL",
            }
            summary = {key: conn.execute(sql, (workspace_id, actor_id) if key == "unread_notifications" else (workspace_id,)).fetchone()[0] for key, sql in counts.items()}
        return summary

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

    def import_facebook_page(
        self,
        actor_id: str,
        workspace_id: str,
        facebook_page_id: str,
        page_name: str,
        encrypted_page_token: str,
        expires_at: str | None = None,
    ) -> dict[str, str]:
        facebook_page_id = facebook_page_id.strip()
        page_name = page_name.strip()
        if not facebook_page_id:
            raise ServiceError("Facebook Page ID is required")
        if not page_name:
            raise ServiceError("Facebook Page name is required")
        if not encrypted_page_token:
            raise ServiceError("Encrypted Page token is required")
        provider_user_id = f"manual:{facebook_page_id}"
        with self.database.connect() as conn:
            self._require_role(conn, actor_id, workspace_id, MANAGE_MEMBERS)
            connection = conn.execute("SELECT id FROM oauth_connections WHERE workspace_id = ? AND provider_user_id = ?", (workspace_id, provider_user_id)).fetchone()
            connection_id = connection["id"] if connection else identifier()
            timestamp = now()
            conn.execute(
                "INSERT INTO oauth_connections(id, workspace_id, provider_user_id, display_name, encrypted_access_token, expires_at, created_at) VALUES (?, ?, ?, ?, ?, ?, ?) "
                "ON CONFLICT(workspace_id, provider_user_id) DO UPDATE SET display_name = excluded.display_name, encrypted_access_token = excluded.encrypted_access_token, expires_at = excluded.expires_at",
                (connection_id, workspace_id, provider_user_id, f"Manual Page: {page_name}", encrypted_page_token, expires_at, timestamp),
            )
            page_id = identifier()
            conn.execute(
                "INSERT INTO facebook_pages(id, workspace_id, connection_id, facebook_page_id, name, encrypted_access_token, created_at) VALUES (?, ?, ?, ?, ?, ?, ?) "
                "ON CONFLICT(workspace_id, facebook_page_id) DO UPDATE SET connection_id = excluded.connection_id, name = excluded.name, encrypted_access_token = excluded.encrypted_access_token",
                (page_id, workspace_id, connection_id, facebook_page_id, page_name, encrypted_page_token, timestamp),
            )
            saved_page = conn.execute("SELECT id, facebook_page_id, name, connection_id, created_at FROM facebook_pages WHERE workspace_id = ? AND facebook_page_id = ?", (workspace_id, facebook_page_id)).fetchone()
            self._audit(conn, workspace_id, actor_id, "facebook.page_imported", "facebook_page", saved_page["id"])
        return dict(saved_page)

    def list_facebook_pages(self, actor_id: str, workspace_id: str) -> list[dict[str, str]]:
        with self.database.connect() as conn:
            self._require_role(conn, actor_id, workspace_id, ROLES)
            rows = conn.execute("SELECT id, facebook_page_id, name, connection_id, created_at FROM facebook_pages WHERE workspace_id = ? ORDER BY name", (workspace_id,)).fetchall()
        return [dict(row) for row in rows]

    def delete_facebook_page(self, actor_id: str, workspace_id: str, page_id: str) -> dict[str, str]:
        with self.database.connect() as conn:
            self._require_role(conn, actor_id, workspace_id, MANAGE_MEMBERS)
            page = conn.execute("SELECT id FROM facebook_pages WHERE id = ? AND workspace_id = ?", (page_id, workspace_id)).fetchone()
            if page is None:
                raise ServiceError("Facebook Page does not belong to this workspace")
            used = conn.execute("SELECT 1 FROM posts WHERE page_id = ? LIMIT 1", (page_id,)).fetchone()
            if used is not None:
                raise ServiceError("Facebook Page is used by posts and cannot be deleted")
            conn.execute("DELETE FROM facebook_pages WHERE id = ?", (page_id,))
            self._audit(conn, workspace_id, actor_id, "facebook.page_deleted", "facebook_page", page_id)
        return {"id": page_id, "status": "deleted"}

    def register_media(self, actor_id: str, workspace_id: str, filename: str, storage_path: str, content_type: str, size_bytes: int) -> dict[str, str]:
        if not filename or size_bytes < 1:
            raise ServiceError("A non-empty media file is required")
        with self.database.connect() as conn:
            self._require_role(conn, actor_id, workspace_id, frozenset({"owner", "admin", "editor", "publisher"}))
            media = {"id": identifier(), "workspace_id": workspace_id, "filename": filename, "storage_path": storage_path, "content_type": content_type, "size_bytes": str(size_bytes), "created_at": now()}
            conn.execute("INSERT INTO media_assets(id, workspace_id, filename, storage_path, content_type, size_bytes, created_by, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)", (media["id"], workspace_id, filename, storage_path, content_type, size_bytes, actor_id, media["created_at"]))
            self._audit(conn, workspace_id, actor_id, "media.uploaded", "media_asset", media["id"])
        return media

    def assert_media_upload_allowed(self, actor_id: str, workspace_id: str) -> None:
        with self.database.connect() as conn:
            self._require_role(conn, actor_id, workspace_id, frozenset({"owner", "admin", "editor", "publisher"}))

    def list_media(self, actor_id: str, workspace_id: str) -> list[dict[str, str]]:
        with self.database.connect() as conn:
            self._require_role(conn, actor_id, workspace_id, ROLES)
            rows = conn.execute("SELECT id, filename, content_type, size_bytes, created_at FROM media_assets WHERE workspace_id = ? ORDER BY created_at DESC", (workspace_id,)).fetchall()
        return [dict(row) for row in rows]

    def delete_media(self, actor_id: str, workspace_id: str, media_id: str) -> dict[str, str]:
        with self.database.connect() as conn:
            self._require_role(conn, actor_id, workspace_id, frozenset({"owner", "admin", "editor", "publisher"}))
            media = conn.execute("SELECT id, storage_path FROM media_assets WHERE id = ? AND workspace_id = ?", (media_id, workspace_id)).fetchone()
            if media is None:
                raise ServiceError("Media does not belong to this workspace")
            attached = conn.execute("SELECT 1 FROM post_media WHERE media_asset_id = ? LIMIT 1", (media_id,)).fetchone()
            if attached is not None:
                raise ServiceError("Media is attached to a post and cannot be deleted")
            conn.execute("DELETE FROM media_assets WHERE id = ?", (media_id,))
            self._audit(conn, workspace_id, actor_id, "media.deleted", "media_asset", media_id)
        return {"id": media["id"], "storage_path": media["storage_path"]}

    def connection_health(
        self,
        actor_id: str,
        workspace_id: str,
        reference_time: datetime | None = None,
    ) -> list[dict[str, str]]:
        current_time = reference_time or datetime.now(UTC)
        with self.database.connect() as conn:
            self._require_role(conn, actor_id, workspace_id, ROLES)
            rows = conn.execute(
                """SELECT oauth_connections.id, oauth_connections.display_name, oauth_connections.expires_at,
                          oauth_connections.created_at,
                          (SELECT status FROM token_health_checks WHERE connection_id = oauth_connections.id
                           ORDER BY checked_at DESC LIMIT 1) AS live_status,
                          (SELECT checked_at FROM token_health_checks WHERE connection_id = oauth_connections.id
                           ORDER BY checked_at DESC LIMIT 1) AS last_checked_at
                   FROM oauth_connections WHERE workspace_id = ? ORDER BY created_at DESC""",
                (workspace_id,),
            ).fetchall()
        connections = []
        for row in rows:
            connection = dict(row)
            connection["health"] = "unknown"
            if connection["expires_at"]:
                try:
                    expires_at = datetime.fromisoformat(connection["expires_at"].replace("Z", "+00:00"))
                    if expires_at.tzinfo is None:
                        expires_at = expires_at.replace(tzinfo=UTC)
                    remaining = expires_at - current_time
                    connection["health"] = "expired" if remaining.total_seconds() <= 0 else "expiring" if remaining <= timedelta(days=7) else "healthy"
                except ValueError:
                    pass
            connections.append(connection)
        return connections

    def connection_token_for_diagnostics(self, actor_id: str, workspace_id: str, connection_id: str) -> str:
        with self.database.connect() as conn:
            self._require_role(conn, actor_id, workspace_id, MANAGE_MEMBERS)
            connection = conn.execute(
                "SELECT encrypted_access_token FROM oauth_connections WHERE id = ? AND workspace_id = ?",
                (connection_id, workspace_id),
            ).fetchone()
            if connection is None:
                raise ServiceError("Facebook connection does not belong to this workspace")
        return connection["encrypted_access_token"]

    def record_connection_diagnostic(
        self,
        actor_id: str,
        workspace_id: str,
        connection_id: str,
        check_status: str,
        detail: str | None = None,
    ) -> dict[str, str | None]:
        if check_status not in {"valid", "invalid"}:
            raise ServiceError("Connection diagnostic status is invalid")
        timestamp = now()
        safe_detail = (detail or "").strip()[:500] or None
        with self.database.connect() as conn:
            self._require_role(conn, actor_id, workspace_id, MANAGE_MEMBERS)
            connection = conn.execute(
                "SELECT id FROM oauth_connections WHERE id = ? AND workspace_id = ?",
                (connection_id, workspace_id),
            ).fetchone()
            if connection is None:
                raise ServiceError("Facebook connection does not belong to this workspace")
            conn.execute(
                "INSERT INTO token_health_checks(id, connection_id, status, detail, checked_at) VALUES (?, ?, ?, ?, ?)",
                (identifier(), connection_id, check_status, safe_detail, timestamp),
            )
            self._audit(conn, workspace_id, actor_id, "facebook.connection_checked", "oauth_connection", connection_id)
        return {"connection_id": connection_id, "status": check_status, "detail": safe_detail, "checked_at": timestamp}

    def delete_facebook_connection(self, actor_id: str, workspace_id: str, connection_id: str) -> dict[str, str]:
        with self.database.connect() as conn:
            self._require_role(conn, actor_id, workspace_id, MANAGE_MEMBERS)
            connection = conn.execute(
                "SELECT id FROM oauth_connections WHERE id = ? AND workspace_id = ?",
                (connection_id, workspace_id),
            ).fetchone()
            if connection is None:
                raise ServiceError("Facebook connection does not belong to this workspace")
            used_page = conn.execute(
                """SELECT 1 FROM posts JOIN facebook_pages ON facebook_pages.id = posts.page_id
                   WHERE facebook_pages.connection_id = ? LIMIT 1""",
                (connection_id,),
            ).fetchone()
            if used_page is not None:
                raise ServiceError("Facebook connection has Pages used by posts and cannot be deleted")
            conn.execute("DELETE FROM oauth_connections WHERE id = ?", (connection_id,))
            self._audit(conn, workspace_id, actor_id, "facebook.connection_deleted", "oauth_connection", connection_id)
        return {"id": connection_id, "status": "deleted"}

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

    def clear_read_notifications(self, actor_id: str, workspace_id: str) -> dict[str, int]:
        with self.database.connect() as conn:
            self._require_role(conn, actor_id, workspace_id, ROLES)
            deleted = conn.execute(
                "DELETE FROM notifications WHERE workspace_id = ? AND user_id = ? AND read_at IS NOT NULL",
                (workspace_id, actor_id),
            ).rowcount
        return {"deleted": deleted}

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

    def update_post(self, actor_id: str, workspace_id: str, post_id: str, body: str | None = None, media_ids: list[str] | None = None) -> dict[str, str]:
        timestamp = now()
        with self.database.connect() as conn:
            self._require_role(conn, actor_id, workspace_id, frozenset({"owner", "admin", "editor", "publisher"}))
            post = conn.execute("SELECT id, body, status FROM posts WHERE id = ? AND workspace_id = ?", (post_id, workspace_id)).fetchone()
            if post is None:
                raise ServiceError("Post does not belong to this workspace")
            if post["status"] not in {"draft", "failed"}:
                raise ServiceError("Only draft or failed posts can be edited")
            next_body = post["body"] if body is None else body.strip()
            if not next_body:
                raise ServiceError("Post body is required")
            conn.execute("UPDATE posts SET body = ?, updated_at = ? WHERE id = ?", (next_body, timestamp, post_id))
            if media_ids is not None:
                conn.execute("DELETE FROM post_media WHERE post_id = ?", (post_id,))
                for sort_order, media_id in enumerate(media_ids):
                    media = conn.execute("SELECT id FROM media_assets WHERE id = ? AND workspace_id = ?", (media_id, workspace_id)).fetchone()
                    if media is None:
                        raise ServiceError("Media does not belong to this workspace")
                    conn.execute("INSERT INTO post_media(post_id, media_asset_id, sort_order) VALUES (?, ?, ?)", (post_id, media_id, sort_order))
            conn.execute("DELETE FROM post_approvals WHERE post_id = ?", (post_id,))
            self._audit(conn, workspace_id, actor_id, "post.updated", "post", post_id)
        return {"id": post_id, "body": next_body, "status": post["status"], "updated_at": timestamp}

    def duplicate_post(self, actor_id: str, workspace_id: str, post_id: str) -> dict[str, str]:
        timestamp = now()
        with self.database.connect() as conn:
            self._require_role(conn, actor_id, workspace_id, frozenset({"owner", "admin", "editor", "publisher"}))
            source = conn.execute("SELECT page_id, body FROM posts WHERE id = ? AND workspace_id = ?", (post_id, workspace_id)).fetchone()
            if source is None:
                raise ServiceError("Post does not belong to this workspace")
            duplicated = {"id": identifier(), "workspace_id": workspace_id, "page_id": source["page_id"], "body": source["body"], "status": "draft", "created_at": timestamp, "updated_at": timestamp}
            conn.execute(
                "INSERT INTO posts(id, workspace_id, page_id, body, status, created_by, created_at, updated_at) VALUES (?, ?, ?, ?, 'draft', ?, ?, ?)",
                (duplicated["id"], workspace_id, source["page_id"], source["body"], actor_id, timestamp, timestamp),
            )
            media_rows = conn.execute(
                "SELECT media_asset_id, sort_order FROM post_media WHERE post_id = ? ORDER BY sort_order",
                (post_id,),
            ).fetchall()
            for media in media_rows:
                conn.execute("INSERT INTO post_media(post_id, media_asset_id, sort_order) VALUES (?, ?, ?)", (duplicated["id"], media["media_asset_id"], media["sort_order"]))
            self._audit(conn, workspace_id, actor_id, "post.duplicated", "post", duplicated["id"])
        return duplicated

    def schedule_post(self, actor_id: str, workspace_id: str, post_id: str, scheduled_at: str, timezone: str) -> dict[str, str]:
        try:
            run_at = datetime.fromisoformat(scheduled_at.replace("Z", "+00:00"))
        except ValueError as exc:
            raise ServiceError("scheduled_at must be ISO-8601") from exc
        if run_at.tzinfo is None or run_at <= datetime.now(UTC):
            raise ServiceError("scheduled_at must be a future timezone-aware time")
        with self.database.connect() as conn:
            role = self._require_role(conn, actor_id, workspace_id, frozenset({"owner", "admin", "editor", "publisher"}))
            post = conn.execute("SELECT id FROM posts WHERE id = ? AND workspace_id = ?", (post_id, workspace_id)).fetchone()
            if post is None:
                raise ServiceError("Post does not belong to this workspace")
            self._require_editor_approval(conn, role, post_id)
            timestamp = now()
            existing_schedule = conn.execute("SELECT id FROM schedules WHERE post_id = ?", (post_id,)).fetchone()
            schedule_id = existing_schedule["id"] if existing_schedule else identifier()
            conn.execute("INSERT INTO schedules(id, post_id, scheduled_at, timezone, created_at) VALUES (?, ?, ?, ?, ?) ON CONFLICT(post_id) DO UPDATE SET scheduled_at = excluded.scheduled_at, timezone = excluded.timezone", (schedule_id, post_id, scheduled_at, timezone, timestamp))
            conn.execute("UPDATE posts SET status = 'scheduled', updated_at = ? WHERE id = ?", (timestamp, post_id))
            job_id = self._queue_post_job(conn, post_id, scheduled_at, timestamp)
            self._audit(conn, workspace_id, actor_id, "post.scheduled", "post", post_id)
        return {"id": schedule_id, "post_id": post_id, "scheduled_at": scheduled_at, "timezone": timezone, "job_id": job_id}

    def publish_post_now(self, actor_id: str, workspace_id: str, post_id: str) -> dict[str, str]:
        timestamp = now()
        with self.database.connect() as conn:
            role = self._require_role(conn, actor_id, workspace_id, frozenset({"owner", "admin", "editor", "publisher"}))
            post = conn.execute("SELECT id FROM posts WHERE id = ? AND workspace_id = ?", (post_id, workspace_id)).fetchone()
            if post is None:
                raise ServiceError("Post does not belong to this workspace")
            self._require_editor_approval(conn, role, post_id)
            conn.execute("DELETE FROM schedules WHERE post_id = ?", (post_id,))
            conn.execute("UPDATE posts SET status = 'queued', updated_at = ? WHERE id = ?", (timestamp, post_id))
            job_id = self._queue_post_job(conn, post_id, timestamp, timestamp)
            self._audit(conn, workspace_id, actor_id, "post.publish_now", "post", post_id)
        return {"post_id": post_id, "job_id": job_id, "run_at": timestamp}

    @staticmethod
    def _queue_post_job(conn: sqlite3.Connection, post_id: str, run_at: str, timestamp: str) -> str:
        """Create or update the sole queued job for a post.

        Repeated schedule/publish requests must not produce multiple provider
        deliveries. A running job cannot be safely moved and must finish first.
        """
        active = conn.execute(
            "SELECT id, status FROM publish_jobs WHERE post_id = ? AND status IN ('queued', 'running') ORDER BY created_at LIMIT 1",
            (post_id,),
        ).fetchone()
        if active is not None:
            if active["status"] == "running":
                raise ServiceError("Post is already being published")
            conn.execute(
                "UPDATE publish_jobs SET run_at = ?, attempts = 0, last_error = NULL, updated_at = ? WHERE id = ?",
                (run_at, timestamp, active["id"]),
            )
            return str(active["id"])
        job_id = identifier()
        conn.execute(
            "INSERT INTO publish_jobs(id, post_id, status, run_at, attempts, created_at, updated_at) VALUES (?, ?, 'queued', ?, 0, ?, ?)",
            (job_id, post_id, run_at, timestamp, timestamp),
        )
        return job_id

    def retry_failed_post(self, actor_id: str, workspace_id: str, post_id: str) -> dict[str, str]:
        timestamp = now()
        with self.database.connect() as conn:
            self._require_role(conn, actor_id, workspace_id, frozenset({"owner", "admin", "publisher"}))
            post = conn.execute("SELECT id, status FROM posts WHERE id = ? AND workspace_id = ?", (post_id, workspace_id)).fetchone()
            if post is None:
                raise ServiceError("Post does not belong to this workspace")
            if post["status"] != "failed":
                raise ServiceError("Only failed posts can be retried")
            job_id = identifier()
            conn.execute("UPDATE posts SET status = 'queued', updated_at = ? WHERE id = ?", (timestamp, post_id))
            conn.execute("INSERT INTO publish_jobs(id, post_id, status, run_at, attempts, created_at, updated_at) VALUES (?, ?, 'queued', ?, 0, ?, ?)", (job_id, post_id, timestamp, timestamp, timestamp))
            self._audit(conn, workspace_id, actor_id, "post.retry_queued", "post", post_id)
        return {"post_id": post_id, "job_id": job_id, "run_at": timestamp}

    def list_posts(self, actor_id: str, workspace_id: str, status_filter: str | None = None) -> list[dict[str, str]]:
        allowed_statuses = {"draft", "scheduled", "queued", "publishing", "published", "failed"}
        if status_filter:
            status_filter = status_filter.strip().lower()
            if status_filter not in allowed_statuses:
                raise ServiceError("Post status filter is invalid")
        with self.database.connect() as conn:
            self._require_role(conn, actor_id, workspace_id, ROLES)
            parameters = [workspace_id]
            where = "posts.workspace_id = ?"
            if status_filter:
                where += " AND posts.status = ?"
                parameters.append(status_filter)
            rows = conn.execute(
                f"SELECT posts.id, posts.page_id, posts.body, posts.status, posts.created_at, schedules.scheduled_at, schedules.timezone, post_approvals.status AS approval_status, post_approvals.comment AS approval_comment, COUNT(post_media.media_asset_id) AS media_count FROM posts LEFT JOIN schedules ON schedules.post_id = posts.id LEFT JOIN post_approvals ON post_approvals.post_id = posts.id LEFT JOIN post_media ON post_media.post_id = posts.id WHERE {where} GROUP BY posts.id, schedules.scheduled_at, schedules.timezone, post_approvals.status, post_approvals.comment ORDER BY COALESCE(schedules.scheduled_at, posts.created_at)",
                tuple(parameters),
            ).fetchall()
        return [dict(row) for row in rows]

    def request_post_approval(self, actor_id: str, workspace_id: str, post_id: str, comment: str | None = None) -> dict[str, str | None]:
        timestamp = now()
        with self.database.connect() as conn:
            self._require_role(conn, actor_id, workspace_id, frozenset({"owner", "admin", "editor", "publisher"}))
            post = conn.execute("SELECT status, body FROM posts WHERE id = ? AND workspace_id = ?", (post_id, workspace_id)).fetchone()
            if post is None:
                raise ServiceError("Post does not belong to this workspace")
            if post["status"] not in {"draft", "failed"}:
                raise ServiceError("Only draft or failed posts can request approval")
            conn.execute(
                """INSERT INTO post_approvals(post_id, status, requested_by, reviewed_by, comment, requested_at, reviewed_at)
                   VALUES (?, 'pending', ?, NULL, ?, ?, NULL)
                   ON CONFLICT(post_id) DO UPDATE SET status = 'pending', requested_by = excluded.requested_by,
                       reviewed_by = NULL, comment = excluded.comment, requested_at = excluded.requested_at, reviewed_at = NULL""",
                (post_id, actor_id, (comment or "").strip() or None, timestamp),
            )
            reviewers = conn.execute(
                "SELECT user_id FROM workspace_members WHERE workspace_id = ? AND role IN ('owner', 'admin') AND user_id != ?",
                (workspace_id, actor_id),
            ).fetchall()
            for reviewer in reviewers:
                conn.execute(
                    "INSERT INTO notifications(id, workspace_id, user_id, type, message, created_at) VALUES (?, ?, ?, 'approval_requested', ?, ?)",
                    (identifier(), workspace_id, reviewer["user_id"], f"Post waiting for approval: {post['body'][:80]}", timestamp),
                )
            self._audit(conn, workspace_id, actor_id, "post.approval_requested", "post", post_id)
        return {"post_id": post_id, "status": "pending", "comment": (comment or "").strip() or None}

    def review_post_approval(self, actor_id: str, workspace_id: str, post_id: str, decision: str, comment: str | None = None) -> dict[str, str | None]:
        if decision not in {"approved", "rejected"}:
            raise ServiceError("Approval decision must be approved or rejected")
        timestamp = now()
        with self.database.connect() as conn:
            self._require_role(conn, actor_id, workspace_id, MANAGE_MEMBERS)
            approval = conn.execute(
                """SELECT post_approvals.status, post_approvals.requested_by FROM post_approvals JOIN posts ON posts.id = post_approvals.post_id
                   WHERE post_approvals.post_id = ? AND posts.workspace_id = ?""",
                (post_id, workspace_id),
            ).fetchone()
            if approval is None or approval["status"] != "pending":
                raise ServiceError("Post does not have a pending approval request")
            conn.execute(
                "UPDATE post_approvals SET status = ?, reviewed_by = ?, comment = ?, reviewed_at = ? WHERE post_id = ?",
                (decision, actor_id, (comment or "").strip() or None, timestamp, post_id),
            )
            conn.execute(
                "INSERT INTO notifications(id, workspace_id, user_id, type, message, created_at) VALUES (?, ?, ?, 'approval_reviewed', ?, ?)",
                (identifier(), workspace_id, approval["requested_by"], f"Your post was {decision}", timestamp),
            )
            self._audit(conn, workspace_id, actor_id, f"post.{decision}", "post", post_id)
        return {"post_id": post_id, "status": decision, "comment": (comment or "").strip() or None}

    def list_calendar(self, actor_id: str, workspace_id: str, date_from: str, date_to: str) -> list[dict[str, str]]:
        try:
            start = datetime.fromisoformat(date_from.replace("Z", "+00:00"))
            end = datetime.fromisoformat(date_to.replace("Z", "+00:00"))
        except ValueError as exc:
            raise ServiceError("Calendar range must use ISO-8601 dates") from exc
        if end <= start:
            raise ServiceError("Calendar end must be after start")
        if end - start > timedelta(days=366):
            raise ServiceError("Calendar range cannot exceed 366 days")
        with self.database.connect() as conn:
            self._require_role(conn, actor_id, workspace_id, ROLES)
            rows = conn.execute(
                """SELECT posts.id, posts.body, posts.status, schedules.scheduled_at, schedules.timezone,
                          facebook_pages.id AS page_id, facebook_pages.name AS page_name,
                          COUNT(post_media.media_asset_id) AS media_count
                   FROM schedules JOIN posts ON posts.id = schedules.post_id
                   JOIN facebook_pages ON facebook_pages.id = posts.page_id
                   LEFT JOIN post_media ON post_media.post_id = posts.id
                   WHERE posts.workspace_id = ?
                     AND datetime(schedules.scheduled_at) >= datetime(?)
                     AND datetime(schedules.scheduled_at) < datetime(?)
                   GROUP BY posts.id, schedules.id, facebook_pages.id
                   ORDER BY datetime(schedules.scheduled_at), posts.id""",
                (workspace_id, date_from, date_to),
            ).fetchall()
        return [dict(row) for row in rows]

    def export_posts_csv(self, actor_id: str, workspace_id: str, status_filter: str | None = None) -> str:
        rows = self.list_posts(actor_id, workspace_id, status_filter)
        output = io.StringIO()
        fieldnames = ["id", "status", "approval_status", "body", "page_id", "scheduled_at", "timezone", "media_count", "created_at"]
        writer = csv.DictWriter(output, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            writer.writerow(row)
        return output.getvalue()

    def export_workspace_data(self, actor_id: str, workspace_id: str) -> dict[str, Any]:
        """Export workspace records for portability without encryption keys or tokens."""
        with self.database.connect() as conn:
            self._require_role(conn, actor_id, workspace_id, MANAGE_MEMBERS)
            workspace = conn.execute(
                "SELECT id, name, owner_id, created_at FROM workspaces WHERE id = ?",
                (workspace_id,),
            ).fetchone()
            if workspace is None:
                raise ServiceError("Workspace does not exist")

            def rows(query: str, parameters: tuple[str, ...] = (workspace_id,)) -> list[dict[str, Any]]:
                return [dict(row) for row in conn.execute(query, parameters).fetchall()]

            export = {
                "schema_version": 1,
                "exported_at": now(),
                "workspace": dict(workspace),
                "members": rows(
                    """SELECT users.id, users.email, users.display_name, workspace_members.role, workspace_members.created_at
                       FROM workspace_members JOIN users ON users.id = workspace_members.user_id
                       WHERE workspace_members.workspace_id = ? ORDER BY workspace_members.created_at"""
                ),
                "facebook_connections": rows(
                    "SELECT id, display_name, expires_at, created_at FROM oauth_connections WHERE workspace_id = ? ORDER BY created_at"
                ),
                "facebook_pages": rows(
                    "SELECT id, connection_id, facebook_page_id, name, created_at FROM facebook_pages WHERE workspace_id = ? ORDER BY created_at"
                ),
                "token_health_checks": rows(
                    """SELECT token_health_checks.id, token_health_checks.connection_id, token_health_checks.status,
                              token_health_checks.detail, token_health_checks.checked_at
                       FROM token_health_checks JOIN oauth_connections ON oauth_connections.id = token_health_checks.connection_id
                       WHERE oauth_connections.workspace_id = ? ORDER BY token_health_checks.checked_at"""
                ),
                "media": rows(
                    "SELECT id, filename, content_type, size_bytes, created_by, created_at FROM media_assets WHERE workspace_id = ? ORDER BY created_at"
                ),
                "posts": rows(
                    "SELECT id, page_id, body, status, created_by, created_at, updated_at FROM posts WHERE workspace_id = ? ORDER BY created_at"
                ),
                "post_approvals": rows(
                    """SELECT post_approvals.post_id, post_approvals.status, post_approvals.requested_by,
                              post_approvals.reviewed_by, post_approvals.comment, post_approvals.requested_at,
                              post_approvals.reviewed_at
                       FROM post_approvals JOIN posts ON posts.id = post_approvals.post_id
                       WHERE posts.workspace_id = ? ORDER BY post_approvals.requested_at"""
                ),
                "schedules": rows(
                    """SELECT schedules.id, schedules.post_id, schedules.scheduled_at, schedules.timezone, schedules.created_at
                       FROM schedules JOIN posts ON posts.id = schedules.post_id
                       WHERE posts.workspace_id = ? ORDER BY schedules.created_at"""
                ),
                "publish_jobs": rows(
                    """SELECT publish_jobs.id, publish_jobs.post_id, publish_jobs.status, publish_jobs.run_at,
                              publish_jobs.attempts, publish_jobs.last_error, publish_jobs.created_at, publish_jobs.updated_at
                       FROM publish_jobs JOIN posts ON posts.id = publish_jobs.post_id
                       WHERE posts.workspace_id = ? ORDER BY publish_jobs.created_at"""
                ),
                "publish_results": rows(
                    """SELECT publish_results.id, publish_results.job_id, publish_results.post_id, publish_results.status,
                              publish_results.attempt, publish_results.remote_post_id, publish_results.error, publish_results.created_at
                       FROM publish_results JOIN posts ON posts.id = publish_results.post_id
                       WHERE posts.workspace_id = ? ORDER BY publish_results.created_at"""
                ),
                "audit_logs": rows(
                    "SELECT id, actor_id, action, entity_type, entity_id, created_at FROM audit_logs WHERE workspace_id = ? ORDER BY created_at"
                ),
            }
            self._audit(conn, workspace_id, actor_id, "workspace.data_exported", "workspace", workspace_id)
        return export

    def publish_metrics(self, actor_id: str, workspace_id: str) -> dict[str, int]:
        with self.database.connect() as conn:
            self._require_role(conn, actor_id, workspace_id, frozenset({"owner", "admin", "publisher"}))
            job_rows = conn.execute(
                """SELECT publish_jobs.status, COUNT(*) AS total
                   FROM publish_jobs JOIN posts ON posts.id = publish_jobs.post_id
                   WHERE posts.workspace_id = ?
                   GROUP BY publish_jobs.status""",
                (workspace_id,),
            ).fetchall()
            result_rows = conn.execute(
                """SELECT publish_results.status, COUNT(*) AS total
                   FROM publish_results JOIN posts ON posts.id = publish_results.post_id
                   WHERE posts.workspace_id = ?
                   GROUP BY publish_results.status""",
                (workspace_id,),
            ).fetchall()
        metrics = {"jobs_queued": 0, "jobs_running": 0, "jobs_succeeded": 0, "jobs_failed": 0, "results_succeeded": 0, "results_failed": 0}
        for row in job_rows:
            metrics[f"jobs_{row['status']}"] = row["total"]
        for row in result_rows:
            metrics[f"results_{row['status']}"] = row["total"]
        return metrics

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

    def list_publish_results(self, actor_id: str, workspace_id: str, limit: int = 50) -> list[dict[str, str]]:
        with self.database.connect() as conn:
            self._require_role(conn, actor_id, workspace_id, frozenset({"owner", "admin", "publisher"}))
            rows = conn.execute(
                """SELECT publish_results.id, publish_results.job_id, publish_results.post_id,
                          publish_results.status, publish_results.attempt, publish_results.remote_post_id,
                          publish_results.error, publish_results.created_at,
                          posts.body, facebook_pages.name AS page_name
                   FROM publish_results JOIN posts ON posts.id = publish_results.post_id
                   JOIN facebook_pages ON facebook_pages.id = posts.page_id
                   WHERE posts.workspace_id = ?
                   ORDER BY publish_results.created_at DESC
                   LIMIT ?""",
                (workspace_id, limit),
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


    def delete_post(self, actor_id: str, workspace_id: str, post_id: str) -> dict[str, str]:
        with self.database.connect() as conn:
            self._require_role(conn, actor_id, workspace_id, frozenset({"owner", "admin", "editor", "publisher"}))
            post = conn.execute("SELECT id, status FROM posts WHERE id = ? AND workspace_id = ?", (post_id, workspace_id)).fetchone()
            if post is None:
                raise ServiceError("Post does not belong to this workspace")
            if post["status"] not in {"draft", "failed"}:
                raise ServiceError("Only draft or failed posts can be deleted")
            conn.execute("DELETE FROM posts WHERE id = ?", (post_id,))
            self._audit(conn, workspace_id, actor_id, "post.deleted", "post", post_id)
        return {"post_id": post_id, "status": "deleted"}

    def _require_role(self, conn: Any, user_id: str, workspace_id: str, allowed: frozenset[str]) -> str:
        row = conn.execute("SELECT role FROM workspace_members WHERE workspace_id = ? AND user_id = ?", (workspace_id, user_id)).fetchone()
        if row is None or row["role"] not in allowed:
            raise ServiceError("You do not have permission for this workspace")
        return row["role"]

    @staticmethod
    def _require_editor_approval(conn: Any, role: str, post_id: str) -> None:
        if role != "editor":
            return
        approval = conn.execute("SELECT status FROM post_approvals WHERE post_id = ?", (post_id,)).fetchone()
        if approval is None or approval["status"] != "approved":
            raise ServiceError("Editor posts must be approved before publishing")

    @staticmethod
    def _audit(conn: Any, workspace_id: str, actor_id: str, action: str, entity_type: str, entity_id: str) -> None:
        conn.execute(
            "INSERT INTO audit_logs(id, workspace_id, actor_id, action, entity_type, entity_id, created_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (identifier(), workspace_id, actor_id, action, entity_type, entity_id, now()),
        )
