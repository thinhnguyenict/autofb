import os
import re
import subprocess
import tempfile
import unittest
from pathlib import Path


SCRIPT = Path(__file__).parents[1] / "deploy" / "install_ubuntu_24_04.sh"
REPOSITORY_INSTALLER = Path(__file__).parents[1] / "deploy" / "aapanel_ubuntu_24_04.sh"
COMPOSE_FILE = Path(__file__).parents[1] / "docker-compose.yml"
NGINX_CONFIG = Path(__file__).parents[1] / "deploy" / "nginx" / "tool.huongdancauca.com.conf"


class InteractiveInstallerTests(unittest.TestCase):
    def shell(self, expression):
        return subprocess.run(
            ["bash", "-c", f"source {SCRIPT!s}; {expression}"],
            check=False,
            capture_output=True,
            text=True,
        )

    def test_domain_validation(self):
        self.assertEqual(self.shell("validate_domain tool.example.com").returncode, 0)
        for value in ("https://tool.example.com", "localhost", "bad_domain.example.com", "-bad.example"):
            with self.subTest(value=value):
                self.assertNotEqual(self.shell(f"validate_domain {value!r}").returncode, 0)

    def test_port_validation(self):
        for value in ("1024", "8001", "65535"):
            self.assertEqual(self.shell(f"validate_port {value}").returncode, 0)
        for value in ("80", "0", "65536", "not-a-port"):
            self.assertNotEqual(self.shell(f"validate_port {value}").returncode, 0)

    def test_sourcing_installer_does_not_execute_installation(self):
        result = self.shell("printf loaded")
        self.assertEqual(result.returncode, 0)
        self.assertEqual(result.stdout, "loaded")

    def test_installer_supports_curl_command_substitution(self):
        result = subprocess.run(
            ["bash", "-c", SCRIPT.read_text()],
            check=False,
            capture_output=True,
            text=True,
        )

        self.assertNotEqual(result.returncode, 0)
        self.assertNotIn("BASH_SOURCE", result.stderr)
        self.assertIn("Error:", result.stderr)

    def test_repository_installer_has_valid_bash_syntax(self):
        result = subprocess.run(
            ["bash", "-n", REPOSITORY_INSTALLER],
            check=False,
            capture_output=True,
            text=True,
        )

        self.assertEqual(result.returncode, 0, result.stderr)

    def test_repository_installer_dry_run_writes_port_override(self):
        with tempfile.TemporaryDirectory() as app_dir:
            (Path(app_dir) / ".git").mkdir()
            env = os.environ | {
                "APP_DIR": app_dir,
                "AUTOFB_API_PORT": "8123",
                "DOMAIN": "tool.example.com",
                "DRY_RUN": "1",
            }
            result = subprocess.run(
                ["bash", REPOSITORY_INSTALLER],
                check=False,
                capture_output=True,
                text=True,
                env=env,
            )

            self.assertEqual(result.returncode, 0, result.stderr)
            override = (Path(app_dir) / "docker-compose.override.yml").read_text()
            self.assertEqual(override.count('"127.0.0.1:8123:8001"'), 1)
            self.assertNotIn("cat > docker-compose.override.yml", override)

    def test_repository_installer_preserves_existing_web_root(self):
        with tempfile.TemporaryDirectory() as working_dir:
            working_path = Path(working_dir)
            repository = working_path / "repository"
            app_dir = working_path / "web-root"
            repository.mkdir()
            app_dir.mkdir()
            (repository / "Dockerfile").write_text("FROM scratch\n")
            (app_dir / "existing-site-file.txt").write_text("keep me\n")
            subprocess.run(["git", "init", "-q", repository], check=True)
            subprocess.run(["git", "-C", repository, "add", "Dockerfile"], check=True)
            subprocess.run(
                [
                    "git", "-C", repository,
                    "-c", "user.name=Installer Test",
                    "-c", "user.email=installer@example.com",
                    "commit", "-qm", "fixture",
                ],
                check=True,
            )
            expression = (
                f"source {REPOSITORY_INSTALLER!s}; "
                f"APP_DIR={str(app_dir)!r}; REPO_URL={str(repository)!r}; "
                "checkout_or_update_repo"
            )

            result = subprocess.run(
                ["bash", "-c", expression],
                check=False,
                capture_output=True,
                text=True,
            )

            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual((app_dir / "existing-site-file.txt").read_text(), "keep me\n")
            self.assertTrue((app_dir / "Dockerfile").is_file())
            self.assertTrue((app_dir / ".git").is_dir())

    def test_repository_installer_moves_stale_root_index_aside(self):
        with tempfile.TemporaryDirectory() as working_dir:
            app_dir = Path(working_dir) / "web-root"
            app_dir.mkdir()
            stale_index = app_dir / "index.html"
            stale_index.write_text("stale aaPanel page\n")
            expression = (
                f"source {REPOSITORY_INSTALLER!s}; "
                f"APP_DIR={str(app_dir)!r}; "
                "quarantine_untracked_root_index"
            )

            result = subprocess.run(
                ["bash", "-c", expression],
                check=False,
                capture_output=True,
                text=True,
            )

            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertFalse(stale_index.exists())
            backups = list(app_dir.glob("index.html.aapanel-backup-*"))
            self.assertEqual(len(backups), 1)
            self.assertEqual(backups[0].read_text(), "stale aaPanel page\n")

    def test_repository_installer_keeps_tracked_root_index(self):
        with tempfile.TemporaryDirectory() as app_dir:
            app_path = Path(app_dir)
            (app_path / "index.html").write_text("tracked page\n")
            subprocess.run(["git", "init", "-q", app_path], check=True)
            subprocess.run(["git", "-C", app_path, "add", "index.html"], check=True)
            subprocess.run(
                [
                    "git", "-C", app_path,
                    "-c", "user.name=Installer Test",
                    "-c", "user.email=installer@example.com",
                    "commit", "-qm", "fixture",
                ],
                check=True,
            )
            expression = (
                f"source {REPOSITORY_INSTALLER!s}; "
                f"APP_DIR={str(app_path)!r}; "
                "quarantine_untracked_root_index"
            )

            result = subprocess.run(
                ["bash", "-c", expression],
                check=False,
                capture_output=True,
                text=True,
            )

            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual((app_path / "index.html").read_text(), "tracked page\n")
            self.assertEqual(list(app_path.glob("index.html.aapanel-backup-*")), [])

    def test_compose_file_has_no_duplicate_mapping_keys(self):
        stack = []
        seen = set()
        for line_number, line in enumerate(COMPOSE_FILE.read_text().splitlines(), 1):
            match = re.match(r"^(\s*)([A-Za-z0-9_.-]+):(?:\s|$)", line)
            if not match:
                continue
            indent = len(match.group(1))
            key = match.group(2)
            while stack and indent <= stack[-1][0]:
                stack.pop()
            location = (tuple(parent_key for _, parent_key in stack), key)
            self.assertNotIn(location, seen, f"duplicate mapping key {key!r} on line {line_number}")
            seen.add(location)
            stack.append((indent, key))

    def test_nginx_example_proxies_every_application_route(self):
        config = NGINX_CONFIG.read_text()

        self.assertIn("proxy_pass http://127.0.0.1:8001;", config)
        self.assertIn("proxy_set_header Host $host;", config)
        self.assertIn("proxy_set_header X-Forwarded-Proto $scheme;", config)
        self.assertEqual(config.count("proxy_pass "), 1)
        self.assertNotIn("enable-php", config)
        self.assertNotIn("/nginx/proxy/", config)


if __name__ == "__main__":
    unittest.main()
