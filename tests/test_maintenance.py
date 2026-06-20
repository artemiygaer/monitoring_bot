from __future__ import annotations

import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from app.maintenance import build_cleanup_command, list_cleanup_candidates


class MaintenanceTests(unittest.TestCase):
    def test_build_cleanup_command_targets_configured_path(self) -> None:
        command = build_cleanup_command("/opt/monitoring-bot")

        self.assertEqual("/opt/monitoring-bot", command.cleanup_path)
        self.assertIn("find \"$cleanup_root\" -type d", command.command)
        self.assertIn("-name __pycache__", command.command)
        self.assertIn("-name .pytest_cache", command.command)
        self.assertIn("-name 'tmp*'", command.command)

    def test_build_cleanup_command_requires_absolute_path(self) -> None:
        with self.assertRaises(ValueError):
            build_cleanup_command("relative/path")

    def test_list_cleanup_candidates_counts_size_from_hostfs(self) -> None:
        with TemporaryDirectory() as temp_dir:
            hostfs_root = Path(temp_dir)
            project_root = hostfs_root / "opt" / "monitoring-bot"
            cache_dir = project_root / "app" / "__pycache__"
            pytest_dir = project_root / ".pytest_cache"
            tmp_dir = project_root / "tmpabc"
            cache_dir.mkdir(parents=True)
            pytest_dir.mkdir()
            tmp_dir.mkdir()
            (cache_dir / "a.pyc").write_bytes(b"12345")
            (pytest_dir / "state").write_bytes(b"12")
            (tmp_dir / "file").write_bytes(b"123")

            candidates = list_cleanup_candidates(
                "/opt/monitoring-bot",
                hostfs_root=str(hostfs_root),
            )

        self.assertEqual(
            ["/opt/monitoring-bot/.pytest_cache", "/opt/monitoring-bot/app/__pycache__", "/opt/monitoring-bot/tmpabc"],
            [candidate.path for candidate in candidates],
        )
        self.assertEqual([2, 5, 3], [candidate.size_bytes for candidate in candidates])


if __name__ == "__main__":
    unittest.main()
