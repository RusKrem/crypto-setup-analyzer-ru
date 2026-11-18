"""Файловая очередь уведомлений: основной сканер не обращается к Telegram по сети."""
from __future__ import annotations
import json
import os
import time
import uuid
from pathlib import Path


def load_env_file(path=None):
    env_path = Path(path) if path else Path(__file__).resolve().parent.parent / ".env"
    if not env_path.exists():
        return
    for raw in env_path.read_text(encoding="utf-8-sig").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key, value = key.strip(), value.strip().strip('"').strip("'")
        if key and key not in os.environ:
            os.environ[key] = value


class TelegramNotifier:
    """Пишет JSON в telegram_queue; отдельный TelegramBridge.exe доставляет сообщения."""
    def __init__(self, token=None, chat_id=None, timeout=12):
        load_env_file()
        self.token = (token if token is not None else os.getenv("TELEGRAM_BOT_TOKEN", "")).strip()
        self.chat_id = (chat_id if chat_id is not None else os.getenv("TELEGRAM_CHANNEL", os.getenv("TELEGRAM_CHAT_ID", ""))).strip()
        self.base_dir = Path(__file__).resolve().parent.parent
        self.queue_dir = self.base_dir / "telegram_queue"
        self.timeout = timeout

    @property
    def configured(self):
        return bool(self.token and self.chat_id and not self.token.startswith("ВСТАВЬТЕ")
                    and not self.chat_id.startswith("ВСТАВЬТЕ"))

    def _enqueue(self, payload, photo_path=None):
        """Атомарно записывает JSON очереди и очищает временные файлы при ошибке."""
        created = float(payload["created_ts"])
        filename = f"{int(created * 1000)}_{payload['id']}.json"
        final_path = self.queue_dir / filename
        tmp_path = final_path.with_suffix(".json.tmp")
        try:
            self.queue_dir.mkdir(parents=True, exist_ok=True)
            encoded = json.dumps(payload, ensure_ascii=False, indent=2)
            tmp_path.write_text(encoded, encoding="utf-8")
            os.replace(tmp_path, final_path)
            return True, f"Сообщение поставлено в очередь: {self.chat_id}"
        except (OSError, TypeError, ValueError) as exc:
            try:
                tmp_path.unlink(missing_ok=True)
            except OSError:
                pass
            if photo_path is not None:
                try:
                    Path(photo_path).unlink(missing_ok=True)
                except OSError:
                    pass
            return False, f"Не удалось записать telegram_queue: {exc}"

    def send_text(self, text, kind="message", ttl_seconds=None):
        if not self.configured:
            return False, "Telegram не настроен: заполните TELEGRAM_BOT_TOKEN и TELEGRAM_CHANNEL в .env"
        created = time.time()
        payload = {"id": uuid.uuid4().hex, "created_ts": created, "channel": self.chat_id,
                   "text": str(text), "kind": kind, "attempts": 0}
        if ttl_seconds is not None:
            payload["ttl_seconds"] = int(ttl_seconds)
        return self._enqueue(payload)

    def send_photo(self, image_path, caption, kind="SIGNAL_CARD", ttl_seconds=300, metadata=None):
        if not self.configured:
            return False, "Telegram не настроен"
        photo = Path(image_path).resolve()
        queue_root = self.queue_dir.resolve()
        try:
            photo.relative_to(queue_root)
        except ValueError:
            return False, "Фотография должна находиться внутри telegram_queue"
        if not photo.is_file():
            return False, "Файл карточки не найден"
        created = time.time()
        payload = {"id": uuid.uuid4().hex, "created_ts": created, "channel": self.chat_id,
                   "text": str(caption), "kind": kind, "photo_path": str(photo),
                   "attempts": 0, "ttl_seconds": int(ttl_seconds)}
        if isinstance(metadata, dict):
            # Только компактные поля события. Свечи и другие большие массивы в очередь не копируем.
            payload["metadata"] = metadata
        return self._enqueue(payload, photo_path=photo)

    @staticmethod
    def _fetch_closed_futures_candles(symbol: str, limit: int = 80):
        """Получает только закрытые 1m-свечи с Binance USDⓈ-M Futures."""
        import requests
        base = "https://fapi.binance.com"
        with requests.Session() as session:
            time_response = session.get(f"{base}/fapi/v1/time", timeout=10)
            time_response.raise_for_status()
            server_time = int(time_response.json()["serverTime"])
            response = session.get(f"{base}/fapi/v1/klines",
                params={"symbol": symbol, "interval": "1m", "limit": int(limit)}, timeout=12)
            response.raise_for_status()
            rows = response.json()
        # closeTime должен быть строго меньше серверного времени Binance.
        return [row for row in rows if len(row) > 6 and int(row[6]) < server_time]

    def _queue_card(self, signal: dict, render_kind: str, queue_kind: str, caption: str, ttl_seconds: int):
        from crypto_setup_analyzer.signal_card import render_signal_card
        self.queue_dir.mkdir(parents=True, exist_ok=True)
        candles = signal.get("candles") or []
        if len(candles) < 5:
            try:
                candles = self._fetch_closed_futures_candles(str(signal["symbol"]))
            except Exception as exc:
                return False, f"Карточка не отправлена: не удалось получить реальные свечи Binance Futures: {exc}"
        image_path = self.queue_dir / f"card_{uuid.uuid4().hex}.png"
        try:
            render_signal_card(signal, candles, render_kind, str(image_path))
        except Exception as exc:
            image_path.unlink(missing_ok=True)
            return False, f"Карточка не отправлена: ошибка построения по реальным свечам: {exc}"
        metadata_keys = (
            "symbol", "direction", "level_name", "level_group", "level", "price",
            "distance_pct", "time", "candle_open_time", "wick_body_ratio",
            "close_position", "candle_open", "candle_high", "candle_low", "candle_close",
        )
        metadata = {key: signal[key] for key in metadata_keys if key in signal}
        result = self.send_photo(
            image_path, caption, kind=queue_kind, ttl_seconds=ttl_seconds, metadata=metadata
        )
        if not result[0]:
            image_path.unlink(missing_ok=True)
        return result

    def send_alert(self, signal: dict):
        symbol = str(signal.get("symbol", "?"))
        level_name = str(signal.get("level_name", "уровень"))
        group = str(signal.get("level_group", ""))
        price = float(signal.get("price", 0)); level = float(signal.get("level", 0))
        distance = float(signal.get("distance_pct", 0))
        direction = signal.get("direction") or ("LONG" if level_name in ("PDL", "PWL", "Today Low") else "SHORT")
        caption = (f"🔔 REVERSAL LAB | ПРИБЛИЖЕНИЕ К УРОВНЮ\n{symbol} · {direction}\n"
                   f"Уровень: {level_name} ({group}) · {level:.10g}\nЦена: {price:.10g} · расстояние: {distance:.3f}%\n"
                   "⚠️ Предупреждение о близости уровня, не подтверждённый вход.")
        card_signal = {**signal, "direction": direction}
        return self._queue_card(card_signal, "APPROACH", "LEVEL_APPROACH", caption, 300)

    def send_confirmation(self, signal: dict):
        direction = signal.get("direction", "SHORT")
        caption = (f"✅ REVERSAL LAB | РЕАКЦИЯ ПОДТВЕРЖДЕНА\n{signal['symbol']} · {direction}\n"
                   f"Уровень: {signal['level_name']} · {signal['level']:.10g}\n"
                   f"Тень/тело: {signal['wick_body_ratio']:.2f} · позиция закрытия: {signal['close_position']:.0%} от минимума свечи\n"
                   "Реакция распознана по закрытой минутной свече. Это не гарантия продолжения движения.")
        card_signal = {**signal, "direction": direction}
        return self._queue_card(card_signal, "CONFIRMED", "REACTION_CONFIRMED", caption, 600)

