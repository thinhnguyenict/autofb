import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from tools import capture_dashboard


class CaptureDashboardTests(unittest.TestCase):
    def test_missing_playwright_fails_instead_of_silently_faking_screenshot(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "dashboard.png"
            environment = {"AUTOFB_SCREENSHOT_PATH": str(output)}
            with patch.dict(capture_dashboard.os.environ, environment, clear=True):
                with patch("tools.capture_dashboard.importlib.util.find_spec", return_value=None):
                    with self.assertRaisesRegex(SystemExit, "Playwright is required"):
                        capture_dashboard.main()
            self.assertFalse(output.exists())

    def test_fallback_requires_explicit_opt_in(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "dashboard.png"
            environment = {
                "AUTOFB_SCREENSHOT_PATH": str(output),
                "AUTOFB_SCREENSHOT_ALLOW_FALLBACK": "1",
            }
            with patch.dict(capture_dashboard.os.environ, environment, clear=True):
                with patch("tools.capture_dashboard.importlib.util.find_spec", return_value=None):
                    capture_dashboard.main()
            self.assertTrue(output.read_bytes().startswith(b"\x89PNG"))


if __name__ == "__main__":
    unittest.main()
