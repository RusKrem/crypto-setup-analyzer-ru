import tempfile
import unittest
from pathlib import Path

from crypto_setup_analyzer.signal_card import render_signal_card


class SignalCardTests(unittest.TestCase):
    def setUp(self):
        self.candles = []
        price = 0.0755
        for i in range(25):
            opening = price
            price += (0.00002 if i % 2 else -0.00001)
            high = max(opening, price) + 0.00003
            low = min(opening, price) - 0.00002
            self.candles.append([i * 60000, opening, high, low, price, 100, 0, 0, 0, 0, 0, 0])

    def test_approach_card_is_created(self):
        signal = {
            "symbol": "DOGEUSDT", "level_name": "Today Low",
            "level_group": "Текущий день", "level": 0.07532,
            "price": 0.07568, "distance_pct": 0.478, "direction": "LONG"
        }
        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp) / "approach.png"
            render_signal_card(signal, self.candles, "APPROACH", str(output))
            self.assertTrue(output.is_file())
            self.assertGreater(output.stat().st_size, 20_000)

    def test_empty_or_missing_candles_are_rejected(self):
        signal = {"symbol": "DOGEUSDT", "level": 0.07532, "price": 0.07568}
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(ValueError):
                render_signal_card(signal, [], "APPROACH", str(Path(tmp) / "empty.png"))

    def test_confirmation_card_is_created(self):
        rejection = [25 * 60000, 0.07545, 0.07560, 0.07520, 0.07555,
                     120, 26 * 60000 - 1, 0, 0, 0, 0, 0]
        candles = self.candles + [rejection]
        signal = {
            "symbol": "DOGEUSDT", "level_name": "Today Low",
            "level_group": "Текущий день", "level": 0.07532,
            "price": 0.07555, "distance_pct": 0.305, "direction": "LONG",
            "wick_body_ratio": 2.5, "close_position": 0.875,
            "candle_open_time": 25 * 60000,
            "candle_open": 0.07545, "candle_high": 0.07560,
            "candle_low": 0.07520, "candle_close": 0.07555
        }
        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp) / "confirmed.png"
            render_signal_card(signal, candles, "CONFIRMED", str(output))
            self.assertTrue(output.is_file())
            self.assertGreater(output.stat().st_size, 20_000)


if __name__ == "__main__":
    unittest.main()
