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
