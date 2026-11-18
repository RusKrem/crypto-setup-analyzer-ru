import json
import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from telegram_bridge import bridge


class FakeResponse:
    def __init__(self, payload):
        self.payload = payload

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def read(self):
        return json.dumps(self.payload).encode("utf-8")


class BridgeObserverIntegrationTests(unittest.TestCase):
    def test_successful_send_is_archived_before_queue_media_are_removed(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            queue = base / "telegram_queue"
            queue.mkdir()
            photo = queue / "card.png"
            photo.write_bytes(b"png")
            payload = {
                "id": "integrated-1", "created_ts": 1700000000,
                "kind": "REACTION_CONFIRMED", "text": "✅\nZECUSDT · LONG\nУровень: PDL · 1176.98",
                "photo_path": str(photo), "channel": "@test_channel",
                "metadata": {"symbol": "ZECUSDT", "direction": "LONG", "level_name": "PDL",
                             "level": 1176.98, "price": 1180.27, "close_position": 0.81},
            }
            message = queue / "message.json"
            message.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
            response = {"ok": True, "result": {"message_id": 77, "chat": {"id": -10077}}}
            with patch.object(bridge, "BASE_DIR", str(base)), \
                 patch.object(bridge, "QUEUE_DIR", str(queue)), \
                 patch.object(bridge, "LOG_FILE", str(base / "bridge.log")), \
                 patch.object(bridge.urllib.request, "urlopen", return_value=FakeResponse(response)):
                bridge.process_file(str(message), "123:token", "@test_channel")

            self.assertFalse(message.exists())
            self.assertFalse(photo.exists())
            db = base / "observer_data" / "observer_events.sqlite3"
            with sqlite3.connect(db) as conn:
                row = conn.execute(
                    "SELECT symbol, level_name, telegram_message_id, media_path FROM events"
                ).fetchone()
            self.assertEqual(row[:3], ("ZECUSDT", "PDL", "77"))
            self.assertTrue((base / "observer_data" / row[3]).exists())

    def test_observer_failure_does_not_retry_successfully_sent_message(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            queue = base / "telegram_queue"
            queue.mkdir()
            message = queue / "message.json"
            message.write_text(json.dumps({
                "id": "observer-error", "kind": "LEVEL_APPROACH", "text": "ZECUSDT · LONG"
            }), encoding="utf-8")
            response = {"ok": True, "result": {"message_id": 78, "chat": {"id": -10078}}}
            with patch.object(bridge, "BASE_DIR", str(base)), \
                 patch.object(bridge, "QUEUE_DIR", str(queue)), \
                 patch.object(bridge, "LOG_FILE", str(base / "bridge.log")), \
                 patch.object(bridge, "archive_delivery", side_effect=RuntimeError("disk full")), \
                 patch.object(bridge.urllib.request, "urlopen", return_value=FakeResponse(response)):
                bridge.process_file(str(message), "123:token", "@test_channel")

            self.assertFalse(message.exists())
            log_text = (base / "bridge.log").read_text(encoding="utf-8")
            self.assertIn("[OBSERVER ERROR]", log_text)
            self.assertIn("[TELEGRAM SENT]", log_text)
            self.assertNotIn("[TELEGRAM RETRY]", log_text)


if __name__ == "__main__":
    unittest.main()
