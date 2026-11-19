import unittest
from unittest.mock import patch

import pandas as pd

from crypto_setup_analyzer import market_data
from ui.main_window import App


class ServerTimeTests(unittest.TestCase):
    def test_server_time_returns_valid_binance_timestamp(self):
        class Response:
            def raise_for_status(self):
                pass

            def json(self):
                return {"serverTime": 1_800_000_000_000}

        class Session:
            def __enter__(self):
                return self

            def __exit__(self, *args):
                return False

            def get(self, url, timeout):
                self.url = url
                self.timeout = timeout
                return Response()

        with patch.object(market_data.requests, "Session", return_value=Session()):
            self.assertEqual(market_data.server_time_ms(), 1_800_000_000_000)

    def test_server_time_rejects_invalid_payload(self):
        class Response:
            def raise_for_status(self):
                pass

            def json(self):
                return {"serverTime": "not-a-timestamp"}

        class Session:
            def __enter__(self):
                return self

            def __exit__(self, *args):
                return False

            def get(self, url, timeout):
                return Response()

        with patch.object(market_data.requests, "Session", return_value=Session()):
            with self.assertRaises(RuntimeError):
                market_data.server_time_ms()

    def test_closed_candle_cutoff_uses_exchange_time_not_local_clock(self):
        candles = pd.DataFrame({
            "timestamp": pd.to_datetime([
                "2026-01-01T00:00:00Z",
                "2026-01-01T00:01:00Z",
            ], utc=True),
            "open": [100.0, 101.0],
            "high": [101.0, 102.0],
            "low": [99.0, 100.0],
            "close": [100.5, 101.5],
            "volume": [1.0, 1.0],
        })
        before_close = int(pd.Timestamp("2026-01-01T00:01:30Z").timestamp() * 1000)
        after_close = int(pd.Timestamp("2026-01-01T00:02:01Z").timestamp() * 1000)

        with patch("ui.main_window.pd.Timestamp.now",
                   side_effect=AssertionError("local clock must not be consulted")):
            closed = App._closed_candles(candles, "1m", exchange_now_ms=before_close)
            complete = App._closed_candles(candles, "1m", exchange_now_ms=after_close)

        self.assertEqual(len(closed), 1)
        self.assertEqual(len(complete), 2)


if __name__ == "__main__":
    unittest.main()
