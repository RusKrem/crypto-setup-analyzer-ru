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

    def test_expired_queue_item_removes_its_card_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            queue = base / "telegram_queue"
            queue.mkdir()
            photo = queue / "expired.png"
            photo.write_bytes(b"png")
            message = queue / "expired.json"
            message.write_text(json.dumps({
                "id": "expired-photo", "created_ts": 1000, "ttl_seconds": 10,
                "kind": "LEVEL_APPROACH", "text": "expired", "photo_path": str(photo),
            }), encoding="utf-8")
            with patch.object(bridge, "BASE_DIR", str(base)), \
                 patch.object(bridge, "QUEUE_DIR", str(queue)), \
                 patch.object(bridge, "LOG_FILE", str(base / "bridge.log")), \
                 patch.object(bridge.time, "time", return_value=2000.0), \
                 patch.object(bridge.urllib.request, "urlopen") as telegram_mock:
                bridge.process_file(str(message), "123:token", "@test_channel")
            self.assertFalse(message.exists())
            self.assertFalse(photo.exists())
            telegram_mock.assert_not_called()

    def test_corrupt_queue_json_is_quarantined_for_inspection(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            queue = base / "telegram_queue"
            queue.mkdir()
            message = queue / "broken.json"
            message.write_text('{"id": "broken", invalid json', encoding="utf-8")
            with patch.object(bridge, "QUEUE_DIR", str(queue)), \
                 patch.object(bridge, "LOG_FILE", str(base / "bridge.log")):
                bridge.process_file(str(message), "123:token", "@test_channel")
            self.assertFalse(message.exists())
            quarantined = list((queue / "failed").glob("*_broken.json"))
            self.assertEqual(len(quarantined), 1)
            self.assertIn("invalid json", quarantined[0].read_text(encoding="utf-8"))

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


    def test_valid_json_with_invalid_queue_shape_is_quarantined(self):
        cases = (
            ["not", "an", "object"],
            {"id": "bad-attempts", "attempts": "many", "text": "x"},
            {"id": "bad-sent-flag", "telegram_sent": "yes", "text": "x"},
            {"id": "bad-created", "created_ts": float("nan"), "text": "x"},
            {"id": "sent-without-flag", "delivery_state": "sent", "text": "x"},
            {"id": "flag-with-pending-state", "delivery_state": "pending",
             "telegram_sent": True, "telegram_result": {"ok": True}, "sent_ts": 1, "text": "x"},
        )
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            queue = base / "telegram_queue"
            queue.mkdir()
            with patch.object(bridge, "QUEUE_DIR", str(queue)), \
                 patch.object(bridge, "LOG_FILE", str(base / "bridge.log")), \
                 patch.object(bridge.urllib.request, "urlopen") as telegram_mock:
                for index, payload in enumerate(cases):
                    message = queue / f"invalid-{index}.json"
                    message.write_text(json.dumps(payload), encoding="utf-8")
                    bridge.process_file(str(message), "123:token", "@test_channel")
                    self.assertFalse(message.exists())
                quarantined = list((queue / "failed").glob("*.json"))
                self.assertEqual(len(quarantined), len(cases))
                telegram_mock.assert_not_called()

    def test_queue_state_write_failure_cleans_temporary_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = str(Path(tmp) / "delivery.json")
            with patch.object(bridge.os, "replace", side_effect=OSError("disk full")):
                with self.assertRaises(OSError):
                    bridge._save_queue_item(path, {"id": "write-failure"})
            self.assertFalse(Path(path + ".tmp").exists())

    def test_archive_retry_with_photo_preserves_source_until_observer_success(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            queue = base / "telegram_queue"
            queue.mkdir()
            photo = queue / "card.png"
            photo.write_bytes(b"card-bytes")
            message = queue / "message.json"
            message.write_text(json.dumps({
                "id": "photo-retry", "created_ts": 1700000000,
                "kind": "REACTION_CONFIRMED", "text": "ZECUSDT · LONG",
                "photo_path": str(photo),
            }), encoding="utf-8")
            response = {"ok": True, "result": {"message_id": 88, "chat": {"id": -10088}}}
            real_archive = bridge.archive_delivery
            archive_calls = []
            def fail_once_then_archive(*args, **kwargs):
                archive_calls.append(1)
                if len(archive_calls) == 1:
                    raise RuntimeError("db busy")
                return real_archive(*args, **kwargs)
            with patch.object(bridge, "BASE_DIR", str(base)), \
                 patch.object(bridge, "QUEUE_DIR", str(queue)), \
                 patch.object(bridge, "LOG_FILE", str(base / "bridge.log")), \
                 patch.object(bridge, "archive_delivery", side_effect=fail_once_then_archive) as archive_mock, \
                 patch.object(bridge.urllib.request, "urlopen", return_value=FakeResponse(response)) as telegram_mock:
                bridge.process_file(str(message), "123:token", "@test_channel")
                self.assertTrue(message.exists())
                self.assertTrue(photo.exists())
                self.assertTrue(json.loads(message.read_text(encoding="utf-8"))["telegram_sent"])
                pending = json.loads(message.read_text(encoding="utf-8"))
                pending["archive_next_attempt_ts"] = 0
                message.write_text(json.dumps(pending), encoding="utf-8")

                bridge.process_file(str(message), "123:token", "@test_channel")

                self.assertFalse(message.exists())
                self.assertFalse(photo.exists())
                self.assertEqual(telegram_mock.call_count, 1)
                self.assertEqual(archive_mock.call_count, 2)
                self.assertEqual(len(archive_calls), 2)
                archived_media = list((base / "observer_data" / "media").glob("*"))
                self.assertEqual(len(archived_media), 1)
                self.assertEqual(archived_media[0].read_bytes(), b"card-bytes")

    def test_queue_cleanup_permission_error_does_not_crash_or_resend(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            queue = base / "telegram_queue"
            queue.mkdir()
            message = queue / "message.json"
            message.write_text(json.dumps({
                "id": "cleanup-retry", "created_ts": bridge.time.time(),
                "kind": "message", "text": "ZECUSDT · LONG",
            }), encoding="utf-8")
            response = {"ok": True, "result": {"message_id": 89, "chat": {"id": -10089}}}
            real_remove = bridge.os.remove
            with patch.object(bridge, "BASE_DIR", str(base)), \
                 patch.object(bridge, "QUEUE_DIR", str(queue)), \
                 patch.object(bridge, "LOG_FILE", str(base / "bridge.log")), \
                 patch.object(bridge, "archive_delivery", return_value=True), \
                 patch.object(bridge.urllib.request, "urlopen", return_value=FakeResponse(response)) as telegram_mock:
                def fail_queue_remove(path):
                    if str(path) == str(message):
                        raise PermissionError("file busy")
                    return real_remove(path)
                with patch.object(bridge.os, "remove", side_effect=fail_queue_remove):
                    bridge.process_file(str(message), "123:token", "@test_channel")
                self.assertTrue(message.exists())
                self.assertTrue(json.loads(message.read_text(encoding="utf-8"))["telegram_sent"])

                bridge.process_file(str(message), "123:token", "@test_channel")
                self.assertFalse(message.exists())
                self.assertEqual(telegram_mock.call_count, 1)


    def test_timeout_after_request_start_is_quarantined_without_retry(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            queue = base / "telegram_queue"
            queue.mkdir()
            message = queue / "timeout.json"
            message.write_text(json.dumps({"id": "timeout-1", "text": "test"}), encoding="utf-8")
            with patch.object(bridge, "QUEUE_DIR", str(queue)), \
                 patch.object(bridge, "LOG_FILE", str(base / "bridge.log")), \
                 patch.object(bridge.urllib.request, "urlopen", side_effect=TimeoutError("read timed out")) as sender:
                bridge.process_file(str(message), "123:token", "@test_channel")
                sender.assert_called_once()
            self.assertFalse(message.exists())
            quarantined = list((queue / "failed" / "delivery_unknown").glob("*.json"))
            self.assertEqual(len(quarantined), 1)
            saved = json.loads(quarantined[0].read_text(encoding="utf-8"))
            self.assertEqual(saved["delivery_state"], "delivery_unknown")
            bridge.process_file(str(quarantined[0]), "123:token", "@test_channel")
            self.assertEqual(sender.call_count, 1)


    def test_definite_dns_failure_remains_retryable_not_unknown(self):
        import socket
        from urllib.error import URLError
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            queue = base / "telegram_queue"
            queue.mkdir()
            message = queue / "dns-failure.json"
            message.write_text(json.dumps({"id": "dns-failure-1", "text": "test"}), encoding="utf-8")
            error = URLError(socket.gaierror("name resolution failed"))
            with patch.object(bridge, "QUEUE_DIR", str(queue)), \\
                 patch.object(bridge, "LOG_FILE", str(base / "bridge.log")), \\
                 patch.object(bridge.urllib.request, "urlopen", side_effect=error):
                bridge.process_file(str(message), "123:token", "@test_channel")
            self.assertTrue(message.exists())
            saved = json.loads(message.read_text(encoding="utf-8"))
            self.assertEqual(saved["delivery_state"], "pending")
            self.assertEqual(saved["attempts"], 1)
            self.assertFalse((queue / "failed" / "delivery_unknown").exists())

    def test_restart_with_sending_state_is_quarantined(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            queue = base / "telegram_queue"
            queue.mkdir()
            message = queue / "restart.json"
            message.write_text(json.dumps({
                "id": "restart-1", "text": "test", "delivery_state": "sending"
            }), encoding="utf-8")
            with patch.object(bridge, "QUEUE_DIR", str(queue)), \
                 patch.object(bridge, "LOG_FILE", str(base / "bridge.log")), \
                 patch.object(bridge.urllib.request, "urlopen") as sender:
                bridge.process_file(str(message), "123:token", "@test_channel")
                sender.assert_not_called()
            quarantined = list((queue / "failed" / "delivery_unknown").glob("*.json"))
            self.assertEqual(len(quarantined), 1)
            self.assertEqual(json.loads(quarantined[0].read_text())["delivery_state"], "delivery_unknown")

    def test_explicit_telegram_api_rejection_is_retried_not_marked_unknown(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            queue = base / "telegram_queue"
            queue.mkdir()
            message = queue / "rejected.json"
            message.write_text(json.dumps({"id": "rejected-1", "text": "test"}), encoding="utf-8")
            with patch.object(bridge, "QUEUE_DIR", str(queue)), \
                 patch.object(bridge, "LOG_FILE", str(base / "bridge.log")), \
                 patch.object(bridge.urllib.request, "urlopen", return_value=FakeResponse({
                     "ok": False, "description": "chat not found"
                 })):
                bridge.process_file(str(message), "123:token", "@test_channel")
            self.assertTrue(message.exists())
            saved = json.loads(message.read_text(encoding="utf-8"))
            self.assertEqual(saved["delivery_state"], "pending")
            self.assertEqual(saved["attempts"], 1)
            self.assertFalse((queue / "failed" / "delivery_unknown").exists())

    def test_http_4xx_is_explicit_rejection_and_remains_retryable(self):
        from urllib.error import HTTPError
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            queue = base / "telegram_queue"
            queue.mkdir()
            message = queue / "http-rejected.json"
            message.write_text(json.dumps({"id": "http-rejected-1", "text": "test"}), encoding="utf-8")
            error = HTTPError("https://api.telegram.org/test", 400, "Bad Request", {}, None)
            with patch.object(bridge, "QUEUE_DIR", str(queue)), \
                 patch.object(bridge, "LOG_FILE", str(base / "bridge.log")), \
                 patch.object(bridge.urllib.request, "urlopen", side_effect=error):
                bridge.process_file(str(message), "123:token", "@test_channel")
            saved = json.loads(message.read_text(encoding="utf-8"))
            self.assertEqual(saved["delivery_state"], "pending")
            self.assertEqual(saved["attempts"], 1)

    def test_single_instance_lock_rejects_second_owner_and_releases(self):
        with tempfile.TemporaryDirectory() as tmp:
            lock_path = str(Path(tmp) / ".bridge.lock")
            first = bridge.SingleInstanceLock(lock_path).acquire()
            try:
                with self.assertRaises(bridge.BridgeAlreadyRunning):
                    bridge.SingleInstanceLock(lock_path).acquire()
            finally:
                first.release()
            second = bridge.SingleInstanceLock(lock_path).acquire()
            second.release()

    def test_success_persists_sent_delivery_state(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            queue = base / "telegram_queue"
            queue.mkdir()
            message = queue / "sent.json"
            message.write_text(json.dumps({"id": "sent-1", "text": "test"}), encoding="utf-8")
            response = {"ok": True, "result": {"message_id": 90, "chat": {"id": -10090}}}
            with patch.object(bridge, "BASE_DIR", str(base)), \
                 patch.object(bridge, "QUEUE_DIR", str(queue)), \
                 patch.object(bridge, "LOG_FILE", str(base / "bridge.log")), \
                 patch.object(bridge, "archive_delivery", return_value=True), \
                 patch.object(bridge.urllib.request, "urlopen", return_value=FakeResponse(response)):
                bridge.process_file(str(message), "123:token", "@test_channel")
            self.assertFalse(message.exists())

if __name__ == "__main__":
    unittest.main()
