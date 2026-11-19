import unittest
from unittest.mock import patch

from ui.main_window import App


class FakeWindow:
    def __init__(self, exists=True):
        self.exists = exists
        self.calls = []

    def winfo_exists(self):
        return self.exists

    def deiconify(self):
        self.calls.append("deiconify")

    def lift(self):
        self.calls.append("lift")

    def focus_force(self):
        self.calls.append("focus")


class MainWindowScannerWindowTests(unittest.TestCase):
    def test_existing_scanner_window_is_reused(self):
        existing = type("ScannerWindow", (), {})()
        existing.window = FakeWindow(True)
        app = App.__new__(App)
        app.root = object()
        app._rebound_scanner_window = existing

        result = app.open_rebound_scanner()

        self.assertIs(result, existing)
        self.assertEqual(existing.window.calls, ["deiconify", "lift", "focus"])

    def test_destroyed_scanner_window_is_recreated(self):
        old = type("ScannerWindow", (), {})()
        old.window = FakeWindow(False)
        replacement = object()
        app = App.__new__(App)
        app.root = object()
        app._rebound_scanner_window = old

        with patch("ui.main_window.ReboundScannerWindow", return_value=replacement) as factory:
            result = app.open_rebound_scanner()

        self.assertIs(result, replacement)
        self.assertIs(app._rebound_scanner_window, replacement)
        factory.assert_called_once_with(app.root)


if __name__ == "__main__":
    unittest.main()
