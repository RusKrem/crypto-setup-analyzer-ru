import unittest

import pandas as pd

from crypto_setup_analyzer.analysis import (
    calculate_reference_levels,
    retain_live_history_depth,
)


class ReferenceLevelTests(unittest.TestCase):
    def make_history(self):
        # 15-minute candles across several weeks. The latest 300 candles do not
        # contain the full previous week, while the full frame does.
        timestamps = pd.date_range(
            "2026-10-19 00:00:00+00:00",
            "2026-11-09 12:00:00+00:00",
            freq="15min",
            inclusive="left",
        )
        frame = pd.DataFrame({
            "timestamp": timestamps,
            "open": 100.0,
            "high": 101.0,
            "low": 99.0,
            "close": 100.0,
            "volume": 1.0,
        })
        # Previous complete week: 2–8 November. Put its true extremes early
        # enough that they are outside the last-300-candle chart viewport.
        frame.loc[frame.timestamp == pd.Timestamp("2026-11-02 01:00:00+00:00"), "high"] = 150.0
        frame.loc[frame.timestamp == pd.Timestamp("2026-11-03 01:00:00+00:00"), "low"] = 50.0
        frame.loc[frame.timestamp == pd.Timestamp("2026-11-08 23:45:00+00:00"), "close"] = 125.0
        # Previous complete day: 8 November.
        frame.loc[frame.timestamp == pd.Timestamp("2026-11-08 02:00:00+00:00"), "high"] = 120.0
        frame.loc[frame.timestamp == pd.Timestamp("2026-11-08 03:00:00+00:00"), "low"] = 80.0
        # Current day: 9 November, with a partial but day-start-complete history.
        frame.loc[frame.timestamp == pd.Timestamp("2026-11-09 01:00:00+00:00"), "high"] = 130.0
        frame.loc[frame.timestamp == pd.Timestamp("2026-11-09 02:00:00+00:00"), "low"] = 70.0
        return frame

    def test_levels_use_full_history_not_last_300_candles(self):
        frame = self.make_history()
        levels = calculate_reference_levels(frame)
        visible_only_levels = calculate_reference_levels(frame.tail(300))

        self.assertEqual(levels["PWH"], 150.0)
        self.assertEqual(levels["PWL"], 50.0)
        self.assertEqual(levels["PWC"], 125.0)
        self.assertEqual(levels["PDH"], 120.0)
        self.assertEqual(levels["PDL"], 80.0)
        self.assertEqual(levels["Today High"], 130.0)
        self.assertEqual(levels["Today Low"], 70.0)
        self.assertNotIn("PWH", visible_only_levels)

    def test_incomplete_previous_day_and_week_are_not_reported(self):
        # Start partway through the previous UTC day: PDH/PDL must not be
        # calculated from an incomplete day, and the prior week is absent too.
        frame = self.make_history()
        frame = frame[frame.timestamp >= pd.Timestamp("2026-11-08 06:00:00+00:00")]
        levels = calculate_reference_levels(frame)
        self.assertNotIn("PDH", levels)
        self.assertNotIn("PDL", levels)
        self.assertNotIn("PWH", levels)
        self.assertNotIn("PWL", levels)
        self.assertNotIn("PWC", levels)
        self.assertIn("Today High", levels)
        self.assertIn("Today Low", levels)

    def test_current_day_range_is_omitted_when_download_starts_midday(self):
        frame = self.make_history()
        current_day = frame[frame.timestamp >= pd.Timestamp("2026-11-09 06:00:00+00:00")]
        levels = calculate_reference_levels(current_day)
        self.assertNotIn("Today High", levels)
        self.assertNotIn("Today Low", levels)

    def test_live_update_preserves_loaded_history_above_old_1200_cap(self):
        combined = pd.DataFrame({"value": range(5003)})
        retained = retain_live_history_depth(combined, previous_count=5000)
        self.assertEqual(len(retained), 5000)
        self.assertEqual(retained.iloc[0]["value"], 3)
        self.assertEqual(retained.iloc[-1]["value"], 5002)

    def test_live_update_uses_minimum_warmup_history(self):
        combined = pd.DataFrame({"value": range(700)})
        retained = retain_live_history_depth(combined, previous_count=300)
        self.assertEqual(len(retained), 500)
        self.assertEqual(retained.iloc[0]["value"], 200)

    def test_missing_candle_invalidates_day_level_window(self):
        frame = self.make_history()
        missing = pd.Timestamp("2026-11-08 12:00:00+00:00")
        frame = frame[frame.timestamp != missing]
        levels = calculate_reference_levels(frame)
        self.assertNotIn("PDH", levels)
        self.assertNotIn("PDL", levels)


if __name__ == "__main__":
    unittest.main()
