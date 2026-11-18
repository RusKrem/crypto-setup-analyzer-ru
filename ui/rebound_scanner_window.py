"""Окно фонового сканера отскоков."""
import threading
import tkinter as tk
from datetime import datetime, timezone
from tkinter import messagebox, ttk

from crypto_setup_analyzer.rebound_scanner import ReboundScanner
from crypto_setup_analyzer.telegram_notifier import TelegramNotifier
from infrastructure.storage import Storage


class ReboundScannerWindow:
    def __init__(self, parent):
        self.parent = parent
        self.window = tk.Toplevel(parent)
        self.window.title("Сканер отскоков | Reversal Lab | Binance Futures USDT-M")
        self.window.geometry("1250x620")
        self.window.minsize(900, 420)
        self.status = tk.StringVar(value="Сканер остановлен.")
        self.count = tk.StringVar(value="Альткоинов: список ещё не загружен")

        top = ttk.Frame(self.window, padding=8)
        top.pack(fill="x")
        ttk.Label(top, textvariable=self.count).pack(side="left")
        ttk.Button(top, text="Запустить", command=self.start).pack(side="left", padx=8)
        ttk.Button(top, text="Остановить", command=self.stop).pack(side="left")
        ttk.Button(top, text="Проверить Telegram", command=self.test_telegram).pack(side="left", padx=8)
        ttk.Label(top, text="30 альткоинов · список каждые 15 минут · цены в реальном времени · порог 0,5%").pack(side="right")
        ttk.Label(self.window, textvariable=self.status, anchor="w", padding=(8, 2)).pack(fill="x")

        frame = ttk.Frame(self.window, padding=8)
        frame.pack(fill="both", expand=True)
        columns = ("time", "symbol", "group", "level", "level_price", "price", "distance", "trend", "status", "details")
        self.table = ttk.Treeview(frame, columns=columns, show="headings", height=18)
        labels = {
            "time": "Время UTC", "symbol": "Пара", "group": "Группа", "level": "Уровень",
            "level_price": "Цена уровня", "price": "Текущая цена", "distance": "До уровня",
            "trend": "Динамика", "status": "Состояние", "details": "Предупреждение"
        }
        widths = {"time": 145, "symbol": 105, "group": 150, "level": 120,
                  "level_price": 115, "price": 115, "distance": 90, "trend": 125,
                  "status": 125, "details": 300}
        for col in columns:
            self.table.heading(col, text=labels[col])
            self.table.column(col, width=widths[col], minwidth=70, stretch=(col == "details"))
        # Сетка надёжнее pack: обе полосы прокрутки всегда остаются видимыми.
        yscroll = ttk.Scrollbar(frame, orient="vertical", command=self.table.yview)
        xscroll = ttk.Scrollbar(frame, orient="horizontal", command=self.table.xview)
        self.table.configure(yscrollcommand=yscroll.set, xscrollcommand=xscroll.set)
        self.table.grid(row=0, column=0, sticky="nsew")
        yscroll.grid(row=0, column=1, sticky="ns")
        xscroll.grid(row=1, column=0, sticky="ew")
        frame.rowconfigure(0, weight=1)
        frame.columnconfigure(0, weight=1)

        # Колесо мыши: вертикальная прокрутка, Shift + колесо: горизонтальная.
        self.table.bind("<MouseWheel>", self._on_mousewheel)
        self.table.bind("<Shift-MouseWheel>", self._on_shift_mousewheel)
        self.table.bind("<Button-4>", self._on_linux_wheel)
        self.table.bind("<Button-5>", self._on_linux_wheel)

        ttk.Label(
            self.window,
            text="Показываются уровни всех отслеживаемых монет. Предупреждение появляется при приближении "
                 "цены к уровню на 0,5%. Касание и вход не подтверждаются. Без реальных ордеров.",
            anchor="w", padding=8
        ).pack(fill="x")

        self.telegram = TelegramNotifier()
        self.storage = Storage()
        self._row_ids = {}
        # Последняя дистанция по каждой паре/уровню для определения направления.
        self._last_distances = {}
        self.scanner = ReboundScanner(
            on_status=lambda message: self._safe_after(self.status.set, message),
            on_signal=self.handle_signal,
            on_symbols=lambda count: self._safe_after(
                self.count.set, f"Альткоинов в списке: {count} · обновление каждые 15 минут"
            ),
            on_price_update=lambda update: self._safe_after(self.update_price, update),
            on_confirmation=self.handle_confirmation,
            batch_size=30, interval_seconds=3, symbol_refresh_seconds=900, levels_refresh_seconds=60,
            state_path=self.telegram.base_dir / "data" / "rebound_scanner_state.json"
        )
        self.window.protocol("WM_DELETE_WINDOW", self.close)

    def _on_mousewheel(self, event):
        """Вертикальная прокрутка на Windows/macOS."""
        delta = getattr(event, "delta", 0)
        if delta:
            # На Windows delta обычно кратна 120; на macOS значения меньше.
            steps = int(-delta / 120) if abs(delta) >= 120 else (-1 if delta > 0 else 1)
            self.table.yview_scroll(steps, "units")
        return "break"

    def _on_shift_mousewheel(self, event):
        """Горизонтальная прокрутка при удержании Shift."""
        delta = getattr(event, "delta", 0)
        if delta:
            steps = int(-delta / 120) if abs(delta) >= 120 else (-1 if delta > 0 else 1)
            self.table.xview_scroll(steps, "units")
        return "break"

    def _on_linux_wheel(self, event):
        """Поддержка колеса мыши Button-4/Button-5 в Linux."""
        direction = -1 if event.num == 4 else 1
        if getattr(event, "state", 0) & 0x0001:
            self.table.xview_scroll(direction, "units")
        else:
            self.table.yview_scroll(direction, "units")
        return "break"

    def _safe_after(self, callback, *args):
        try:
            self.window.after(0, callback, *args)
        except (tk.TclError, RuntimeError):
            pass

    def handle_signal(self, signal):
        """Показывает предупреждение, журналирует его и ставит карточку в Telegram."""
        try:
            self.storage.add_reaction_event({**signal, "event_type": "APPROACH"})
        except Exception as exc:
            self._safe_after(self.status.set, f"Журнал предупреждений: {exc}")
        self._safe_after(self.add_signal, signal)
        if not self.telegram.configured:
            return

        def send():
            ok, message = self.telegram.send_alert(signal)
            self._safe_after(self.status.set, f"Telegram: {message}")
        threading.Thread(target=send, daemon=True).start()

    def handle_confirmation(self, signal):
        """Отображает подтверждённую реакцию, журналирует и отправляет карточку."""
        try:
            self.storage.add_reaction_event({**signal, "event_type": "CONFIRMED"})
        except Exception as exc:
            self._safe_after(self.status.set, f"Журнал подтверждений: {exc}")
        def update_status():
            self.status.set(f"РЕАКЦИЯ ПОДТВЕРЖДЕНА: {signal['symbol']} · {signal['direction']} · {signal['level_name']}")
            key = (signal["symbol"], signal["level_name"])
            row_id = self._row_ids.get(key)
            if row_id and self.table.exists(row_id):
                self.table.set(row_id, "status", "РЕАКЦИЯ ПОДТВЕРЖДЕНА")
                self.table.set(row_id, "details", f"Отвержение: тень/тело {signal['wick_body_ratio']:.2f}")
                self.table.item(row_id, tags=("CONFIRMED",))
            self.table.tag_configure("CONFIRMED", foreground="#159b65")
        self._safe_after(update_status)
        if not self.telegram.configured:
            return
        def send():
            ok, message = self.telegram.send_confirmation(signal)
            self._safe_after(self.status.set, f"Telegram: {message}")
        threading.Thread(target=send, daemon=True).start()

    def test_telegram(self):
        self.telegram = TelegramNotifier()
        if not self.telegram.configured:
            messagebox.showwarning(
                "Telegram не настроен",
                "Откройте файл .env рядом с START.bat и заполните TELEGRAM_BOT_TOKEN и TELEGRAM_CHAT_ID.\n\n"
                "Затем перезапустите программу. Не отправляйте токен в чат.",
                parent=self.window
            )
            return
        self.status.set("Проверяю соединение с Telegram…")

        def send_test():
            ok, message = self.telegram.send_text(
                "🧪 REVERSAL LAB | ТЕСТ СВЯЗИ\n\n"
                "Telegram подключён. Сканер будет отправлять предупреждения о приближении цены к ключевым уровням.\n"
                "⚠️ Это уведомления, не подтверждённые торговые входы."
            )
            def show_result():
                if ok:
                    messagebox.showinfo("Telegram", message, parent=self.window)
                else:
                    messagebox.showerror("Telegram", message, parent=self.window)
                self.status.set(message)
            self._safe_after(show_result)
        threading.Thread(target=send_test, daemon=True).start()

    def start(self):
        self.scanner.start()
        self.status.set("Запускаю фоновый сканер…")

    def stop(self):
        self.scanner.stop()
        self.status.set("Останавливаю сканер…")

    @staticmethod
    def _price(value):
        return f"{float(value):.10g}"

    def _trend(self, update):
        """Определяет, сокращается или увеличивается расстояние до уровня."""
        key = (update["symbol"], update["level_name"])
        current = float(update["distance_pct"])
        previous = self._last_distances.get(key)
        self._last_distances[key] = current
        if previous is None:
            return "— Первый замер", "WATCH"
        delta = current - previous
        # Фильтруем микроколебания округления, чтобы надпись не мигала.
        if abs(delta) < 0.001:
            return "→ Без изменений", "WATCH"
        if delta < 0:
            return f"↓ Ближе ({abs(delta):.3f} п.п.)", "APPROACH"
        return f"↑ Дальше (+{delta:.3f} п.п.)", "WATCH"

    def _values(self, update, state, details, trend=None):
        stamp = datetime.fromtimestamp(update["time"] / 1000, tz=timezone.utc)
        if trend is None:
            trend = "—"
        return (
            stamp.strftime("%Y-%m-%d %H:%M:%S"), update["symbol"], update.get("level_group", ""),
            update["level_name"], self._price(update["level"]), self._price(update["price"]),
            f'{update["distance_pct"]:.3f}%', trend, state, details
        )

    def _sort_rows(self):
        """Сортирует все строки по расстоянию до уровня, ближайшие сверху."""
        rows = []
        for item_id in self.table.get_children(""):
            values = self.table.item(item_id, "values")
            try:
                distance = float(str(values[6]).replace("%", "").replace(",", "."))
            except (IndexError, TypeError, ValueError):
                distance = float("inf")
            rows.append((distance, item_id))
        for index, (_, item_id) in enumerate(sorted(rows, key=lambda item: item[0])):
            self.table.move(item_id, "", index)

    def add_signal(self, signal):
        """Выделяет приближение, сохраняя строку мониторинга для этой пары и уровня."""
        key = (signal["symbol"], signal["level_name"])
        row_id = self._row_ids.get(key)
        trend, _trend_tag = self._trend(signal)
        values = self._values(
            signal, "ПРИБЛИЖЕНИЕ",
            signal.get("details", f'Цена в {signal["distance_pct"]:.3f}% от уровня; касание ещё не подтверждено'),
            trend
        )
        if row_id and self.table.exists(row_id):
            self.table.item(row_id, values=values, tags=("APPROACH",))
            self.table.move(row_id, "", 0)
        else:
            row_id = self.table.insert("", 0, values=values, tags=("APPROACH",))
            self._row_ids[key] = row_id
        self.table.tag_configure("APPROACH", foreground="#b36b00")
        self.table.tag_configure("WATCH", foreground="#667788")
        self._sort_rows()
        self.status.set(
            f'Приближение: {signal["symbol"]} к {signal["level_name"]} ({signal["distance_pct"]:.3f}%)'
        )

    def update_price(self, update):
        """Обновляет цену, не стирая уже полученный статус подтверждения."""
        key = (update["symbol"], update["level_name"])
        in_zone = bool(update.get("in_zone", False))
        state = "ПРИБЛИЖЕНИЕ" if in_zone else "Наблюдение"
        details = (
            f'Цена в {update["distance_pct"]:.3f}% от уровня'
            if in_zone else "Отслеживание цены и уровня"
        )
        trend, trend_tag = self._trend(update)
        tag = "APPROACH" if in_zone else "WATCH"
        row_id = self._row_ids.get(key)

        if row_id and self.table.exists(row_id):
            previous_state = self.table.set(row_id, "status")
            if previous_state == "РЕАКЦИЯ ПОДТВЕРЖДЕНА":
                state = previous_state
                details = self.table.set(row_id, "details")
                tag = "CONFIRMED"

        values = self._values(update, state, details, trend)
        if row_id and self.table.exists(row_id):
            self.table.item(row_id, values=values, tags=(tag,))
        else:
            # Строка появляется даже вне зоны предупреждения.
            row_id = self.table.insert("", "end", values=values, tags=(tag,))
            self._row_ids[key] = row_id

        self.table.tag_configure("APPROACH", foreground="#b36b00")
        self.table.tag_configure("WATCH", foreground="#667788")
        self.table.tag_configure("CONFIRMED", foreground="#159b65")
        self._sort_rows()

    def close(self):
        self.scanner.stop()
        self.window.destroy()


if __name__ == "__main__":
    pass
