"""Install the local FastAPI and Playwright developer-tool dependencies."""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path


def run(command: list[str]) -> None:
    print("+", " ".join(command), flush=True)
    completed = subprocess.run(command)
    if completed.returncode != 0:
        raise SystemExit(
            "Dependency bootstrap failed. Check package-index/proxy access, then rerun this command."
        )


def main() -> None:
    root = Path(__file__).resolve().parents[1]
    requirements = root / "reqs.txt"
    run([sys.executable, "-m", "pip", "install", "-r", str(requirements)])
    run([sys.executable, "-m", "playwright", "install", "chromium"])
    print("FastAPI and Playwright developer tools are ready")


if __name__ == "__main__":
    main()
