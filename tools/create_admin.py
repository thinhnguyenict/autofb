"""Create the first AutoFB admin account and workspace from the command line."""
from __future__ import annotations

import argparse
import os
from pathlib import Path

from autofb.web.database import Database
from autofb.web.service import AutoFBService, ServiceError


def create_admin(database_path: str | Path, email: str, password: str, display_name: str, workspace_name: str) -> dict[str, str]:
    database = Database(database_path)
    database.initialize()
    service = AutoFBService(database)
    try:
        user = service.register(email, password, display_name)
    except ServiceError as exc:
        if "already registered" not in str(exc):
            raise
        with database.connect() as conn:
            row = conn.execute("SELECT id, email, display_name, created_at FROM users WHERE email = ?", (email.strip().lower(),)).fetchone()
            if row is None:
                raise
            user = dict(row)
    workspaces = [item for item in service.list_workspaces(user["id"]) if item["name"] == workspace_name]
    workspace = workspaces[0] if workspaces else service.create_workspace(user["id"], workspace_name)
    return {"user_id": user["id"], "email": user["email"], "workspace_id": workspace["id"], "workspace_name": workspace["name"]}


def parser() -> argparse.ArgumentParser:
    arg_parser = argparse.ArgumentParser(description="Create an AutoFB admin account and initial workspace.")
    arg_parser.add_argument("--database", default=os.environ.get("AUTOFB_DATABASE_PATH", "autofb.db"), help="SQLite database path.")
    arg_parser.add_argument("--email", default=os.environ.get("AUTOFB_ADMIN_EMAIL", ""), help="Admin email address.")
    arg_parser.add_argument("--password", default=os.environ.get("AUTOFB_ADMIN_PASSWORD", ""), help="Admin password, at least 12 characters.")
    arg_parser.add_argument("--display-name", default=os.environ.get("AUTOFB_ADMIN_DISPLAY_NAME", "Admin"), help="Admin display name.")
    arg_parser.add_argument("--workspace", default=os.environ.get("AUTOFB_ADMIN_WORKSPACE", "Default workspace"), help="Initial workspace name.")
    return arg_parser


def main() -> int:
    args = parser().parse_args()
    if not args.email or not args.password:
        raise SystemExit("--email/--password or AUTOFB_ADMIN_EMAIL/AUTOFB_ADMIN_PASSWORD are required")
    result = create_admin(args.database, args.email, args.password, args.display_name, args.workspace)
    print(f"Admin ready: {result['email']} workspace={result['workspace_name']} ({result['workspace_id']})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
