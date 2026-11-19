import unittest
from unittest.mock import patch
import pandas as pd

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

    def test_forming_candle_is_excluded_from_analysis_frame(self):
        now = pd.Timestamp.now(tz="UTC")
        current_open = now.floor("5min")
        frame = pd.DataFrame({
            "timestamp": [current_open - pd.Timedelta(minutes=5), current_open],
            "open": [10.0, 11.0], "high": [11.0, 12.0],
            "low": [9.0, 10.0], "close": [10.5, 11.5],
            "volume": [100.0, 200.0],
        })
        closed = App._closed_candles(frame, "5m")
        self.assertEqual(len(closed), 1)
        self.assertEqual(float(closed.iloc[-1].close), 10.5)

    def test_completed_candles_are_kept_in_analysis_frame(self):
        now = pd.Timestamp.now(tz="UTC")
        last_open = now.floor("5min") - pd.Timedelta(minutes=5)
        frame = pd.DataFrame({
            "timestamp": [last_open - pd.Timedelta(minutes=5), last_open],
            "open": [10.0, 11.0], "high": [11.0, 12.0],
            "low": [9.0, 10.0], "close": [10.5, 11.5],
            "volume": [100.0, 200.0],
        })
        closed = App._closed_candles(
            frame, "5m", exchange_now_ms=int(now.timestamp() * 1000)
        )
        self.assertEqual(len(closed), 2)

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
