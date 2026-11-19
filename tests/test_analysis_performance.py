import unittest
import pandas as pd

from crypto_setup_analyzer.analysis import _build_first_crossing_lookup, find_order_blocks


class FirstCrossingLookupTests(unittest.TestCase):
    def test_minimum_lookup_returns_first_value_at_or_below_threshold(self):
        values = [8, 7, 9, 5, 6, 3, 4]
        first = _build_first_crossing_lookup(values, "min")
        self.assertEqual(first(2, 6), 3)
        self.assertEqual(first(4, 3), 5)
        self.assertIsNone(first(6, 2))
        self.assertIsNone(first(len(values), 100))

    def test_maximum_lookup_returns_first_value_at_or_above_threshold(self):
        values = [2, 4, 3, 8, 5, 9, 1]
        first = _build_first_crossing_lookup(values, "max")
        self.assertEqual(first(2, 7), 3)
        self.assertEqual(first(4, 9), 5)
        self.assertIsNone(first(6, 10))

    def test_lookup_matches_naive_search_for_multiple_thresholds(self):
        values = [9, 4, 8, 3, 7, 2, 6, 1, 5]
        for mode in ("min", "max"):
            first = _build_first_crossing_lookup(values, mode)
            for start in range(len(values) + 1):
                for threshold in range(1, 11):
                    if mode == "min":
                        expected = next((i for i in range(start, len(values))
                                         if values[i] <= threshold), None)
                    else:
                        expected = next((i for i in range(start, len(values))
                                         if values[i] >= threshold), None)
                    self.assertEqual(first(start, threshold), expected)

    def test_order_block_reports_first_invalidation_candle(self):
        rows = [
            (10, 11, 9, 10),
            (10, 10.5, 8.5, 9),  # Last bearish candle before displacement.
            (9, 11, 9, 10),
            (10, 11, 9, 10),
            (10, 14, 9, 13),     # Bullish structure break.
            (9, 10, 8, 9),       # First candle that invalidates the OB.
            (9, 10, 8.8, 9.5),
        ]
        frame = pd.DataFrame([
            {"timestamp": pd.Timestamp("2026-01-01", tz="UTC") + pd.Timedelta(minutes=i),
             "open": o, "high": h, "low": low, "close": c, "volume": 1}
            for i, (o, h, low, c) in enumerate(rows)
        ])
        blocks = find_order_blocks(
            frame, structure_lookback=2, search_back=3,
            atr_period=3, displacement_atr=0.1,
        )
        self.assertFalse(blocks.empty)
        block = blocks[blocks.break_index == 4].iloc[0]
        self.assertTrue(block.invalidated)
        self.assertEqual(int(block.invalidated_index), 5)
        self.assertEqual(block.invalidated_time, frame.iloc[5].timestamp)

    def test_invalid_lookup_mode_is_rejected(self):
        with self.assertRaises(ValueError):
            _build_first_crossing_lookup([1, 2, 3], "median")


if __name__ == "__main__":
    unittest.main()
