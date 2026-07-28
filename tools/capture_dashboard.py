"""Capture a real dashboard screenshot with a temporary local API when needed."""
from __future__ import annotations

import importlib.util
import os
import subprocess
import struct
import sys
import tempfile
import time
import urllib.error
import urllib.request
import zlib
from contextlib import contextmanager
from pathlib import Path
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parents[1]


def _png_chunk(kind: bytes, payload: bytes) -> bytes:
    checksum = zlib.crc32(kind + payload) & 0xFFFFFFFF
    return struct.pack(">I", len(payload)) + kind + payload + struct.pack(">I", checksum)


def _write_fallback_png(output: Path) -> None:
    width, height = 960, 540
    header = b"\x89PNG\r\n\x1a\n"
    ihdr = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)
    rows = []
    for y in range(height):
        row = bytearray([0])
        for x in range(width):
            in_card = 80 < x < 880 and 70 < y < 470
            if in_card:
                row.extend((255, 255, 255))
            elif y < 130:
                row.extend((23, 105, 224))
            else:
                row.extend((245, 247, 251))
        rows.append(bytes(row))
    output.write_bytes(header + _png_chunk(b"IHDR", ihdr) + _png_chunk(b"IDAT", zlib.compress(b"".join(rows))) + _png_chunk(b"IEND", b""))
    print(f"Fallback dashboard artifact written to {output}")


def _capture_with_playwright(url: str, output: Path) -> None:
    from playwright.sync_api import sync_playwright

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        page = browser.new_page(viewport={"width": 1440, "height": 1000})
        page.goto(url, wait_until="networkidle", timeout=30_000)
        page.locator("h1").wait_for(state="visible")
        page.screenshot(path=str(output), full_page=True)
        browser.close()
    print(f"Saved dashboard screenshot to {output}")


def _is_available(url: str) -> bool:
    try:
        with urllib.request.urlopen(url, timeout=2) as response:
            return response.status < 500
    except (OSError, urllib.error.URLError):
        return False


@contextmanager
def _dashboard_server(url: str):
    if _is_available(url):
        yield
        return
    parsed = urlparse(url)
    if parsed.hostname not in {"127.0.0.1", "localhost"}:
        raise RuntimeError(f"Dashboard is unavailable and cannot be started for remote host: {parsed.hostname}")
    port = parsed.port or 80
    with tempfile.TemporaryDirectory() as directory:
        environment = os.environ.copy()
        environment["AUTOFB_DATABASE_PATH"] = str(Path(directory) / "screenshot.db")
        environment["AUTOFB_MEDIA_DIR"] = str(Path(directory) / "media")
        process = subprocess.Popen(
            [sys.executable, "-m", "uvicorn", "autofb.web.api:app", "--host", "127.0.0.1", "--port", str(port)],
            env=environment,
            cwd=ROOT,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
            text=True,
        )
        try:
            deadline = time.monotonic() + 20
            while time.monotonic() < deadline:
                if _is_available(url):
                    break
                if process.poll() is not None:
                    error = process.stderr.read() if process.stderr else ""
                    raise RuntimeError(f"Temporary dashboard server exited early: {error.strip()}")
                time.sleep(0.25)
            else:
                raise RuntimeError("Temporary dashboard server did not become ready within 20 seconds")
            yield
        finally:
            process.terminate()
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=5)


def main() -> None:
    url = os.environ.get("AUTOFB_DASHBOARD_URL", "http://127.0.0.1:8001")
    output = Path(os.environ.get("AUTOFB_SCREENSHOT_PATH", "output/dashboard.png"))
    output.parent.mkdir(parents=True, exist_ok=True)

    if importlib.util.find_spec("playwright") is None:
        if os.environ.get("AUTOFB_SCREENSHOT_ALLOW_FALLBACK") == "1":
            _write_fallback_png(output)
            return
        raise SystemExit("Playwright is required for screenshots. Run `make bootstrap`, then retry.")
    with _dashboard_server(url):
        _capture_with_playwright(url, output)


if __name__ == "__main__":
    main()
