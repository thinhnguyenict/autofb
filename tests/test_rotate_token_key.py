import tempfile
import unittest
from pathlib import Path

from autofb.web.database import Database
from tools.rotate_token_key import rotate_token_key


class RotateTokenKeyTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.database = Database(Path(self.directory.name) / "autofb.db")
        self.database.initialize()
        with self.database.connect() as connection:
            connection.execute("INSERT INTO users VALUES ('u1', 'u@example.com', 'hash', 'User', 'now')")
            connection.execute("INSERT INTO workspaces VALUES ('w1', 'Workspace', 'u1', 'now')")
            connection.execute(
                "INSERT INTO oauth_connections VALUES ('c1', 'w1', 'meta-user', 'Meta User', 'old:user-token', NULL, 'now')"
            )
            connection.execute(
                "INSERT INTO facebook_pages VALUES ('p1', 'w1', 'c1', 'meta-page', 'Page', 'old:page-token', 'now')"
            )

    def tokens(self):
        with self.database.connect() as connection:
            return (
                connection.execute("SELECT encrypted_access_token FROM oauth_connections").fetchone()[0],
                connection.execute("SELECT encrypted_access_token FROM facebook_pages").fetchone()[0],
            )

    def test_rotates_connection_and_page_tokens_atomically(self):
        report = rotate_token_key(
            self.database.path,
            lambda value: value.removeprefix("old:"),
            lambda value: f"new:{value}",
        )
        self.assertEqual(report, {"oauth_connections": 1, "facebook_pages": 1})
        self.assertEqual(self.tokens(), ("new:user-token", "new:page-token"))

    def test_bad_old_key_rolls_back_every_token(self):
        calls = 0

        def decrypt(value):
            nonlocal calls
            calls += 1
            if calls == 2:
                raise ValueError("invalid old key")
            return value.removeprefix("old:")

        with self.assertRaisesRegex(ValueError, "invalid old key"):
            rotate_token_key(self.database.path, decrypt, lambda value: f"new:{value}")
        self.assertEqual(self.tokens(), ("old:user-token", "old:page-token"))

    def test_rejects_missing_database(self):
        with self.assertRaises(FileNotFoundError):
            rotate_token_key(Path(self.directory.name) / "missing.db", str, str)


if __name__ == "__main__":
    unittest.main()
