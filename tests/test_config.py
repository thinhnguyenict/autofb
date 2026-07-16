import json
import tempfile
import unittest
from pathlib import Path

from autofb.config import ConfigError, load_config


class LoadConfigTests(unittest.TestCase):
    def write_config(self, payload):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        path = Path(directory.name) / "config.json"
        path.write_text(json.dumps(payload), encoding="utf-8")
        return path

    def payload(self):
        return {
            "excel": {"path": "data.xlsx", "caption_file": "caption.xlsx"},
            "pages": {
                "page_id": ["page-a"],
                "access_token": ["token-a"],
                "page_name": ["Page A"],
                "act_id": "act_1",
            },
        }

    def test_loads_valid_configuration(self):
        config = load_config(self.write_config(self.payload()))
        self.assertEqual(config.pages.page_tokens(), (("page-a", "token-a"),))
        self.assertEqual(config.excel.caption_file, "caption.xlsx")

    def test_rejects_misaligned_page_token_lists(self):
        payload = self.payload()
        payload["pages"]["access_token"].append("token-b")
        with self.assertRaisesRegex(ConfigError, "same length"):
            load_config(self.write_config(payload))

    def test_rejects_missing_required_excel_path(self):
        payload = self.payload()
        payload["excel"]["path"] = ""
        with self.assertRaisesRegex(ConfigError, "excel.path"):
            load_config(self.write_config(payload))


if __name__ == "__main__":
    unittest.main()
