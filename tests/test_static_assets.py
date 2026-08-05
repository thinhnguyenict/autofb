import subprocess
import unittest
from html.parser import HTMLParser
from pathlib import Path


ROOT = Path(__file__).parents[1]
INDEX = ROOT / "autofb" / "web" / "static" / "index.html"
APP_JS = ROOT / "autofb" / "web" / "static" / "app.js"


class IdCollector(HTMLParser):
    def __init__(self):
        super().__init__()
        self.ids = []

    def handle_starttag(self, tag, attrs):
        attributes = dict(attrs)
        if "id" in attributes:
            self.ids.append(attributes["id"])


class StaticAssetTests(unittest.TestCase):
    def test_index_has_unique_ids_and_single_auth_section(self):
        parser = IdCollector()
        parser.feed(INDEX.read_text())

        duplicates = {value for value in parser.ids if parser.ids.count(value) > 1}
        self.assertEqual(duplicates, set())
        self.assertEqual(parser.ids.count("auth"), 1)
        self.assertEqual(parser.ids.count("app"), 1)

    def test_index_loads_assets_through_api_prefix(self):
        index = INDEX.read_text()

        self.assertIn('/api/v1/static/app.css', index)
        self.assertIn('/api/v1/static/app.js', index)
        self.assertNotIn('href="/static/app.css', index)
        self.assertNotIn('src="/static/app.js', index)

    def test_frontend_javascript_has_valid_syntax(self):
        result = subprocess.run(
            ["node", "--check", APP_JS],
            check=False,
            capture_output=True,
            text=True,
        )

        self.assertEqual(result.returncode, 0, result.stderr)


if __name__ == "__main__":
    unittest.main()
