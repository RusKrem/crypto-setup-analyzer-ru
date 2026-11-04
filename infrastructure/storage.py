"""Хранилище SQLite для сигналов и виртуальных сделок."""
import sqlite3
from pathlib import Path

class Storage:
    """Сохраняет состояние между запусками приложения."""
    def __init__(self, path="data/crypto_analyzer.db"):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._initialize()

    def _connect(self):
        """Создаёт отдельное соединение для текущей операции."""
        connection = sqlite3.connect(self.path, timeout=10)
        connection.row_factory = sqlite3.Row
        return connection

    def _initialize(self):
        """Создаёт таблицы, если база запускается впервые."""
        with self._connect() as db:
            db.execute("""CREATE TABLE IF NOT EXISTS signals (
                signal_key TEXT PRIMARY KEY, symbol TEXT NOT NULL,
                direction TEXT NOT NULL, level_name TEXT NOT NULL,
                level REAL NOT NULL, price REAL NOT NULL,
                signal_time INTEGER NOT NULL, details TEXT NOT NULL DEFAULT '')""")
            db.execute("""CREATE TABLE IF NOT EXISTS trades (
                trade_id TEXT PRIMARY KEY, symbol TEXT NOT NULL,
                direction TEXT NOT NULL, signal_time INTEGER NOT NULL,
                entry REAL NOT NULL, stop REAL NOT NULL, target REAL NOT NULL,
                level_name TEXT NOT NULL, level REAL NOT NULL,
                status TEXT NOT NULL DEFAULT 'OPEN', exit_price REAL,
                exit_time INTEGER, result_pct REAL)""")
            db.execute("CREATE INDEX IF NOT EXISTS idx_trades_status ON trades(status)")
            db.execute("CREATE INDEX IF NOT EXISTS idx_signals_time ON signals(signal_time)")
            db.execute("""CREATE TABLE IF NOT EXISTS reaction_events (
                event_id TEXT PRIMARY KEY, symbol TEXT NOT NULL, direction TEXT NOT NULL,
                level_name TEXT NOT NULL, level REAL NOT NULL, price REAL NOT NULL,
                event_time INTEGER NOT NULL, event_type TEXT NOT NULL, details TEXT NOT NULL DEFAULT '')""")
            db.execute("CREATE INDEX IF NOT EXISTS idx_reaction_events_time ON reaction_events(event_time)")

    def add_signal(self, signal):
        """Сохраняет сигнал; повтор того же ключа безопасно игнорируется."""
        key = signal.get("signal_key") or "|".join(str(signal[k]) for k in
            ("symbol", "direction", "level_name", "time"))
        with self._connect() as db:
            cursor = db.execute("""INSERT OR IGNORE INTO signals
                (signal_key, symbol, direction, level_name, level, price, signal_time, details)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                (key, signal["symbol"], signal["direction"], signal["level_name"],
                 signal["level"], signal["price"], signal["time"], signal.get("details", "")))
            return cursor.rowcount == 1


    def add_reaction_event(self, event):
        """Записывает предупреждения и подтверждённые реакции для последующей статистики."""
        import uuid
        event_id = event.get("event_id") or uuid.uuid4().hex
        with self._connect() as db:
            db.execute("""INSERT OR IGNORE INTO reaction_events
                (event_id, symbol, direction, level_name, level, price, event_time, event_type, details)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (event_id, event["symbol"], event.get("direction", "LONG" if event.get("level_name") in ("PDL", "PWL", "Today Low") else "SHORT"),
                 event["level_name"], float(event["level"]), float(event["price"]), int(event["time"]),
                 event.get("event_type", "APPROACH"), event.get("details", "")))
        return event_id

    def recent_reaction_events(self, limit=1000):
        with self._connect() as db:
            rows = db.execute("SELECT * FROM reaction_events ORDER BY event_time DESC LIMIT ?", (int(limit),)).fetchall()
            return [dict(row) for row in rows]

    def save_trade(self, trade):
        """Добавляет сделку или обновляет её состояние."""
        with self._connect() as db:
            db.execute("""INSERT INTO trades
                (trade_id, symbol, direction, signal_time, entry, stop, target,
                 level_name, level, status, exit_price, exit_time, result_pct)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(trade_id) DO UPDATE SET
                status=excluded.status, exit_price=excluded.exit_price,
                exit_time=excluded.exit_time, result_pct=excluded.result_pct""",
                (trade["trade_id"], trade["symbol"], trade["direction"], trade["signal_time"],
                 trade["entry"], trade["stop"], trade["target"], trade["level_name"],
                 trade["level"], trade.get("status", "OPEN"), trade.get("exit_price"),
                 trade.get("exit_time"), trade.get("result_pct")))

    def open_trades(self):
        """Возвращает все сделки, которые ещё требуют мониторинга."""
        with self._connect() as db:
            rows = db.execute("SELECT * FROM trades WHERE status='OPEN' ORDER BY signal_time").fetchall()
            return [dict(row) for row in rows]

    def recent_trades(self, limit=500):
        """Возвращает последние сделки для таблицы и статистики."""
        with self._connect() as db:
            rows = db.execute("SELECT * FROM trades ORDER BY signal_time DESC LIMIT ?", (int(limit),)).fetchall()
            return [dict(row) for row in rows]
