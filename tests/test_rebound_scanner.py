import unittest
from unittest.mock import patch
from crypto_setup_analyzer.rebound_scanner import scan_symbol, ReboundScanner, ALERT_DISTANCE_PCT

class ReboundScannerTests(unittest.TestCase):
    def test_warns_when_price_is_approaching_level(self):
        with patch("crypto_setup_analyzer.rebound_scanner._levels", return_value=[("PDL", 100.0, "Дневные")]):
            result = scan_symbol(object(), "TESTUSDT", current_price=100.3)
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["level_name"], "PDL")
        self.assertAlmostEqual(result[0]["distance_pct"], 0.3)

    def test_no_warning_outside_half_percent(self):
        with patch("crypto_setup_analyzer.rebound_scanner._levels", return_value=[("PDL", 100.0, "Дневные")]):
            result = scan_symbol(object(), "TESTUSDT", current_price=100.8)
        self.assertEqual(result, [])

    def test_touch_is_not_approach_alert(self):
        with patch("crypto_setup_analyzer.rebound_scanner._levels", return_value=[("PDL", 100.0, "Дневные")]):
            result = scan_symbol(object(), "TESTUSDT", current_price=100.0)
        self.assertEqual(result, [])

    def test_default_threshold_is_half_percent(self):
        self.assertEqual(ALERT_DISTANCE_PCT, 0.5)

    def test_scanner_level_groups_are_limited_to_six_daily_weekly_levels(self):
        from datetime import datetime, timezone
        now = datetime.now(timezone.utc)
        # Готовим несколько завершённых дней, прошлую неделю и сегодняшнюю свечу.
        from datetime import timedelta
        monday = now.date() - timedelta(days=now.weekday())
        candles = []
        for offset in range(-14, now.date().weekday() + 1):
            day = monday + timedelta(days=offset)
            stamp = int(datetime(day.year, day.month, day.day, tzinfo=timezone.utc).timestamp() * 1000)
            candles.append([stamp, "100", str(110 + offset), str(90 + offset), "100", "1", stamp + 86399999, "1", 1, "1", "1", "0"])
        with patch("crypto_setup_analyzer.rebound_scanner.fetch_klines", return_value=candles):
            from crypto_setup_analyzer.rebound_scanner import _levels
            levels = _levels(object(), "TESTUSDT")
        names = {name for name, _, _ in levels}
        self.assertLessEqual(names, {"PWH", "PWL", "PDH", "PDL", "Today High", "Today Low"})
        self.assertEqual(len(levels), 6)


    def test_websocket_price_event_emits_approach_and_price_update(self):
        signals = []
        updates = []
        scanner = ReboundScanner(lambda message: None, signals.append,
                                 on_price_update=updates.append)
        scanner._symbols = ["TESTUSDT"]
        scanner._levels_cache["TESTUSDT"] = [("PDL", 100.0, "Предыдущий день")]
        scanner._handle_price("TESTUSDT", 100.3)
        self.assertEqual(len(signals), 1)
        self.assertEqual(signals[0]["level_name"], "PDL")
        self.assertAlmostEqual(updates[0]["distance_pct"], 0.3)
        self.assertTrue(updates[0]["in_zone"])

    def test_websocket_price_event_does_not_alert_on_exact_touch(self):
        signals = []
        scanner = ReboundScanner(lambda message: None, signals.append)
        scanner._symbols = ["TESTUSDT"]
        scanner._levels_cache["TESTUSDT"] = [("PDL", 100.0, "Предыдущий день")]
        scanner._handle_price("TESTUSDT", 100.0)
        self.assertEqual(signals, [])


    def test_rejection_requires_wick_body_ratio_and_close_position(self):
        scanner = ReboundScanner(lambda message: None, lambda signal: None)
        candle = [0, "99.0", "101.0", "98.5", "99.2", "1", 60000]
        result = scanner.evaluate_rejection(candle, 100.0, "SHORT")
        self.assertIsNotNone(result)
        self.assertGreaterEqual(result["wick_body_ratio"], 1.5)
        no_touch = [0, "98.0", "99.0", "97.5", "98.2", "1", 60000]
        self.assertIsNone(scanner.evaluate_rejection(no_touch, 100.0, "SHORT"))

    def test_long_rejection_is_mirrored(self):
        scanner = ReboundScanner(lambda message: None, lambda signal: None)
        candle = [0, "101.0", "101.5", "99.0", "100.8", "1", 60000]
        result = scanner.evaluate_rejection(candle, 100.0, "LONG")
        self.assertIsNotNone(result)
        self.assertGreaterEqual(result["close_position"], 0.65)

if __name__ == "__main__":
    unittest.main()
