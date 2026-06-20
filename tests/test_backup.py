from __future__ import annotations

import unittest
from datetime import datetime, timezone
from pathlib import Path
from tempfile import TemporaryDirectory
import os

from app.backup import build_backup_command, build_delete_backup_command, list_backup_archives


class BackupCommandTests(unittest.TestCase):
    def test_build_backup_command_archives_root_dir_to_backup_dir(self) -> None:
        command = build_backup_command(datetime(2026, 5, 2, 19, 30, 45, tzinfo=timezone.utc))

        self.assertEqual("/root", command.source_dir)
        self.assertEqual("/backup", command.target_dir)
        self.assertEqual("root-backup-20260502-193045.tar.gz", command.archive_name)
        self.assertEqual("/backup/root-backup-20260502-193045.tar.gz", command.archive_path)
        self.assertIn("mkdir -p /backup", command.command)
        self.assertIn("tar -czf /backup/root-backup-20260502-193045.tar.gz -C /root .", command.command)
        self.assertIn("Недостаточно свободного места для бекапа", command.command)

    def test_build_backup_command_requires_absolute_paths(self) -> None:
        with self.assertRaises(ValueError):
            build_backup_command(datetime.now(timezone.utc), source_dir="root")

    def test_list_backup_archives_reads_tar_files_from_hostfs(self) -> None:
        with TemporaryDirectory() as temp_dir:
            hostfs_root = Path(temp_dir)
            backup_dir = hostfs_root / "backup"
            backup_dir.mkdir()
            first_archive = backup_dir / "root-backup-20260502-193045.tar"
            second_archive = backup_dir / "root-backup-20260502-193500.tar.gz"
            ignored_file = backup_dir / "notes.txt"
            first_archive.write_bytes(b"first")
            second_archive.write_bytes(b"second archive")
            ignored_file.write_text("ignore", encoding="utf-8")
            os.utime(first_archive, (1000, 1000))
            os.utime(second_archive, (2000, 2000))

            archives = list_backup_archives(
                target_dir="/backup",
                hostfs_root=str(hostfs_root),
                timezone_info=timezone.utc,
            )

        self.assertEqual(
            ["root-backup-20260502-193500.tar.gz", "root-backup-20260502-193045.tar"],
            [archive.name for archive in archives],
        )
        self.assertEqual([14, 5], [archive.size_bytes for archive in archives])
        self.assertEqual("/backup/root-backup-20260502-193500.tar.gz", archives[0].host_path)

    def test_build_delete_backup_command_rejects_path_traversal(self) -> None:
        with self.assertRaises(ValueError):
            build_delete_backup_command("../root-backup.tar")

    def test_build_delete_backup_command_removes_selected_archive(self) -> None:
        command = build_delete_backup_command("root-backup-20260502-193045.tar.gz", target_dir="/backup")

        self.assertEqual("/backup/root-backup-20260502-193045.tar.gz", command.archive_path)
        self.assertIn("rm -f -- /backup/root-backup-20260502-193045.tar.gz", command.command)


if __name__ == "__main__":
    unittest.main()
