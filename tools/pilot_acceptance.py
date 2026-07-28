#!/usr/bin/env python3
"""Verify the externally deployed API gates required for a controlled pilot."""
from __future__ import annotations

import argparse
import json
import os
from contextlib import closing
from urllib.parse import urlparse
from urllib.request import Request, urlopen


class PilotAcceptanceError(ValueError):
    pass


EXPECTED_STATUS = {
    "/healthz": "ok",
    "/readyz": "ready",
    "/workerz": "ready",
    "/backupz": "ready",
}


def validate_base_url(base_url: str, *, allow_insecure_http: bool = False) -> str:
    parsed = urlparse(base_url.strip())
    allowed_scheme = parsed.scheme == "https" or (allow_insecure_http and parsed.scheme == "http")
    if not allowed_scheme or not parsed.netloc:
        raise PilotAcceptanceError("Pilot URL must use HTTPS")
    if not allow_insecure_http and (parsed.hostname or "").lower() in {"localhost", "127.0.0.1", "::1"}:
        raise PilotAcceptanceError("Pilot URL must use a public host")
    if parsed.username is not None or parsed.password is not None:
        raise PilotAcceptanceError("Pilot URL cannot contain credentials")
    if parsed.query or parsed.fragment or parsed.path not in {"", "/"}:
        raise PilotAcceptanceError("Pilot URL must contain only the deployment origin")
    return f"{parsed.scheme}://{parsed.netloc}"


def pilot_acceptance(
    base_url: str,
    *,
    allow_insecure_http: bool = False,
    opener=urlopen,
) -> dict[str, object]:
    """Probe public health gates without returning URLs, bodies, or credentials."""
    origin = validate_base_url(base_url, allow_insecure_http=allow_insecure_http)
    checks: dict[str, str] = {}
    for path, expected in EXPECTED_STATUS.items():
        try:
            request = Request(f"{origin}{path}", headers={"Accept": "application/json"})
            with closing(opener(request, timeout=5)) as response:
                if response.status != 200:
                    checks[path] = "error"
                    continue
                payload = json.loads(response.read(65537))
                checks[path] = "ok" if payload.get("status") == expected else "error"
        except (OSError, ValueError, json.JSONDecodeError):
            checks[path] = "error"
    failed = sorted(path for path, value in checks.items() if value != "ok")
    return {"status": "passed" if not failed else "failed", "checks": checks, "failed_checks": failed}


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(description="Verify a deployed AutoFB single-VPS pilot.")
    result.add_argument("--url", default=os.environ.get("AUTOFB_PUBLIC_URL", ""))
    result.add_argument("--allow-insecure-http", action="store_true")
    return result


def main() -> int:
    args = parser().parse_args()
    if not args.url:
        raise SystemExit("AUTOFB_PUBLIC_URL or --url is required")
    report = pilot_acceptance(args.url, allow_insecure_http=args.allow_insecure_http)
    print(json.dumps(report, sort_keys=True))
    return 0 if report["status"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
