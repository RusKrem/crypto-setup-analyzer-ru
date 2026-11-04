"""Быстрые проверки сервисного слоя без сети и графического интерфейса."""
import unittest
import pandas as pd
from services.indicator_service import IndicatorService
from services.market_data_service import MarketDataService


class ArchitectureTests(unittest.TestCase):
    def test_indicator_service_accepts_candle_frame(self):
        n = 80
        timestamps = pd.date_range("2026-01-01", periods=n, freq="5min", tz="UTC")
        close = [100 + i * 0.05 + (2 if i % 9 == 0 else 0) for i in range(n)]
        frame = pd.DataFrame({
            "timestamp": timestamps,
            "open": [c - 0.1 for c in close],
            "high": [c + 0.5 for c in close],
            "low": [c - 0.5 for c in close],
            "close": close,
            "volume": [1000.0 + i for i in range(n)],
        })
        service = IndicatorService()
        levels = service.add_levels(frame)
        self.assertIn("PDH", levels.columns)
        self.assertIn("PDL", levels.columns)
        self.assertIsInstance(service.find_events(levels), pd.DataFrame)
        self.assertIsInstance(service.find_price_reactions(levels), pd.DataFrame)
        self.assertIsInstance(service.find_order_blocks(levels), pd.DataFrame)
        self.assertIsInstance(service.find_market_structure(levels), pd.DataFrame)

    def test_market_service_is_api_facade(self):
        service = MarketDataService()
        self.assertTrue(callable(service.download_history))
        self.assertTrue(callable(service.latest_candles))
        self.assertTrue(callable(service.load_csv))


if __name__ == "__main__":
    unittest.main()
