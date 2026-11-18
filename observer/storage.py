"""Сохранение успешно доставленных Telegram-событий Reversal Lab.

Модуль не отправляет сообщения и не обращается к Telegram API.
Он вызывается Telegram Bridge только после успешного ответа Bot API.
"""
from __future__ import annotations

import json
from contextlib import closing
import re
import shutil
import sqlite3
import time
from pathlib import Path
from typing import Any


def _number(pattern: str, text: str) -> float | None:
    match = re.search(pattern, text, flags=re.IGNORECASE)
    if not match:
        return None
    try:
        return float(match.group(1).replace(",", "."))
    except (TypeError, ValueError):
        return None


def parse_notification(item: dict[str, Any], sent_at: float | None = None) -> dict[str, Any]:
    """Извлекает поля из текста карточки/уведомления, сохраняя исходный текст."""
    text = str(item.get("text", ""))
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    symbol = None
    direction = None
    level_name = None
    level_price = None

    for line in lines:
        symbol_match = re.search(r"\b([A-Z0-9]{2,}USDT)\s*[·|/]\s*(LONG|SHORT)\b", line, re.I)
        if symbol_match:
            symbol = symbol_match.group(1).upper()
            direction = symbol_match.group(2).upper()
            break

    for line in lines:
        if not line.lower().startswith("уровень:"):
            continue
        value = line.split(":", 1)[1].strip()
        # Форматы: "Today Low (Текущий день): 1171.72" и
        # "Today Low (Текущий день) · 1171.72" / "Today Low · 1173.3".
        match = re.match(
            r"(.+?)\s*(?:\([^)]*\))?\s*(?:[·:]\s*)" r"([+-]?\d+(?:[.,]\d+)?)\s*$",
            value,
        )
        if match:
            level_name = re.sub(r"\s*\([^)]*\)", "", match.group(1)).strip()
            try:
                level_price = float(match.group(2).replace(",", "."))
            except ValueError:
                pass
        else:
            # Дополнительный разбор, если строка имеет нестандартный суффикс.
            number_match = re.search(r"([+-]?\d+(?:[.,]\d+)?)\s*$", value)
            if number_match:
                level_price = float(number_match.group(1).replace(",", "."))
                level_name = value[:number_match.start()].strip(" ·:")
                level_name = re.sub(r"\s*\([^)]*\)", "", level_name).strip()
        break

    metadata = item.get("metadata") if isinstance(item.get("metadata"), dict) else {}
    # Структурированные данные сканера точнее текста карточки и имеют приоритет.
    symbol = metadata.get("symbol") or symbol
    direction = metadata.get("direction") or direction
    level_name = metadata.get("level_name") or level_name
    try:
        level_price = float(metadata.get("level")) if metadata.get("level") is not None else level_price
    except (TypeError, ValueError):
        pass

    def meta_float(key: str, fallback: float | None) -> float | None:
        try:
            return float(metadata[key]) if metadata.get(key) is not None else fallback
        except (TypeError, ValueError):
            return fallback

    close_position = meta_float("close_position", None)
    if close_position is None:
        close_pct = _number(r"позиция закрытия:\s*([+-]?\d+(?:[.,]\d+)?)\s*%", text)
        close_position = close_pct / 100.0 if close_pct is not None else None

    return {
        "metadata": metadata,
        "queue_id": str(item.get("id", "")),
        "kind": str(item.get("kind", "message")),
        "symbol": symbol,
        "direction": direction,
        "level_name": level_name,
        "level_price": level_price,
        "price": meta_float("price", _number(r"Цена:\s*([+-]?\d+(?:[.,]\d+)?)", text)),
        "distance_pct": meta_float("distance_pct", _number(r"расстояние:\s*([+-]?\d+(?:[.,]\d+)?)\s*%", text)),
        "wick_body_ratio": meta_float("wick_body_ratio", _number(r"Тень/тело:\s*([+-]?\d+(?:[.,]\d+)?)", text)),
        "close_position": close_position,
        "raw_text": text,
        "created_at": float(item.get("created_ts", sent_at or time.time()) or time.time()),
        "sent_at": float(sent_at or time.time()),
    }


def archive_delivery(
    base_dir: str | Path,
    item: dict[str, Any],
    telegram_result: dict[str, Any] | None = None,
    sent_at: float | None = None,
) -> bool:
    """Архивирует доставленное сообщение. Повторный queue_id игнорируется.

    Возвращает True, если добавлена новая запись, и False при дубликате.
    Вызывающая сторона должна обрабатывать исключения отдельно, не повторяя
    уже успешную отправку сообщения в Telegram.
    """
    base = Path(base_dir).resolve()
    archive_dir = base / "observer_data"
    media_dir = archive_dir / "media"
    archive_dir.mkdir(parents=True, exist_ok=True)
    media_dir.mkdir(parents=True, exist_ok=True)
    db_path = archive_dir / "observer_events.sqlite3"

    event = parse_notification(item, sent_at=sent_at)
    queue_id = event["queue_id"]
    if not queue_id:
        raise ValueError("У события отсутствует id очереди")

    result = telegram_result or {}
    msg_data = result.get("result") if isinstance(result, dict) else {}
    if not isinstance(msg_data, dict):
        msg_data = {}
    chat = msg_data.get("chat") if isinstance(msg_data.get("chat"), dict) else {}

    with closing(sqlite3.connect(db_path, timeout=10)) as conn:
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute(
            """CREATE TABLE IF NOT EXISTS events (
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
                media_path TEXT,
                metadata_json TEXT
            )"""
        )
        columns = {row[1] for row in conn.execute("PRAGMA table_info(events)")}
        if "metadata_json" not in columns:
            conn.execute("ALTER TABLE events ADD COLUMN metadata_json TEXT")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_events_sent_at ON events(sent_at)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_events_symbol ON events(symbol, sent_at)")
        exists = conn.execute("SELECT 1 FROM events WHERE queue_id=?", (queue_id,)).fetchone()
        if exists:
            return False

        media_relative = None
        photo_name = item.get("photo_path")
        if photo_name:
            source = Path(str(photo_name)).resolve()
            # Разрешаем только файлы внутри telegram_queue, как и сам Bridge.
            queue_root = (base / "telegram_queue").resolve()
            try:
                source.relative_to(queue_root)
            except ValueError:
                source = None
            if source and source.is_file():
                safe_id = re.sub(r"[^A-Za-z0-9_-]", "_", queue_id)[:80] or "event"
                target_name = f"{int(event['sent_at'] * 1000)}_{safe_id}{source.suffix.lower()}"
                target = media_dir / target_name
                if not target.exists():
                    shutil.copy2(source, target)
                media_relative = str(Path("media") / target_name)

        conn.execute(
            """INSERT INTO events (
                queue_id, kind, symbol, direction, level_name, level_price,
                price, distance_pct, wick_body_ratio, close_position,
                raw_text, created_at, sent_at, telegram_chat_id,
                telegram_message_id, media_path, metadata_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                event["queue_id"], event["kind"], event["symbol"], event["direction"],
                event["level_name"], event["level_price"], event["price"],
                event["distance_pct"], event["wick_body_ratio"], event["close_position"],
                event["raw_text"], event["created_at"], event["sent_at"],
                str(chat.get("id")) if chat.get("id") is not None else None,
                str(msg_data.get("message_id")) if msg_data.get("message_id") is not None else None,
                media_relative,
                json.dumps(event["metadata"], ensure_ascii=False, default=str),
            ),
        )
        conn.commit()
    return True
