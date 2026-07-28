"""Password and opaque-session primitives that never expose raw session storage."""
from __future__ import annotations

import base64
import hashlib
import hmac
import secrets


_SCRYPT_N = 2**14


def hash_password(password: str) -> str:
    if len(password) < 12:
        raise ValueError("Password must contain at least 12 characters")
    salt = secrets.token_bytes(16)
    digest = hashlib.scrypt(password.encode(), salt=salt, n=_SCRYPT_N, r=8, p=1)
    return "scrypt$%s$%s" % (
        base64.urlsafe_b64encode(salt).decode(),
        base64.urlsafe_b64encode(digest).decode(),
    )


def verify_password(password: str, encoded: str) -> bool:
    try:
        algorithm, encoded_salt, encoded_digest = encoded.split("$", 2)
        if algorithm != "scrypt":
            return False
        salt = base64.urlsafe_b64decode(encoded_salt)
        expected = base64.urlsafe_b64decode(encoded_digest)
        actual = hashlib.scrypt(password.encode(), salt=salt, n=_SCRYPT_N, r=8, p=1)
    except (ValueError, TypeError):
        return False
    return hmac.compare_digest(actual, expected)


def new_session_token() -> str:
    return secrets.token_urlsafe(32)


def token_digest(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def http_security_headers(path: str, *, enable_hsts: bool = False) -> dict[str, str]:
    """Return restrictive headers for API, dashboard, and static responses."""
    sensitive = path.startswith("/api/") or path in {"/healthz", "/readyz", "/workerz", "/backupz"}
    if path in {"/docs", "/redoc"}:
        content_policy = (
            "default-src 'self'; base-uri 'none'; frame-ancestors 'none'; object-src 'none'; "
            "script-src 'self' 'unsafe-inline' https://cdn.jsdelivr.net; "
            "style-src 'self' 'unsafe-inline' https://cdn.jsdelivr.net; "
            "img-src 'self' data: https://fastapi.tiangolo.com"
        )
    else:
        content_policy = (
            "default-src 'self'; base-uri 'none'; frame-ancestors 'none'; "
            "form-action 'self'; object-src 'none'; script-src 'self'; style-src 'self'; "
            "connect-src 'self'; img-src 'self' data: blob:; media-src 'self' blob:"
        )
    headers = {
        "X-Content-Type-Options": "nosniff",
        "X-Frame-Options": "DENY",
        "Referrer-Policy": "same-origin",
        "Permissions-Policy": "camera=(), microphone=(), geolocation=(), payment=()",
        "Cross-Origin-Opener-Policy": "same-origin",
        "Content-Security-Policy": content_policy,
        "Cache-Control": "no-store" if sensitive else ("public, max-age=3600" if path.startswith("/static/") else "no-cache"),
    }
    if enable_hsts:
        headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
    return headers
