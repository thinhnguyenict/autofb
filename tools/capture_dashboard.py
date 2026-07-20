"""Capture a dashboard screenshot, with a dependency-free fallback artifact."""
from __future__ import annotations

import importlib.util
import os
import struct
import zlib
from pathlib import Path


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
    print(f"Playwright is not installed; wrote fallback dashboard artifact to {output}")


def _capture_with_playwright(url: str, output: Path) -> None:
    from playwright.sync_api import sync_playwright

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        page = browser.new_page(viewport={"width": 1440, "height": 1000})
        page.goto(url, wait_until="networkidle")
        page.screenshot(path=str(output), full_page=True)
        browser.close()
    print(f"Saved dashboard screenshot to {output}")


def main() -> None:
    url = os.environ.get("AUTOFB_DASHBOARD_URL", "http://127.0.0.1:8001")
    output = Path(os.environ.get("AUTOFB_SCREENSHOT_PATH", "output/dashboard.png"))
    output.parent.mkdir(parents=True, exist_ok=True)

    if importlib.util.find_spec("playwright") is None:
        _write_fallback_png(output)
        return
    _capture_with_playwright(url, output)


if __name__ == "__main__":
    main()
