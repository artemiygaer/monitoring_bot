from __future__ import annotations

import unittest

from app.keyboards import (
    ACTION_CONFIRM_BACKUP,
    ACTION_CONFIRM_CLEANUP,
    ACTION_CONFIRM_DELETE_BACKUP,
    ACTION_CONTAINER_LOGS,
    ACTION_CONTAINER_STATS,
    ACTION_CREATE_BACKUP,
    ACTION_DELETE_BACKUP,
    ACTION_DOWNLOAD_BACKUP,
    ACTION_RESTART_CONTAINER,
    ACTION_SERVICE_CONTAINERS,
    ACTION_SERVICE_LOGS,
    ACTION_SERVICE_STATS,
    MENU_ABOUT,
    MENU_BACKUP,
    MENU_CLEANUP,
    MENU_CONTAINERS,
    MENU_FAILED_LOGINS,
    MENU_RESOURCES,
    MENU_SYSTEM,
    build_backup_archive_menu,
    build_backup_confirm_menu,
    build_backup_delete_confirm_menu,
    build_backup_menu,
    build_cleanup_confirm_menu,
    build_container_detail_menu,
    build_main_menu,
    build_service_detail_menu,
    build_system_menu,
)


def keyboard_texts(markup) -> list[str]:
    return [button.text for row in markup.keyboard for button in row]


class KeyboardTests(unittest.TestCase):
    def test_service_detail_menu_contains_context_actions(self) -> None:
        markup = build_service_detail_menu()
        texts = keyboard_texts(markup)

        self.assertIn(ACTION_SERVICE_LOGS, texts)
        self.assertIn(ACTION_SERVICE_STATS, texts)
        self.assertIn(ACTION_SERVICE_CONTAINERS, texts)

    def test_container_detail_menu_contains_context_actions(self) -> None:
        markup = build_container_detail_menu()
        texts = keyboard_texts(markup)

        self.assertIn(ACTION_CONTAINER_LOGS, texts)
        self.assertIn(ACTION_CONTAINER_STATS, texts)
        self.assertIn(ACTION_RESTART_CONTAINER, texts)

    def test_main_menu_contains_backup_action(self) -> None:
        markup = build_main_menu()
        texts = keyboard_texts(markup)

        self.assertIn(MENU_BACKUP, texts)
        self.assertIn(MENU_CONTAINERS, texts)
        self.assertIn(MENU_RESOURCES, texts)
        self.assertIn(MENU_SYSTEM, texts)
        self.assertNotIn(MENU_FAILED_LOGINS, texts)
        self.assertNotIn(MENU_CLEANUP, texts)
        self.assertNotIn(MENU_ABOUT, texts)
        self.assertNotIn("Сервисы", texts)
        self.assertNotIn("Логи", texts)
        self.assertNotIn("Статистика", texts)

    def test_system_menu_contains_secondary_actions(self) -> None:
        markup = build_system_menu()
        texts = keyboard_texts(markup)

        self.assertIn(MENU_FAILED_LOGINS, texts)
        self.assertIn(MENU_CLEANUP, texts)
        self.assertIn(MENU_ABOUT, texts)

    def test_backup_confirm_menu_contains_confirm_action(self) -> None:
        markup = build_backup_confirm_menu()
        texts = keyboard_texts(markup)

        self.assertIn(ACTION_CONFIRM_BACKUP, texts)

    def test_backup_menu_contains_archive_actions(self) -> None:
        markup = build_backup_menu()
        texts = keyboard_texts(markup)

        self.assertIn(ACTION_CREATE_BACKUP, texts)
        self.assertIn(ACTION_DOWNLOAD_BACKUP, texts)
        self.assertIn(ACTION_DELETE_BACKUP, texts)

    def test_backup_archive_menu_contains_archive_options(self) -> None:
        markup = build_backup_archive_menu(["backup-a.tar", "backup-b.tar"])
        texts = keyboard_texts(markup)

        self.assertIn("backup-a.tar", texts)
        self.assertIn("backup-b.tar", texts)

    def test_backup_delete_confirm_menu_contains_confirm_action(self) -> None:
        markup = build_backup_delete_confirm_menu()
        texts = keyboard_texts(markup)

        self.assertIn(ACTION_CONFIRM_DELETE_BACKUP, texts)

    def test_cleanup_confirm_menu_contains_confirm_action(self) -> None:
        markup = build_cleanup_confirm_menu()
        texts = keyboard_texts(markup)

        self.assertIn(ACTION_CONFIRM_CLEANUP, texts)


if __name__ == "__main__":
    unittest.main()
