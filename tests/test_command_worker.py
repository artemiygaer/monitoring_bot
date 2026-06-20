from __future__ import annotations

import unittest

from app.command_worker import build_host_command


class CommandWorkerTests(unittest.TestCase):
    def test_build_host_command_uses_chroot_without_mount_namespace(self) -> None:
        command = build_host_command("uname -a", "/hostfs")

        self.assertNotIn("--mount", command)
        self.assertEqual("nsenter", command[0])
        self.assertIn("chroot", command)
        self.assertEqual("/hostfs", command[command.index("chroot") + 1])
        self.assertEqual("/bin/sh", command[-3])
        self.assertEqual("-lc", command[-2])
        self.assertEqual("uname -a", command[-1])


if __name__ == "__main__":
    unittest.main()
