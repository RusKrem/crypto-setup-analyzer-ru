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

    def test_support_warning_is_suppressed_after_level_was_broken(self):
        with patch("crypto_setup_analyzer.rebound_scanner._levels", return_value=[("PDL", 100.0, "Дневные")]):
            result = scan_symbol(object(), "TESTUSDT", current_price=99.7)
        self.assertEqual(result, [])

    def test_resistance_warning_is_suppressed_after_level_was_broken(self):
        with patch("crypto_setup_analyzer.rebound_scanner._levels", return_value=[("PDH", 100.0, "Дневные")]):
            result = scan_symbol(object(), "TESTUSDT", current_price=100.3)
        self.assertEqual(result, [])

    def test_approach_warning_contains_expected_direction(self):
        levels = [("PDL", 100.0, "Дневные"), ("PDH", 200.0, "Дневные")]
        with patch("crypto_setup_analyzer.rebound_scanner._levels", return_value=levels):
            result = scan_symbol(object(), "TESTUSDT", current_price=100.3)
        self.assertEqual([item["direction"] for item in result], ["LONG"])

    def test_all_six_levels_only_alert_from_the_correct_side(self):
        cases = (
            ("PDL", 100.3, 99.7, "LONG"),
            ("PWL", 100.3, 99.7, "LONG"),
            ("Today Low", 100.3, 99.7, "LONG"),
            ("PDH", 99.7, 100.3, "SHORT"),
            ("PWH", 99.7, 100.3, "SHORT"),
            ("Today High", 99.7, 100.3, "SHORT"),
        )
        for level_name, valid_price, invalid_price, direction in cases:
            with self.subTest(level=level_name):
                level_data = [(level_name, 100.0, "Тест")]
                with patch("crypto_setup_analyzer.rebound_scanner._levels", return_value=level_data):
                    valid_result = scan_symbol(object(), "TESTUSDT", current_price=valid_price)
                    invalid_result = scan_symbol(object(), "TESTUSDT", current_price=invalid_price)
                self.assertEqual(len(valid_result), 1)
                self.assertEqual(valid_result[0]["direction"], direction)
                self.assertEqual(invalid_result, [])

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

    def test_websocket_suppresses_support_alert_below_level(self):
        signals = []
        scanner = ReboundScanner(lambda message: None, signals.append)
        scanner._symbols = ["TESTUSDT"]
        scanner._levels_cache["TESTUSDT"] = [("PDL", 100.0, "Предыдущий день")]
        scanner._handle_price("TESTUSDT", 99.7)
        self.assertEqual(signals, [])

    def test_websocket_suppresses_resistance_alert_above_level(self):
        signals = []
        scanner = ReboundScanner(lambda message: None, signals.append)
        scanner._symbols = ["TESTUSDT"]
        scanner._levels_cache["TESTUSDT"] = [("PDH", 100.0, "Предыдущий день")]
        scanner._handle_price("TESTUSDT", 100.3)
        self.assertEqual(signals, [])


    def test_moving_today_high_and_low_do_not_repeat_approach_alerts(self):
        scenarios = (
            ("Today High", (100.0, 100.1, 100.2, 100.3), 99.7),
            ("Today Low", (100.0, 99.9, 99.8, 99.7), 100.3),
        )
        for level_name, moving_levels, price in scenarios:
            with self.subTest(level_name=level_name):
                signals = []
                scanner = ReboundScanner(lambda message: None, signals.append)
                scanner._symbols = ["TESTUSDT"]

                # Binance обновляет дневной экстремум, но это тот же уровень дня.
                for moving_level in moving_levels:
                    scanner._levels_cache["TESTUSDT"] = [
                        (level_name, moving_level, "Текущий день")
                    ]
                    scanner._handle_price("TESTUSDT", price)

                self.assertEqual(len(signals), 1)
                self.assertEqual(len(scanner._active_alerts), 1)
                self.assertEqual(len(scanner._approach_started), 1)

    def test_period_rollover_prunes_all_old_level_state(self):
        from datetime import datetime, timezone

        scanner = ReboundScanner(lambda message: None, lambda signal: None)
        old_key = scanner._alert_key(
            "TESTUSDT", "Today High", datetime(2026, 11, 9, 12, tzinfo=timezone.utc)
        )
        new_key = scanner._alert_key(
            "TESTUSDT", "Today High", datetime(2026, 11, 10, 12, tzinfo=timezone.utc)
        )
        scanner._active_alerts.add(old_key)
        scanner._approach_started[old_key] = 123.0
        scanner._last_confirmed_candle[old_key] = 456
        scanner._confirmed_alerts.add(old_key)

        scanner._prune_level_state("TESTUSDT", "Today High", new_key)

        self.assertNotIn(old_key, scanner._active_alerts)
        self.assertNotIn(old_key, scanner._approach_started)
        self.assertNotIn(old_key, scanner._last_confirmed_candle)
        self.assertNotIn(old_key, scanner._confirmed_alerts)

    def test_alert_can_repeat_after_price_leaves_hysteresis_zone(self):
        signals = []
        scanner = ReboundScanner(lambda message: None, signals.append)
        scanner._symbols = ["TESTUSDT"]
        scanner._levels_cache["TESTUSDT"] = [
            ("Today High", 100.0, "Текущий день")
        ]

        scanner._handle_price("TESTUSDT", 99.7)
        scanner._handle_price("TESTUSDT", 100.8)  # дальше 0,7%: сброс блокировки
        scanner._handle_price("TESTUSDT", 99.7)

        self.assertEqual(len(signals), 2)

    def test_dynamic_level_key_is_stable_within_period_and_rolls_over(self):
        from datetime import datetime, timezone

        day_1 = datetime(2026, 11, 9, 12, 0, tzinfo=timezone.utc)
        same_day = datetime(2026, 11, 9, 23, 59, tzinfo=timezone.utc)
        next_day = datetime(2026, 11, 10, 0, 1, tzinfo=timezone.utc)

        first = ReboundScanner._alert_key("TESTUSDT", "Today High", day_1)
        same = ReboundScanner._alert_key("TESTUSDT", "Today High", same_day)
        next_period = ReboundScanner._alert_key("TESTUSDT", "Today High", next_day)

        self.assertEqual(first, same)
        self.assertNotEqual(first, next_period)

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


    def test_crossing_level_cancels_active_approach_immediately(self):
        signals = []
        scanner = ReboundScanner(lambda message: None, signals.append)
        scanner._symbols = ["TESTUSDT"]
        scanner._levels_cache["TESTUSDT"] = [
            ("Today High", 100.0, "Текущий день")
        ]

        scanner._handle_price("TESTUSDT", 99.7)
        self.assertEqual(len(signals), 1)
        self.assertEqual(len(scanner._active_alerts), 1)
        self.assertEqual(len(scanner._approach_started), 1)

        # Цена пересекла сопротивление. Гистерезис не должен удерживать
        # старое предупреждение на неправильной стороне уровня.
        scanner._handle_price("TESTUSDT", 100.2)
        self.assertEqual(len(scanner._active_alerts), 0)
        self.assertEqual(len(scanner._approach_started), 0)

    def test_leaving_hysteresis_zone_clears_approach_timer(self):
        signals = []
        scanner = ReboundScanner(lambda message: None, signals.append)
        scanner._symbols = ["TESTUSDT"]
        scanner._levels_cache["TESTUSDT"] = [
            ("PDL", 100.0, "Предыдущий день")
        ]

        scanner._handle_price("TESTUSDT", 100.3)
        self.assertEqual(len(scanner._approach_started), 1)

        # Выход за 0,7% завершает попытку подхода и очищает её таймер.
        scanner._handle_price("TESTUSDT", 100.8)
        self.assertEqual(len(scanner._active_alerts), 0)
        self.assertEqual(len(scanner._approach_started), 0)

        # Новый подход должен получить новый таймер и новое событие.
        scanner._handle_price("TESTUSDT", 100.3)
        self.assertEqual(len(signals), 2)
        self.assertEqual(len(scanner._approach_started), 1)



    def test_confirmation_rejects_candle_closed_before_approach(self):
        scanner = ReboundScanner(lambda message: None, lambda signal: None)
        self.assertFalse(scanner._is_confirmation_fresh(
            close_time_ms=1_000_000,
            approach_started=1001.0,
            now=1002.0,
        ))

    def test_confirmation_accepts_candle_closed_after_approach_within_window(self):
        scanner = ReboundScanner(lambda message: None, lambda signal: None)
        self.assertTrue(scanner._is_confirmation_fresh(
            close_time_ms=1_002_000,
            approach_started=1001.0,
            now=1003.0,
        ))

    def test_confirmation_rejects_approach_older_than_five_minutes(self):
        scanner = ReboundScanner(lambda message: None, lambda signal: None)
        self.assertFalse(scanner._is_confirmation_fresh(
            close_time_ms=1_400_000,
            approach_started=1000.0,
            now=1301.0,
        ))


if __name__ == "__main__":
    unittest.main()
