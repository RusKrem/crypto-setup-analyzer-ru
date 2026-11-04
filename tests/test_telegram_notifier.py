import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from crypto_setup_analyzer.telegram_notifier import TelegramNotifier, load_env_file


class TelegramNotifierTests(unittest.TestCase):
    def test_load_env_file_does_not_override_existing_environment(self):
        with tempfile.TemporaryDirectory() as folder:
            env_file = Path(folder) / ".env"
            env_file.write_text("TEST_TELEGRAM_KEY=file-value\n", encoding="utf-8")
            with patch.dict(os.environ, {"TEST_TELEGRAM_KEY": "existing-value"}, clear=False):
                load_env_file(env_file)
                self.assertEqual(os.environ["TEST_TELEGRAM_KEY"], "existing-value")

    def test_not_configured_when_missing_values(self):
        notifier = TelegramNotifier(token="", chat_id="")
        ok, message = notifier.send_text("test")
        self.assertFalse(ok)
        self.assertIn("не настроен", message)

    def test_send_text_writes_queue_not_network(self):
        with tempfile.TemporaryDirectory() as folder:
            notifier = TelegramNotifier(token="123:abc", chat_id="@test_channel")
            notifier.queue_dir = Path(folder) / "telegram_queue"
            ok, message = notifier.send_text("hello", kind="OPEN")
            self.assertTrue(ok)
            self.assertIn("очередь", message)
            files = list(notifier.queue_dir.glob("*.json"))
            self.assertEqual(len(files), 1)
            item = json.loads(files[0].read_text(encoding="utf-8"))
            self.assertEqual(item["channel"], "@test_channel")
            self.assertEqual(item["text"], "hello")
            self.assertEqual(item["kind"], "OPEN")

    def test_level_alert_uses_real_futures_candles_and_five_minute_ttl(self):
        candles = []
        price = 1.0
        for i in range(8):
            opening = price
            price += 0.0001 if i % 2 else -0.00005
            high = max(opening, price) + 0.0001
            low = min(opening, price) - 0.0001
            candles.append([i * 60000, opening, high, low, price, 10, (i+1)*60000-1, 0, 0, 0, 0, 0])
        with tempfile.TemporaryDirectory() as folder:
            notifier = TelegramNotifier(token="123:abc", chat_id="@test_channel")
            notifier.queue_dir = Path(folder) / "telegram_queue"
            def fake_render(signal, received_candles, kind, output_path):
                self.assertEqual(received_candles, candles)
                self.assertEqual(kind, "APPROACH")
                Path(output_path).write_bytes(b"test-png")
                return output_path
            with patch.object(notifier, "_fetch_closed_futures_candles", return_value=candles), \
                 patch("crypto_setup_analyzer.signal_card.render_signal_card", side_effect=fake_render):
                ok, _ = notifier.send_alert({"symbol": "ABCUSDT", "level_name": "PDL", "price": 1, "level": 1.01, "distance_pct": 0.1})
            self.assertTrue(ok)
            item = json.loads(next(notifier.queue_dir.glob("*.json")).read_text(encoding="utf-8"))
            self.assertEqual(item["ttl_seconds"], 300)
            self.assertEqual(item["kind"], "LEVEL_APPROACH")
            self.assertTrue(item["photo_path"].endswith(".png"))

    def test_level_alert_does_not_fall_back_to_text_without_real_candles(self):
        with tempfile.TemporaryDirectory() as folder:
            notifier = TelegramNotifier(token="123:abc", chat_id="@test_channel")
            notifier.queue_dir = Path(folder) / "telegram_queue"
            with patch.object(notifier, "_fetch_closed_futures_candles", side_effect=RuntimeError("offline")):
                ok, message = notifier.send_alert({"symbol": "ABCUSDT", "level_name": "PDL", "price": 1, "level": 1.01, "distance_pct": 0.1})
            self.assertFalse(ok)
            self.assertIn("реальные свечи Binance Futures", message)
            self.assertFalse(list(notifier.queue_dir.glob("*.json")))


if __name__ == "__main__":
    unittest.main()
