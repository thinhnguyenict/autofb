"""Structured application logging without request bodies, queries, or secrets."""
from __future__ import annotations

import json
import logging
import re
import threading
import time
import uuid
from collections import OrderedDict
from contextlib import closing
from datetime import UTC, datetime
from urllib.request import Request, urlopen


REQUEST_ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")


class ErrorReportLimiter:
    """Bound duplicate hosted error reports while keeping memory usage predictable."""

    def __init__(self, cooldown_seconds: float = 60, max_fingerprints: int = 1024, clock=time.monotonic) -> None:
        if cooldown_seconds < 0:
            raise ValueError("cooldown_seconds cannot be negative")
        if max_fingerprints < 1:
            raise ValueError("max_fingerprints must be positive")
        self.cooldown_seconds = cooldown_seconds
        self.max_fingerprints = max_fingerprints
        self.clock = clock
        self._seen: OrderedDict[str, float] = OrderedDict()
        self._lock = threading.Lock()

    def allow(self, method: str, path: str, error_type: str) -> bool:
        fingerprint = f"{method}:{path}:{error_type}"
        current = self.clock()
        with self._lock:
            previous = self._seen.get(fingerprint)
            if previous is not None and current - previous < self.cooldown_seconds:
                self._seen.move_to_end(fingerprint)
                return False
            self._seen[fingerprint] = current
            self._seen.move_to_end(fingerprint)
            while len(self._seen) > self.max_fingerprints:
                self._seen.popitem(last=False)
        return True


def request_id(candidate: str | None) -> str:
    """Accept a safe correlation ID or generate an opaque replacement."""
    value = (candidate or "").strip()
    return value if REQUEST_ID_PATTERN.fullmatch(value) else str(uuid.uuid4())


class JsonFormatter(logging.Formatter):
    """Emit stable single-line JSON suitable for container log collection."""

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, object] = {
            "timestamp": datetime.fromtimestamp(record.created, UTC).isoformat(),
            "level": record.levelname.lower(),
            "logger": record.name,
            "event": record.getMessage(),
        }
        for field in ("request_id", "method", "path", "status_code", "duration_ms"):
            value = getattr(record, field, None)
            if value is not None:
                payload[field] = value
        if record.exc_info:
            payload["exception"] = record.exc_info[0].__name__ if record.exc_info[0] else "Exception"
        return json.dumps(payload, ensure_ascii=False, separators=(",", ":"))


def configure_logging(logger_name: str = "autofb", level: int = logging.INFO) -> logging.Logger:
    logger = logging.getLogger(logger_name)
    if not any(getattr(handler, "_autofb_json", False) for handler in logger.handlers):
        handler = logging.StreamHandler()
        handler.setFormatter(JsonFormatter())
        handler._autofb_json = True  # type: ignore[attr-defined]
        logger.addHandler(handler)
    logger.setLevel(level)
    logger.propagate = False
    return logger


def report_unhandled_error(
    webhook_url: str,
    *,
    request_id_value: str,
    method: str,
    path: str,
    error_type: str,
    bearer_token: str | None = None,
    sender=None,
) -> bool:
    """Best-effort hosted error notification containing no exception message or request data."""
    if not webhook_url.startswith("https://"):
        return False
    payload = {
        "service": "autofb-api",
        "event": "api.unhandled_error",
        "request_id": request_id_value,
        "method": method,
        "path": path,
        "error_type": error_type,
        "occurred_at": datetime.now(UTC).isoformat(),
    }
    headers = {"Content-Type": "application/json"}
    if bearer_token:
        headers["Authorization"] = f"Bearer {bearer_token}"
    try:
        if sender is not None:
            response = sender(webhook_url, json=payload, headers=headers, timeout=3)
            status_code = response.status_code
        else:
            request = Request(
                webhook_url,
                data=json.dumps(payload).encode(),
                headers=headers,
                method="POST",
            )
            with closing(urlopen(request, timeout=3)) as response:
                status_code = response.status
    except Exception:
        return False
    return 200 <= status_code < 300
