"""Meta OAuth integration; credentials remain server-side and encrypted at rest."""
from __future__ import annotations

import os
from dataclasses import dataclass
from urllib.parse import urlencode

import httpx
from cryptography.fernet import Fernet


class OAuthError(RuntimeError):
    pass


@dataclass(frozen=True)
class MetaOAuthSettings:
    app_id: str
    app_secret: str
    redirect_uri: str
    encryption_key: str
    graph_version: str = "v25.0"
    scopes: str = "pages_show_list,pages_manage_posts"

    @classmethod
    def from_environment(cls) -> "MetaOAuthSettings":
        values = {
            "app_id": os.environ.get("META_APP_ID", ""),
            "app_secret": os.environ.get("META_APP_SECRET", ""),
            "redirect_uri": os.environ.get("META_REDIRECT_URI", ""),
            "encryption_key": os.environ.get("AUTOFB_TOKEN_ENCRYPTION_KEY", ""),
        }
        missing = [name for name, value in values.items() if not value]
        if missing:
            raise OAuthError("Missing OAuth configuration: " + ", ".join(missing))
        return cls(**values, graph_version=os.environ.get("META_GRAPH_VERSION", "v25.0"), scopes=os.environ.get("META_OAUTH_SCOPES", "pages_show_list,pages_manage_posts"))


class MetaOAuth:
    def __init__(self, settings: MetaOAuthSettings) -> None:
        self.settings = settings
        self.cipher = Fernet(settings.encryption_key.encode())
        self.base_url = f"https://graph.facebook.com/{settings.graph_version}"

    def authorization_url(self, state: str) -> str:
        query = urlencode({"client_id": self.settings.app_id, "redirect_uri": self.settings.redirect_uri, "state": state, "response_type": "code", "scope": self.settings.scopes})
        return "https://www.facebook.com/" + self.settings.graph_version + "/dialog/oauth?" + query

    def exchange_and_discover(self, code: str) -> tuple[str, str, list[dict[str, str]], str, int]:
        token_response = self._get("/oauth/access_token", {"client_id": self.settings.app_id, "client_secret": self.settings.app_secret, "redirect_uri": self.settings.redirect_uri, "code": code})
        access_token = str(token_response.get("access_token", ""))
        if not access_token:
            raise OAuthError("Meta did not return an access token")
        profile = self._get("/me", {"fields": "id,name", "access_token": access_token})
        accounts = self._get("/me/accounts", {"fields": "id,name,access_token", "access_token": access_token})
        pages = [
            {"facebook_page_id": str(item["id"]), "name": str(item.get("name", item["id"])), "encrypted_access_token": self.encrypt(str(item["access_token"]))}
            for item in accounts.get("data", [])
            if item.get("id") and item.get("access_token")
        ]
        expires_in = int(token_response.get("expires_in", 0) or 0)
        return str(profile.get("id", "")), str(profile.get("name", "Facebook user")), pages, self.encrypt(access_token), expires_in

    def encrypt(self, value: str) -> str:
        return self.cipher.encrypt(value.encode()).decode()

    def _get(self, path: str, params: dict[str, str]) -> dict:
        response = httpx.get(self.base_url + path, params=params, timeout=20)
        try:
            payload = response.json()
        except ValueError as exc:
            raise OAuthError("Meta returned an invalid response") from exc
        if response.is_error or "error" in payload:
            message = payload.get("error", {}).get("message", "Meta OAuth request failed")
            raise OAuthError(str(message))
        return payload
