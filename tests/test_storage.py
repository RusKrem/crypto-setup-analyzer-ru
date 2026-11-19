"""Проверки постоянного хранения сигналов и виртуальных сделок."""
import tempfile
import unittest
from pathlib import Path
from infrastructure.storage import Storage

class StorageTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.storage = Storage(str(Path(self.temp.name) / "test.db"))

    def tearDown(self):
        self.temp.cleanup()

    def test_duplicate_signal_is_ignored(self):
        signal = {"symbol":"NEARUSDT", "direction":"LONG", "level_name":"PDL",
                  "level":4.8, "price":4.85, "time":123, "details":"test"}
        self.assertTrue(self.storage.add_signal(signal))
        self.assertFalse(self.storage.add_signal(signal))


    def test_reaction_event_retries_are_idempotent(self):
        event = {
            "symbol": "NEARUSDT", "direction": "LONG", "level_name": "PDL",
            "level": 4.8, "price": 4.85, "time": 123456,
            "event_type": "APPROACH", "details": "near level",
        }
        first = self.storage.add_reaction_event(event)
        second = self.storage.add_reaction_event(dict(event))
        self.assertEqual(first, second)
        self.assertEqual(len(self.storage.recent_reaction_events()), 1)

    def test_distinct_reaction_times_are_distinct_events(self):
        event = {
            "symbol": "NEARUSDT", "direction": "LONG", "level_name": "PDL",
            "level": 4.8, "price": 4.85, "time": 123456,
            "event_type": "APPROACH", "details": "near level",
        }
        first = self.storage.add_reaction_event(event)
        later = dict(event, time=123457)
        second = self.storage.add_reaction_event(later)
        self.assertNotEqual(first, second)
        self.assertEqual(len(self.storage.recent_reaction_events()), 2)

    def test_trade_is_saved_and_open_trade_is_restored(self):
        trade = {"trade_id":"NEARUSDT|LONG|123", "symbol":"NEARUSDT", "direction":"LONG",
                 "signal_time":123, "entry":4.85, "stop":4.8, "target":4.95,
                 "level_name":"PDL", "level":4.82, "status":"OPEN"}
        self.storage.save_trade(trade)
        self.assertEqual(len(self.storage.open_trades()), 1)
        trade["status"] = "TARGET"
        trade["exit_price"] = 4.95
        trade["exit_time"] = 456
        trade["result_pct"] = 2.06
        self.storage.save_trade(trade)
        self.assertEqual(len(self.storage.open_trades()), 0)
        self.assertEqual(self.storage.recent_trades()[0]["status"], "TARGET")

if __name__ == "__main__":
    unittest.main()
