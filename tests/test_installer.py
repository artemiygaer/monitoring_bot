from __future__ import annotations

import os
import stat
import subprocess
import tempfile
import unittest
from pathlib import Path


DUMMY_TOKEN = "123456:" + "x" * 24


class InstallerTests(unittest.TestCase):
    def setUp(self) -> None:
        self.repo = Path(__file__).parents[1]
        self.temp_dir = tempfile.TemporaryDirectory(dir=self.repo)
        self.install_dir = Path(self.temp_dir.name)
        self.relative_dir = self.install_dir.relative_to(self.repo).as_posix()

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def run_installer(self, **overrides: str) -> subprocess.CompletedProcess[str]:
        environment = os.environ.copy()
        environment.update(overrides)
        return subprocess.run(
            [
                "bash",
                "install.sh",
                "--config-only",
                "--non-interactive",
                "--install-dir",
                self.relative_dir,
            ],
            cwd=self.repo,
            env=environment,
            text=True,
            encoding="utf-8",
            errors="replace",
            capture_output=True,
            check=False,
        )

    def test_config_only_is_redacted_idempotent_and_preserves_unknown_key(self) -> None:
        env_path = self.install_dir / ".env"
        env_path.write_text(
            "\n".join(
                [
                    "CUSTOM_OPTION=keep-me",
                    f"BOT_TOKEN={DUMMY_TOKEN}",
                    "ALLOWED_USER_IDS=123456789",
                    "MONITOR_SERVER_NAME=old",
                    "MONITOR_SERVER_NAME=duplicate",
                    "MONITOR_TIMEZONE=UTC",
                    "",
                ]
            ),
            encoding="utf-8",
        )

        first = self.run_installer()
        second_overrides = (
            {"MONITOR_INSTALL_SERVER_NAME": "new-server"} if os.name != "nt" else {}
        )
        second = self.run_installer(**second_overrides)

        self.assertEqual(0, first.returncode, first.stderr)
        self.assertEqual(0, second.returncode, second.stderr)
        self.assertNotIn(DUMMY_TOKEN, first.stdout + first.stderr)
        self.assertIn("значение скрыто", first.stdout)
        content = env_path.read_text(encoding="utf-8")
        self.assertIn("CUSTOM_OPTION=keep-me", content)
        self.assertEqual(1, content.count("MONITOR_SERVER_NAME="))
        expected_server = "new-server" if os.name != "nt" else "old"
        self.assertIn(f"MONITOR_SERVER_NAME={expected_server}", content)
        self.assertGreaterEqual(len(list(self.install_dir.glob(".env.backup-*"))), 2)
        if os.name != "nt":
            self.assertEqual(0o600, stat.S_IMODE(env_path.stat().st_mode))

    def test_invalid_ids_fail_with_clear_message(self) -> None:
        (self.install_dir / ".env").write_text(
            "\n".join(
                [
                    f"BOT_TOKEN={DUMMY_TOKEN}",
                    "ALLOWED_USER_IDS=not-a-number",
                    "MONITOR_SERVER_NAME=test-server",
                    "MONITOR_TIMEZONE=UTC",
                    "",
                ]
            ),
            encoding="utf-8",
        )
        result = self.run_installer()

        self.assertNotEqual(0, result.returncode)
        self.assertIn("ID должны быть числами", result.stderr)

    def test_github_bootstrap_downloads_release_files_and_starts_installer(self) -> None:
        release_dir = self.install_dir / "release"
        target_dir = self.install_dir / "target"
        release_dir.mkdir()
        release_files = {
            "install.sh": "#!/usr/bin/env bash\nset -e\ntouch github-bootstrap-called\n",
            "deploy.sh": "#!/usr/bin/env bash\nset -e\n",
            "docker-compose.bot.yml": "services: {}\n",
            "default.env.example": "BOT_TOKEN=\nALLOWED_USER_IDS=\n",
        }
        for name, content in release_files.items():
            (release_dir / name).write_text(content, encoding="utf-8", newline="\n")

        result = subprocess.run(
            [
                "bash",
                "-c",
                (
                    f'MONITOR_INSTALL_DIR="$PWD/{self.relative_dir}/target" '
                    f'MONITOR_GITHUB_RELEASE_BASE="file://$PWD/{self.relative_dir}/release" '
                    "MONITOR_INSTALL_SOURCE=ghcr "
                    "bash ./install-from-github.sh"
                ),
            ],
            cwd=self.repo,
            text=True,
            encoding="utf-8",
            errors="replace",
            capture_output=True,
            check=False,
        )

        self.assertEqual(0, result.returncode, result.stderr)
        self.assertTrue((target_dir / "github-bootstrap-called").is_file())
        for name in ("install.sh", "deploy.sh", "docker-compose.bot.yml", ".env.example"):
            self.assertTrue((target_dir / name).is_file(), name)
        self.assertFalse((target_dir / "default.env.example").exists())


if __name__ == "__main__":
    unittest.main()
