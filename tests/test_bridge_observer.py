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

    def test_observer_failure_retries_archive_without_resending_telegram(self):
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
                 patch.object(bridge, "archive_delivery", side_effect=RuntimeError("disk full")) as archive_mock, \
                 patch.object(bridge.urllib.request, "urlopen", return_value=FakeResponse(response)) as telegram_mock:
                bridge.process_file(str(message), "123:token", "@test_channel")

                self.assertTrue(message.exists())
                pending = json.loads(message.read_text(encoding="utf-8"))
                self.assertTrue(pending["telegram_sent"])
                self.assertEqual(pending["telegram_result"]["result"]["message_id"], 78)
                self.assertEqual(telegram_mock.call_count, 1)

                # В тесте снимаем backoff, чтобы проверить повторный проход сразу.
                pending["archive_next_attempt_ts"] = 0
                message.write_text(json.dumps(pending), encoding="utf-8")

                archive_mock.side_effect = None
                archive_mock.return_value = True
                bridge.process_file(str(message), "123:token", "@test_channel")

                self.assertFalse(message.exists())
                self.assertEqual(telegram_mock.call_count, 1)
                self.assertEqual(archive_mock.call_count, 2)

            log_text = (base / "bridge.log").read_text(encoding="utf-8")
            self.assertIn("[OBSERVER RETRY]", log_text)
            self.assertIn("[TELEGRAM SENT]", log_text)
            self.assertNotIn("[TELEGRAM RETRY]", log_text)

    def test_photo_symlink_outside_queue_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            queue = base / "telegram_queue"
            queue.mkdir()
            outside = base / "outside.png"
            outside.write_bytes(b"not-in-queue")
            link = queue / "linked.png"
            try:
                link.symlink_to(outside)
            except (OSError, NotImplementedError):
                self.skipTest("Symlinks are unavailable in this environment")

            with patch.object(bridge, "QUEUE_DIR", str(queue)):
                with self.assertRaises(RuntimeError):
                    bridge._validated_photo_path(str(link))


if __name__ == "__main__":
    unittest.main()
