from __future__ import annotations

import unittest

from app.navigation import NavigationHistory, ViewState


class NavigationTests(unittest.TestCase):
    def test_refresh_preserves_current_screen_and_page(self) -> None:
        navigation = NavigationHistory()
        navigation.open("services")
        navigation.open("service", page=2, payload="token")

        self.assertEqual(ViewState("service", page=2, payload="token"), navigation.refresh())

    def test_back_returns_to_explicit_previous_screen(self) -> None:
        navigation = NavigationHistory()
        navigation.open("services")
        navigation.open("service", payload="service-token")
        navigation.open("containers", payload="service-token")

        self.assertEqual(ViewState("service", payload="service-token"), navigation.back())
        self.assertEqual(ViewState("services"), navigation.back())
        self.assertEqual(ViewState("home"), navigation.back())

    def test_page_change_does_not_add_back_step(self) -> None:
        navigation = NavigationHistory()
        navigation.open("containers")
        navigation.open("containers", page=1, remember=False)

        self.assertEqual(ViewState("home"), navigation.back())
