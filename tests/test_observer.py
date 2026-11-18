import sqlite3
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from observer.storage import archive_delivery, parse_notification


class ObserverTests(unittest.TestCase):
    def test_parse_approach_notification(self):
        item = {
            "id": "approach-1",
            "kind": "LEVEL_APPROACH",
            "created_ts": 1700000000,
            "text": (
                "🔔 REVERSAL LAB | ПРИБЛИЖЕНИЕ К УРОВНЮ\n"
                "ZECUSDT · LONG\n"
                "Уровень: Today Low (Текущий день): 1171.72\n"
                "Цена: 1176.82 · расстояние: 0.435%\n"
            ),
        }
        event = parse_notification(item, sent_at=1700000005)
        self.assertEqual(event["symbol"], "ZECUSDT")
        self.assertEqual(event["direction"], "LONG")
        self.assertEqual(event["level_name"], "Today Low")
        self.assertAlmostEqual(event["level_price"], 1171.72)
        self.assertAlmostEqual(event["price"], 1176.82)
        self.assertAlmostEqual(event["distance_pct"], 0.435)

    def test_parse_confirmation_notification(self):
        item = {
            "id": "confirm-1",
            "kind": "REACTION_CONFIRMED",
            "created_ts": 1700000000,
            "text": (
                "✅ REVERSAL LAB | РЕАКЦИЯ ПОДТВЕРЖДЕНА\n"
                "TRUMPUSDT · LONG\n"
                "Уровень: Today Low · 1.112\n"
                "Тень/тело: 5.00 · позиция закрытия: 86% от минимума свечи\n"
            ),
        }
        event = parse_notification(item, sent_at=1700000005)
        self.assertEqual(event["symbol"], "TRUMPUSDT")
        self.assertEqual(event["level_name"], "Today Low")
        self.assertAlmostEqual(event["level_price"], 1.112)
        self.assertAlmostEqual(event["wick_body_ratio"], 5.0)
        self.assertAlmostEqual(event["close_position"], 0.86)

    def test_archive_copies_image_and_saves_telegram_metadata(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            queue = base / "telegram_queue"
            queue.mkdir()
            photo = queue / "card.png"
            photo.write_bytes(b"fake-png-bytes")
            item = {
                "id": "photo-1", "kind": "REACTION_CONFIRMED",
                "created_ts": time.time(), "photo_path": str(photo),
                "text": "✅ REVERSAL LAB | РЕАКЦИЯ ПОДТВЕРЖДЕНА\nZECUSDT · LONG\nУровень: PDL · 1176.98",
                "metadata": {"symbol": "ZECUSDT", "direction": "LONG", "level_name": "PDL",
                             "level": 1176.98, "price": 1180.27, "close_position": 0.81},
            }
            api_result = {"ok": True, "result": {"message_id": 321, "chat": {"id": -100123}}}
            self.assertTrue(archive_delivery(base, item, api_result))
            self.assertTrue(photo.exists())  # Bridge сам удалит исходник после архивации.
            db = base / "observer_data" / "observer_events.sqlite3"
            with sqlite3.connect(db) as conn:
                row = conn.execute(
                    "SELECT symbol, level_name, telegram_chat_id, telegram_message_id, media_path, price, close_position FROM events"
                ).fetchone()
            self.assertEqual(row[:4], ("ZECUSDT", "PDL", "-100123", "321"))
            self.assertEqual(row[5:], (1180.27, 0.81))
            archived = base / "observer_data" / row[4]
            self.assertTrue(archived.exists())
            self.assertEqual(archived.read_bytes(), b"fake-png-bytes")

    def test_media_filename_does_not_collide_after_queue_id_sanitizing(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            queue = base / "telegram_queue"
            queue.mkdir()
            first = queue / "first.png"
            second = queue / "second.png"
            first.write_bytes(b"first-image")
            second.write_bytes(b"second-image")
            sent_at = time.time()
            item_a = {"id": "a/b", "kind": "REACTION_CONFIRMED",
                      "photo_path": str(first), "text": "A", "created_ts": sent_at}
            item_b = {"id": "a_b", "kind": "REACTION_CONFIRMED",
                      "photo_path": str(second), "text": "B", "created_ts": sent_at}
            self.assertTrue(archive_delivery(base, item_a, sent_at=sent_at))
            self.assertTrue(archive_delivery(base, item_b, sent_at=sent_at))
            with sqlite3.connect(base / "observer_data" / "observer_events.sqlite3") as conn:
                paths = [row[0] for row in conn.execute(
                    "SELECT media_path FROM events ORDER BY queue_id"
                )]
            self.assertNotEqual(paths[0], paths[1])
            self.assertEqual((base / "observer_data" / paths[0]).read_bytes(), b"first-image")
            self.assertEqual((base / "observer_data" / paths[1]).read_bytes(), b"second-image")

    def test_failed_database_insert_removes_copied_media(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            queue = base / "telegram_queue"
            queue.mkdir()
            photo = queue / "card.png"
            photo.write_bytes(b"image")
            item = {"id": "failed-insert", "kind": "REACTION_CONFIRMED",
                    "photo_path": str(photo), "text": "test", "created_ts": time.time()}
            with patch("observer.storage.json.dumps", side_effect=RuntimeError("serialize failed")):
                with self.assertRaises(RuntimeError):
                    archive_delivery(base, item, sent_at=time.time())
            media_dir = base / "observer_data" / "media"
            self.assertEqual(list(media_dir.iterdir()), [])

    def test_legacy_database_is_migrated_with_metadata_column(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            archive = base / "observer_data"
            archive.mkdir()
            db = archive / "observer_events.sqlite3"
            with sqlite3.connect(db) as conn:
                conn.execute(
                    """CREATE TABLE events (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        queue_id TEXT NOT NULL UNIQUE,
                        kind TEXT NOT NULL,
                        symbol TEXT,
                        direction TEXT,
                        level_name TEXT,
                        level_price REAL,
                        price REAL,
                        distance_pct REAL,
                        wick_body_ratio REAL,
                        close_position REAL,
                        raw_text TEXT NOT NULL,
                        created_at REAL NOT NULL,
                        sent_at REAL NOT NULL,
                        telegram_chat_id TEXT,
                        telegram_message_id TEXT,
                        media_path TEXT
                    )"""
                )
            item = {"id": "legacy-migration", "kind": "LEVEL_APPROACH",
                    "text": "ZECUSDT · LONG", "created_ts": time.time()}
            self.assertTrue(archive_delivery(base, item))
            with sqlite3.connect(db) as conn:
                columns = {row[1] for row in conn.execute("PRAGMA table_info(events)")}
                metadata = conn.execute(
                    "SELECT metadata_json FROM events WHERE queue_id=?",
                    ("legacy-migration",),
                ).fetchone()
            self.assertIn("metadata_json", columns)
            self.assertEqual(metadata[0], "{}")

    def test_same_queue_id_is_not_archived_twice(self):
        with tempfile.TemporaryDirectory() as tmp:
            item = {"id": "same-id", "kind": "LEVEL_APPROACH", "text": "ZECUSDT · LONG"}
            self.assertTrue(archive_delivery(tmp, item, {"ok": True}))
            self.assertFalse(archive_delivery(tmp, item, {"ok": True}))
            with sqlite3.connect(Path(tmp) / "observer_data" / "observer_events.sqlite3") as conn:
                count = conn.execute("SELECT COUNT(*) FROM events").fetchone()[0]
            self.assertEqual(count, 1)


if __name__ == "__main__":
    unittest.main()
