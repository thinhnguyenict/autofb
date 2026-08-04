import os
import subprocess
import tempfile
import unittest
from pathlib import Path


SCRIPT = Path(__file__).parents[1] / "deploy" / "install_ubuntu_24_04.sh"
REPOSITORY_INSTALLER = Path(__file__).parents[1] / "deploy" / "aapanel_ubuntu_24_04.sh"


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


if __name__ == "__main__":
    unittest.main()
