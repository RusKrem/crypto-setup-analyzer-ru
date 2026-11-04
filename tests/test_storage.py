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
