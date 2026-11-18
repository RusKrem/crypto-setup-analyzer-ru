"""Сканер приближения цены к ключевым уровням Binance Futures USDT-M."""
from __future__ import annotations
import time
import threading
from datetime import datetime, timedelta, timezone
import requests
import json
import math
import websocket

BASE_URL = "https://fapi.binance.com"
TOP_ALTCOINS_COUNT = 30
MIN_QUOTE_VOLUME_USDT = 2_000_000
ALERT_DISTANCE_PCT = 0.5

# Направление ожидаемого подхода к каждому опорному уровню.
# Поддержка: цена подходит сверху вниз (LONG).
# Сопротивление: цена подходит снизу вверх (SHORT).
LEVEL_DIRECTIONS = {
    "PDL": "LONG",
    "PWL": "LONG",
    "Today Low": "LONG",
    "PDH": "SHORT",
    "PWH": "SHORT",
    "Today High": "SHORT",
}


def _is_valid_approach_side(level_name: str, price: float, level: float) -> bool:
    """Проверяет, что цена подходит к уровню с ожидаемой стороны."""
    direction = LEVEL_DIRECTIONS.get(level_name)
    if direction == "LONG":
        return price > level
    if direction == "SHORT":
        return price < level
    # Неизвестные уровни не должны генерировать сигналы с неподтверждённой семантикой.
    return False


EXCLUDED_BASES = {
    "BTC", "ETH", "BNB", "SOL", "XRP", "USDC", "FDUSD", "TUSD", "USDP", "DAI",
    "EUR", "TRY", "BRL", "GBP", "AUD", "UST", "USTC", "PAXG", "WBTC", "WBETH",
    "USDE", "USDS", "USD1", "RLUSD", "PYUSD", "EURC", "USDD", "BUSD"
}


def list_altcoin_symbols(session: requests.Session, limit: int = TOP_ALTCOINS_COUNT,
                         min_quote_volume: float = MIN_QUOTE_VOLUME_USDT) -> list[str]:
    """Выбирает ликвидные бессрочные USDT-M фьючерсы, исключая основные монеты и стейблкоины."""
    info = session.get(f"{BASE_URL}/fapi/v1/exchangeInfo", timeout=20)
    info.raise_for_status()
    allowed = set()
    for item in info.json().get("symbols", []):
        base, symbol = item.get("baseAsset", ""), item.get("symbol", "")
        if (item.get("status") == "TRADING" and item.get("quoteAsset") == "USDT"
                and item.get("contractType") == "PERPETUAL" and base not in EXCLUDED_BASES
                and not any(tag in base for tag in ("UP", "DOWN", "BULL", "BEAR"))):
            allowed.add(symbol)
    tickers = session.get(f"{BASE_URL}/fapi/v1/ticker/24hr", timeout=20)
    tickers.raise_for_status()
    ranked = []
    for item in tickers.json():
        if item.get("symbol") not in allowed:
            continue
        try:
            volume = float(item.get("quoteVolume", 0))
        except (TypeError, ValueError):
            continue
        if volume >= min_quote_volume:
            ranked.append((item["symbol"], volume))
    ranked.sort(key=lambda row: row[1], reverse=True)
    return [symbol for symbol, _ in ranked[:max(1, int(limit))]]


def _validate_klines(rows, symbol: str, interval: str):
    """Проверяет структуру и хронологию ответа Binance Klines до расчётов."""
    if not isinstance(rows, list):
        raise ValueError(f"Binance вернула некорректный список свечей для {symbol} {interval}")
    validated = []
    previous_open = None
    for index, row in enumerate(rows):
        if not isinstance(row, (list, tuple)) or len(row) < 7:
            raise ValueError(f"Свеча {index} для {symbol} {interval} имеет неверный формат")
        try:
            open_time = int(row[0])
            close_time = int(row[6])
            open_price, high, low, close = map(float, (row[1], row[2], row[3], row[4]))
            volume = float(row[5])
        except (TypeError, ValueError, OverflowError) as exc:
            raise ValueError(f"Свеча {index} для {symbol} {interval} содержит некорректные значения") from exc
        values = (open_price, high, low, close, volume)
        if not all(math.isfinite(value) for value in values):
            raise ValueError(f"Свеча {index} для {symbol} {interval} содержит нечисловые значения")
        if min(open_price, high, low, close) <= 0 or volume < 0:
            raise ValueError(f"Свеча {index} для {symbol} {interval} содержит недопустимые цены/объём")
        if high < max(open_price, close, low) or low > min(open_price, close, high):
            raise ValueError(f"Свеча {index} для {symbol} {interval} имеет противоречивый OHLC")
        if close_time < open_time or (previous_open is not None and open_time <= previous_open):
            raise ValueError(f"Свечи {symbol} {interval} идут не по времени или повторяются")
        previous_open = open_time
        validated.append(row)
    return validated


def fetch_klines(session, symbol: str, interval: str, limit: int):
    response = session.get(f"{BASE_URL}/fapi/v1/klines",
                           params={"symbol": symbol, "interval": interval, "limit": limit}, timeout=12)
    response.raise_for_status()
    return _validate_klines(response.json(), symbol, interval)


def _levels(session, symbol):
    """Строит уровни только по свечам точных UTC-периодов; неполные окна пропускаются."""
    daily = fetch_klines(session, symbol, "1d", 16)
    now = datetime.now(timezone.utc)
    today = now.date()
    previous_date = today - timedelta(days=1)
    today_start = datetime.combine(today, datetime.min.time(), tzinfo=timezone.utc)
    previous_week_start = today_start - timedelta(days=today.weekday() + 7)
    previous_week_dates = {
        previous_week_start.date() + timedelta(days=offset) for offset in range(7)
    }
    by_date = {}
    for candle in daily:
        candle_date = datetime.fromtimestamp(int(candle[0]) / 1000, timezone.utc).date()
        by_date[candle_date] = candle

    levels = []
    previous_day = by_date.get(previous_date)
    if previous_day is not None:
        levels.extend([
            ("PDH", float(previous_day[2]), "Предыдущий день"),
            ("PDL", float(previous_day[3]), "Предыдущий день"),
        ])

    # Недельный диапазон допустим только при наличии всех семи дневных свечей.
    if previous_week_dates.issubset(by_date):
        previous_week_days = [by_date[day] for day in sorted(previous_week_dates)]
        levels.extend([
            ("PWH", max(float(c[2]) for c in previous_week_days), "Предыдущая неделя"),
            ("PWL", min(float(c[3]) for c in previous_week_days), "Предыдущая неделя"),
        ])

    current_day = by_date.get(today)
    if current_day is not None:
        levels.extend([
            ("Today High", float(current_day[2]), "Текущий день"),
            ("Today Low", float(current_day[3]), "Текущий день"),
        ])

    return [(name, price, group) for name, price, group in levels if price > 0]


def _level_period_token(level_name: str, now: datetime | None = None):
    """Возвращает стабильный идентификатор периода для уровня.

    Цена Today High/Low может меняться при каждом обновлении Binance, но это
    всё ещё тот же дневной уровень. Идентификатор меняется только при переходе
    к новому календарному дню/неделе UTC.
    """
    now = now or datetime.now(timezone.utc)
    today = now.astimezone(timezone.utc).date()

    if level_name in ("Today High", "Today Low"):
        return ("day", today.isoformat())
    if level_name in ("PDH", "PDL"):
        return ("day", (today - timedelta(days=1)).isoformat())
    if level_name in ("PWH", "PWL", "PWC"):
        current_week_start = today - timedelta(days=today.weekday())
        previous_week_start = current_week_start - timedelta(days=7)
        return ("week", previous_week_start.isoformat())
    return ("level", level_name)


def scan_symbol(session, symbol: str, current_price: float | None = None):
    """Выдаёт только предупреждение о приближении в пределах 0,5%, без сигналов входа."""
    if current_price is None:
        response = session.get(f"{BASE_URL}/fapi/v1/ticker/price", params={"symbol": symbol}, timeout=8)
        response.raise_for_status()
        current_price = float(response.json()["price"])
    alerts = []
    for name, level, group in _levels(session, symbol):
        distance = abs(current_price-level)/level*100
        direction = LEVEL_DIRECTIONS.get(name)
        # Предупреждаем только до пересечения: LONG подходит к поддержке сверху,
        # SHORT подходит к сопротивлению снизу.
        correct_side = _is_valid_approach_side(name, current_price, level)
        if correct_side and 0 < distance <= ALERT_DISTANCE_PCT:
            alerts.append({"symbol": symbol, "level_name": name, "level_group": group,
                           "direction": direction, "level": level, "price": current_price,
                           "distance_pct": distance, "time": int(time.time()*1000),
                           "details": f"Цена в {distance:.3f}% от уровня; касание ещё не подтверждено"})
    return sorted(alerts, key=lambda x: x["distance_pct"])


class ReboundScanner:
    """Фоновый радар уровней: цены получает через WebSocket, уровни через REST."""
    WS_URL = "wss://fstream.binance.com/ws/!ticker@arr"

    def __init__(self, on_status, on_signal, on_symbols=None, on_trade_update=None,
                 on_price_update=None, on_confirmation=None, batch_size=30, interval_seconds=3, alert_distance_pct=ALERT_DISTANCE_PCT,
                 symbol_refresh_seconds=900, levels_refresh_seconds=60):
        self.on_status = on_status
        self.on_signal = on_signal
        self.on_symbols = on_symbols or (lambda count: None)
        self.on_price_update = on_price_update or (lambda update: None)
        self.on_confirmation = on_confirmation or (lambda update: None)
        self.batch_size = max(1, int(batch_size))
        self.interval_seconds = max(1, int(interval_seconds))
        self.symbol_refresh_seconds = max(60, int(symbol_refresh_seconds))
        self.levels_refresh_seconds = max(15, int(levels_refresh_seconds))
        self.alert_distance_pct = float(alert_distance_pct)
        self._stop = threading.Event()
        self._thread = None
        self._ws_thread = None
        self._confirmation_thread = None
        self._last_confirmed_candle = {}
        self._confirmed_alerts = set()
        self._approach_started = {}
        self._chart_candles = {}
        self._ws_app = None
        self._symbols = []
        self._active_alerts = set()
        self._last_refresh = 0
        self._levels_cache = {}
        self._levels_cache_time = {}
        self._last_ws_price_at = {}
        self._last_ws_event_time = {}
        self._lock = threading.RLock()

    @property
    def running(self):
        return self._thread is not None and self._thread.is_alive()

    def start(self):
        if not self.running:
            self._stop.clear()
            self._thread = threading.Thread(target=self._run, daemon=True)
            self._ws_thread = threading.Thread(target=self._ws_loop, daemon=True)
            self._confirmation_thread = threading.Thread(target=self._confirmation_loop, daemon=True)
            self._thread.start()
            self._ws_thread.start()
            self._confirmation_thread.start()

    def stop(self):
        self._stop.set()
        app = self._ws_app
        if app is not None:
            try:
                app.close()
            except Exception:
                pass

    def _run(self):
        """Обновляет список монет и уровни; частые цены сюда не запрашиваются."""
        last_price_refresh = 0.0
        with requests.Session() as session:
            while not self._stop.is_set():
                try:
                    now = time.time()
                    if not self._symbols or now - self._last_refresh >= self.symbol_refresh_seconds:
                        symbols = list_altcoin_symbols(session, limit=self.batch_size)
                        with self._lock:
                            self._symbols = symbols
                            self._last_refresh = now
                            # При смене списка оставляем кэш только для отслеживаемых монет.
                            self._levels_cache = {s: v for s, v in self._levels_cache.items() if s in symbols}
                            self._levels_cache_time = {s: v for s, v in self._levels_cache_time.items() if s in symbols}
                            self._last_ws_price_at = {s: v for s, v in self._last_ws_price_at.items() if s in symbols}
                            self._last_ws_event_time = {s: v for s, v in self._last_ws_event_time.items() if s in symbols}
                            self._active_alerts = {k for k in self._active_alerts if k[0] in symbols}
                        self.on_symbols(len(symbols))
                    with self._lock:
                        symbols = list(self._symbols)
                    if not symbols:
                        raise RuntimeError("Binance Futures не вернула подходящие альткоины USDT-M.")
                    # Обновляем только уровни по REST, а цены приходят отдельным WebSocket-потоком.
                    for symbol in symbols:
                        if self._stop.is_set():
                            break
                        now = time.time()
                        if (symbol not in self._levels_cache or
                                now - self._levels_cache_time.get(symbol, 0) >= self.levels_refresh_seconds):
                            try:
                                levels = _levels(session, symbol)
                                with self._lock:
                                    self._levels_cache[symbol] = levels
                                    self._levels_cache_time[symbol] = now
                            except Exception as exc:
                                self.on_status(f"Не удалось обновить уровни {symbol}: {str(exc)[:80]}")
                    # Резервная загрузка цен через REST. Она также создаёт первые строки
                    # таблицы, даже если WebSocket ещё не подключился или недоступен.
                    now = time.time()
                    if now - last_price_refresh >= 10:
                        try:
                            response = session.get(f"{BASE_URL}/fapi/v1/ticker/price", timeout=12)
                            response.raise_for_status()
                            ticker_prices = response.json()
                            prices = {}
                            for item in ticker_prices:
                                symbol = item.get("symbol")
                                if symbol not in symbols:
                                    continue
                                try:
                                    price = float(item.get("price", 0))
                                except (TypeError, ValueError):
                                    continue
                                if math.isfinite(price) and price > 0:
                                    prices[symbol] = price
                            updated = 0
                            for symbol, price in prices.items():
                                if price > 0:
                                    self._handle_price(symbol, price, source="rest")
                                    updated += 1
                            last_price_refresh = now
                            self.on_status(
                                f"Binance Futures USDT-M · {len(symbols)} альткоинов · "
                                f"цены REST + WebSocket · получено цен: {updated} · "
                                f"порог {self.alert_distance_pct:.2f}%"
                            )
                        except Exception as exc:
                            self.on_status(
                                f"Резервное получение цен Binance: {str(exc)[:100]}"
                            )
                    else:
                        self.on_status(
                            f"Binance Futures USDT-M · {len(symbols)} альткоинов · "
                            f"REST + WebSocket · порог {self.alert_distance_pct:.2f}%"
                        )
                except Exception as exc:
                    self.on_status(f"Ошибка подготовки сканера: {str(exc)[:140]}")
                self._stop.wait(2)

    @staticmethod
    def _alert_key(symbol, level_name, now=None):
        """Ключ алерта не зависит от плавающей цены динамического экстремума."""
        return (symbol, level_name, _level_period_token(level_name, now))

    def _prune_level_state(self, symbol, level_name, keep_key):
        """Удаляет состояние того же уровня из уже завершившихся периодов."""
        stale_keys = {
            key for key in self._active_alerts
            if key[0] == symbol and key[1] == level_name and key != keep_key
        }
        for mapping in (self._approach_started, self._last_confirmed_candle):
            stale_keys.update(
                key for key in mapping
                if key[0] == symbol and key[1] == level_name and key != keep_key
            )
        stale_keys.update(
            key for key in self._confirmed_alerts
            if key[0] == symbol and key[1] == level_name and key != keep_key
        )
        self._active_alerts.difference_update(stale_keys)
        self._confirmed_alerts.difference_update(stale_keys)
        for mapping in (self._approach_started, self._last_confirmed_candle):
            for key in stale_keys:
                mapping.pop(key, None)

    def _handle_price(self, symbol, price, source="websocket", event_time_ms=None):
        """Обрабатывает цену; REST не перезаписывает свежие данные WebSocket."""
        try:
            price = float(price)
        except (TypeError, ValueError):
            return
        if not math.isfinite(price) or price <= 0:
            return
        now = time.time()
        with self._lock:
            if symbol not in self._symbols:
                return
            if source == "rest" and now - self._last_ws_price_at.get(symbol, 0.0) < 15:
                return
            if source == "websocket":
                event_time = int(event_time_ms) if event_time_ms is not None else int(now * 1000)
                if event_time < self._last_ws_event_time.get(symbol, 0):
                    return
                self._last_ws_event_time[symbol] = event_time
                self._last_ws_price_at[symbol] = now
            levels = list(self._levels_cache.get(symbol, []))
        if not levels:
            return
        now = time.time()
        # Для WebSocket используем время события Binance, а не часы локального ПК.
        # REST fallback не содержит event time, поэтому для него остаётся время получения.
        try:
            event_time = int(event_time_ms) if source == "websocket" and event_time_ms is not None else int(now * 1000)
        except (TypeError, ValueError, OverflowError):
            event_time = int(now * 1000)
        active_now = set()
        for name, level, group in levels:
            if level <= 0:
                continue
            distance = abs(price - level) / level * 100
            direction = LEVEL_DIRECTIONS.get(name)
            correct_side = _is_valid_approach_side(name, price, level)
            in_zone = correct_side and 0 < distance <= self.alert_distance_pct
            update = {"symbol": symbol, "level_name": name, "level_group": group,
                      "direction": direction, "level": level, "price": price,
                      "distance_pct": distance, "time": event_time,
                      "in_zone": in_zone, "correct_side": correct_side}
            self.on_price_update(update)
            alert_key = self._alert_key(symbol, name)
            with self._lock:
                # Сохраняем блокировку при изменении цены Today High/Low.
                # При смене календарного периода удаляем старое состояние.
                self._prune_level_state(symbol, name, alert_key)
                was_active = alert_key in self._active_alerts
                is_new = False
                # Гистерезис действует только пока цена остаётся на ожидаемой
                # стороне уровня. Пересечение уровня немедленно завершает подход.
                if was_active and correct_side and distance <= 0.7:
                    active_now.add(alert_key)
                elif in_zone and not was_active:
                    self._active_alerts.add(alert_key)
                    self._approach_started[alert_key] = now
                    self._confirmed_alerts.discard(alert_key)
                    active_now.add(alert_key)
                    is_new = True
                else:
                    is_new = False
            if in_zone and is_new:
                with self._lock:
                    candles = list(self._chart_candles.get(symbol, []))
                self.on_signal({**update, "candles": candles,
                    "details": f"Цена в {distance:.3f}% от уровня; касание ещё не подтверждено"})
        # Сбрасываем блокировку только после удаления дальше 0,7%.
        with self._lock:
            expired = {k for k in self._active_alerts if k[0] == symbol and k not in active_now}
            self._active_alerts.difference_update(expired)
            # Не допускаем подтверждения по таймеру уже завершившегося подхода.
            # Последнюю проверенную свечу сохраняем, чтобы не переоценить её
            # при повторном входе в зону в пределах той же минуты.
            for key in expired:
                self._approach_started.pop(key, None)

    @staticmethod
    def _is_confirmation_fresh(close_time_ms: int, approach_started: float | None,
                               now: float | None = None, open_time_ms: int | None = None) -> bool:
        """Свеча должна целиком сформироваться после начала подхода и не старше 5 минут."""
        if approach_started is None:
            return False
        now = time.time() if now is None else float(now)
        started = float(approach_started)
        candle_closed_at = int(close_time_ms) / 1000.0
        candle_opened_at = (
            int(open_time_ms) / 1000.0 if open_time_ms is not None else candle_closed_at
        )
        return (
            candle_opened_at >= started
            and candle_closed_at >= started
            and 0 <= now - started <= 300
        )

    @staticmethod
    def evaluate_rejection(candle, level, direction):
        """Проверяет выраженное отвержение закрытой свечой; возвращает метрики или None."""
        o, h, low, close = map(float, (candle[1], candle[2], candle[3], candle[4]))
        span = h - low
        if span <= 0:
            return None
        body = abs(close - o)
        body = max(body, span * 0.001)
        upper_wick = h - max(o, close)
        lower_wick = min(o, close) - low
        close_position = (close - low) / span
        if direction == "SHORT":
            touched = h >= level
            ratio = upper_wick / body
            valid = touched and close < level and ratio >= 1.5 and close_position <= 0.35
        else:
            touched = low <= level
            ratio = lower_wick / body
            valid = touched and close > level and ratio >= 1.5 and close_position >= 0.65
        if not valid:
            return None
        return {"wick_body_ratio": ratio, "close_position": close_position,
                "candle_open": o, "candle_high": h, "candle_low": low, "candle_close": close}

    def _claim_confirmation(self, key, candle, level, direction, now=None):
        """Атомарно проверяет активный цикл и захватывает одну свечу для подтверждения."""
        close_time = int(candle[6])
        with self._lock:
            if key not in self._active_alerts:
                return None
            if self._last_confirmed_candle.get(key) == close_time:
                return None
            self._last_confirmed_candle[key] = close_time
            started = self._approach_started.get(key)
            if (key in self._confirmed_alerts
                    or not self._is_confirmation_fresh(
                        close_time, started, now=now, open_time_ms=int(candle[0])
                    )):
                return None
            metrics = self.evaluate_rejection(candle, level, direction)
            if not metrics:
                return None
            self._confirmed_alerts.add(key)
            return metrics

    def _release_confirmation_claim(self, key, close_time):
        """Разрешает повторную попытку, если обработчик не смог принять событие."""
        with self._lock:
            self._confirmed_alerts.discard(key)
            if self._last_confirmed_candle.get(key) == close_time:
                self._last_confirmed_candle.pop(key, None)

    def _confirmation_loop(self):
        """Проверяет только завершённые 1m-свечи и публикует подтверждённые реакции."""
        with requests.Session() as session:
            while not self._stop.is_set():
                with self._lock:
                    symbols = list(self._symbols)
                    levels_by_symbol = {k: list(v) for k, v in self._levels_cache.items()}
                for symbol in symbols:
                    if self._stop.is_set():
                        break
                    try:
                        candles = fetch_klines(session, symbol, "1m", 80)
                        if len(candles) < 3:
                            continue
                        with self._lock:
                            self._chart_candles[symbol] = list(candles[:-1])
                        closed = candles[-2]
                        close_time = int(closed[6])
                        for name, level, group in levels_by_symbol.get(symbol, []):
                            direction = "LONG" if name in ("PDL", "PWL", "Today Low") else "SHORT"
                            key = self._alert_key(symbol, name)
                            with self._lock:
                                self._prune_level_state(symbol, name, key)
                            metrics = self._claim_confirmation(
                                key, closed, level, direction
                            )
                            if not metrics:
                                continue
                            close = float(closed[4])
                            distance = abs(close - level) / level * 100 if level else 0
                            event = {"symbol": symbol, "level_name": name, "level_group": group,
                                "level": level, "price": close, "distance_pct": distance,
                                "time": close_time, "candle_open_time": int(closed[0]),
                                "direction": direction, "candles": candles[:-1],
                                "details": "Выраженное отвержение уровня на закрытой минутной свече", **metrics}
                            try:
                                self.on_confirmation(event)
                            except Exception:
                                self._release_confirmation_claim(key, close_time)
                                raise
                    except Exception as exc:
                        self.on_status(f"Проверка реакции {symbol}: {str(exc)[:90]}")
                self._stop.wait(12)

    def _ws_loop(self):
        """Подключается к общему потоку котировок Binance USDⓈ-M Futures."""
        while not self._stop.is_set():
            try:
                def on_message(_ws, message):
                    try:
                        payload = json.loads(message)
                        if isinstance(payload, dict):
                            payload = [payload]
                        with self._lock:
                            tracked = set(self._symbols)
                        for item in payload:
                            symbol = item.get("s")
                            if symbol in tracked:
                                # Поле c в !ticker@arr содержит последнюю цену.
                                self._handle_price(symbol, item.get("c", 0), source="websocket", event_time_ms=item.get("E"))
                    except Exception as exc:
                        self.on_status(f"Ошибка обработки WebSocket: {str(exc)[:100]}")

                def on_error(_ws, error):
                    if not self._stop.is_set():
                        self.on_status(f"WebSocket Binance: {str(error)[:100]}")

                def on_open(_ws):
                    self.on_status("WebSocket Binance подключён · получаем поток цен")

                self._ws_app = websocket.WebSocketApp(
                    self.WS_URL, on_message=on_message, on_error=on_error, on_open=on_open
                )
                self._ws_app.run_forever(ping_interval=150, ping_timeout=20)
            except Exception as exc:
                if not self._stop.is_set():
                    self.on_status(f"Не удалось подключить WebSocket: {str(exc)[:100]}")
            finally:
                self._ws_app = None
            if not self._stop.is_set():
                self.on_status("WebSocket отключён. Повторное подключение через 5 секунд…")
                self._stop.wait(5)
