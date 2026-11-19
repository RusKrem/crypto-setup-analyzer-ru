from pathlib import Path
import threading
import tkinter as tk
from tkinter import ttk, filedialog, messagebox
import pandas as pd
import matplotlib
matplotlib.use("TkAgg")
import matplotlib.pyplot as plt
from matplotlib.patches import Rectangle
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg, NavigationToolbar2Tk
from services.market_data_service import MarketDataService
from services.indicator_service import IndicatorService
from ui.rebound_scanner_window import ReboundScannerWindow

ROOT=Path(__file__).resolve().parents[1]

class App:
    def __init__(self, root):
        self.root=root
        self._rebound_scanner_window = None
        self.market_data = MarketDataService()
        self.indicators = IndicatorService()
        root.title("Crypto Setup Analyzer | Визуальный анализатор")
        root.geometry("1400x880")
        root.minsize(1000,650)
        self.df=None
        self.events=pd.DataFrame()
        self.levels=tk.BooleanVar(value=True)
        self.today_hilo=tk.BooleanVar(value=True)
        # Отдельные переключатели групп ключевых уровней.
        self.weekly_levels=tk.BooleanVar(value=True)
        self.swing_levels=tk.BooleanVar(value=False)
        self.session_levels=tk.BooleanVar(value=False)
        self.fvg=tk.BooleanVar(value=True)
        self.sweeps=tk.BooleanVar(value=True)
        self.all_tf_fvg=tk.BooleanVar(value=False)
        self.current_price_line=tk.BooleanVar(value=True)
        self.hhll_enabled=tk.BooleanVar(value=True)
        self.volume_profile_enabled=tk.BooleanVar(value=False)
        self.order_blocks_enabled=tk.BooleanVar(value=True)
        self._price_line_artist=None
        self._profile_ax=None
        self.mtf_data={}
        self.mtf_events={}
        self.status=tk.StringVar(value="Загрузи исторические данные или открой CSV.")
        self.symbols=["NEARUSDT"]
        self._original_xlim=None
        self._visible_count=300
        self.loaded_interval=None
        self.loaded_symbol=None
        self.live_price_enabled=True
        self._last_live_price=None
        self._drag_start=None
        self._drag_xlim=None
        self._drag_ylim=None
        self.live_candles=tk.BooleanVar(value=True)
        self._last_candle_poll=0
        self._price_request_running = False
        self._candle_request_running = False
        self._download_request_running = False
        self._last_analysis_signature = None
        self._ui()
        self._empty()
        self.root.after(250, self.refresh_symbols)  # load available pairs automatically on startup
        self.root.after(500, self.update_live_price)
        self.root.after(1200, self.update_live_candles)

    def _ui(self):
        bar=ttk.Frame(self.root,padding=8); bar.pack(fill="x")
        ttk.Label(bar,text="Инструмент:").pack(side="left")
        self.symbol=tk.StringVar(value="NEARUSDT")
        self.symbol_box=ttk.Combobox(bar,textvariable=self.symbol,values=self.symbols,state="normal",width=15)
        self.symbol_box.pack(side="left",padx=(4,4))
        self.symbol_box.bind("<KeyRelease>", self.filter_symbols)
        ttk.Button(bar,text="Обновить валюты",command=self.refresh_symbols).pack(side="left",padx=(0,10))
        ttk.Label(bar,text="Таймфрейм:").pack(side="left")
        self.interval=tk.StringVar(value="5m")
        ttk.Combobox(bar,textvariable=self.interval,values=["1m","3m","5m","15m","30m","1h","2h","4h","1d"],state="readonly",width=6).pack(side="left",padx=(4,12))
        ttk.Label(bar,text="Дней:").pack(side="left")
        self.days=tk.StringVar(value="3")
        ttk.Combobox(bar,textvariable=self.days,values=["1","2","3","7","14","30"],state="readonly",width=5).pack(side="left",padx=(4,12))
        ttk.Button(bar,text="Загрузить данные",command=self.download).pack(side="left",padx=3)
        ttk.Button(bar,text="Открыть CSV",command=self.open_csv).pack(side="left",padx=3)
        ttk.Button(bar,text="Сканер отскоков альткоинов",command=self.open_rebound_scanner).pack(side="left",padx=3)
        ttk.Button(bar,text="Обновить график",command=self.refresh).pack(side="left",padx=3)
        self.live_price_var=tk.StringVar(value="Цена сейчас: загружаю…")
        self.live_price_label=ttk.Label(bar,textvariable=self.live_price_var,font=("Segoe UI",10,"bold"),foreground="#087f5b")
        self.live_price_label.pack(side="left",padx=(12,4))
        ttk.Checkbutton(bar,text="Свечи в реальном времени",variable=self.live_candles,command=self.toggle_live_candles).pack(side="left",padx=(8,4))
        # Индикаторы доступны как отдельные переключатели с галочками.
        indicator_bar=ttk.Frame(self.root, padding=(8,0,8,4))
        indicator_bar.pack(fill="x")
        indicator_items=[
            ("Ключевые уровни PDH / PDL", self.levels),
            ("High / Low дня", self.today_hilo),
            ("FVG", self.fvg),
            ("Снятие ликвидности", self.sweeps),
            ("FVG всех ТФ", self.all_tf_fvg),
            ("Линия цены", self.current_price_line),
            ("HH / HL / LH / LL", self.hhll_enabled),
            ("Профиль объёма", self.volume_profile_enabled),
            ("Ордер-блоки (OB)", self.order_blocks_enabled),
        ]
        for label, variable in indicator_items:
            ttk.Checkbutton(indicator_bar,text=label,variable=variable,command=self.refresh).pack(side="left",padx=(0,9),pady=2)
        # Панель ключевых уровней вынесена на отдельную строку, чтобы все группы были доступны.
        levels_bar=ttk.LabelFrame(self.root,text="Ключевые уровни",padding=(8,2))
        levels_bar.pack(fill="x",padx=8,pady=(0,4))
        level_groups=[
            ("Дневные PDH / PDL",self.levels),
            ("Недельные PWH / PWL / PWC",self.weekly_levels),
            ("Торговые сессии",self.session_levels),
        ]
        for label, variable in level_groups:
            ttk.Checkbutton(levels_bar,text=label,variable=variable,command=self.refresh).pack(side="left",padx=(0,12),pady=2)
        ttk.Button(indicator_bar,text="Загрузить FVG всех ТФ",command=self.download_all_tf_fvg).pack(side="left",padx=3)
        # Основной график цены и отдельная панель профиля объёма; легенда находится снизу.
        self.fig=plt.figure(figsize=(12,6.5),dpi=100)
        self._gs=self.fig.add_gridspec(1,2,width_ratios=[4.8,1.2],wspace=0.04)
        self.ax=self.fig.add_subplot(self._gs[0,0])
        self._profile_ax=self.fig.add_subplot(self._gs[0,1],sharey=self.ax)
        self.fig.subplots_adjust(bottom=0.22,top=0.92,left=0.06,right=0.98)
        self.canvas=FigureCanvasTkAgg(self.fig,master=self.root)
        self.canvas.get_tk_widget().pack(fill="both",expand=True,padx=8)
        toolbar=ttk.Frame(self.root); toolbar.pack(fill="x",padx=8)
        nav=NavigationToolbar2Tk(self.canvas,toolbar,pack_toolbar=False)
        nav.update()
        for child in toolbar.winfo_children(): child.pack(side="left")
        ttk.Separator(toolbar,orient="vertical").pack(side="left",fill="y",padx=5)
        ttk.Button(toolbar,text="− Приблизить",command=lambda:self.zoom_plot(0.75)).pack(side="left",padx=2)
        ttk.Button(toolbar,text="+ Отдалить",command=lambda:self.zoom_plot(1.33)).pack(side="left",padx=2)
        ttk.Button(toolbar,text="Сбросить масштаб",command=self.reset_zoom).pack(side="left",padx=2)
        self.canvas.mpl_connect("scroll_event",self.on_scroll_zoom)
        self.canvas.mpl_connect("button_press_event",self.on_double_click)
        # Drag with the left mouse button to move freely on both axes.
        self.canvas.get_tk_widget().configure(cursor="fleur")
        self.canvas.mpl_connect("button_press_event",self.on_pan_start)
        self.canvas.mpl_connect("motion_notify_event",self.on_pan_move)
        self.canvas.mpl_connect("button_release_event",self.on_pan_end)
        frame=ttk.LabelFrame(self.root,text="Найденные события",padding=5); frame.pack(fill="x",padx=8,pady=4)
        cols=("time","type","direction","price","details")
        self.table=ttk.Treeview(frame,columns=cols,show="headings",height=5)
        names={"time":"Время (UTC)","type":"Событие","direction":"Направление","price":"Цена","details":"Описание"}
        widths={"time":150,"type":180,"direction":100,"price":110,"details":600}
        for c in cols:
            self.table.heading(c,text=names[c]); self.table.column(c,width=widths[c],minwidth=70,stretch=c=="details")
        scroll=ttk.Scrollbar(frame,orient="vertical",command=self.table.yview)
        self.table.configure(yscrollcommand=scroll.set)
        self.table.pack(side="left",fill="x",expand=True); scroll.pack(side="right",fill="y")
        ttk.Label(self.root,textvariable=self.status,anchor="w",relief="sunken",padding=5).pack(fill="x",side="bottom")

    def update_live_price(self):
        """Получает цену в фоновом потоке, чтобы не блокировать интерфейс."""
        if not self._price_request_running:
            symbol = self.loaded_symbol or self.symbol.get().strip().upper()
            if symbol:
                self._price_request_running = True
                def worker():
                    try:
                        price = self.market_data.realtime_price(symbol)
                        error = None
                    except Exception as exc:
                        price, error = None, str(exc)
                    def apply_result():
                        self._price_request_running = False
                        if error:
                            self.live_price_var.set(f"{symbol}: цена временно недоступна")
                            return
                        # Игнорируем ответ старого инструмента, если пользователь уже переключился.
                        active_symbol = self.loaded_symbol or self.symbol.get().strip().upper()
                        if symbol != active_symbol:
                            return
                        previous = self._last_live_price
                        arrow = "" if previous is None or price == previous else (" ▲" if price > previous else " ▼")
                        self.live_price_var.set(f"{symbol}: {price:.10g}{arrow} · обновление каждые 5 сек")
                        self._last_live_price = price
                        if self.current_price_line.get() and self.df is not None and not self.df.empty:
                            # Обновляем только линию цены, не перестраивая весь график.
                            if getattr(self, "_price_line_artist", None) is not None:
                                self._price_line_artist.set_ydata([price, price])
                            if getattr(self, "_price_line_label", None) is not None:
                                self._price_line_label.set_text(f"{price:.8g}")
                            self.canvas.draw_idle()
                    self.root.after(0, apply_result)
                threading.Thread(target=worker, daemon=True).start()
        self.root.after(5000, self.update_live_price)

    def toggle_live_candles(self):
        if self.live_candles.get():
            self.status.set("Обновление свечей в реальном времени включено.")
            self.root.after(100, self.update_live_candles)
        else:
            self.status.set("Автообновление свечей выключено.")

    def update_live_candles(self):
        """Загружает новые свечи в фоне и пересчитывает индикаторы только при изменениях."""
        if self.live_candles.get() and self.df is not None and not self.df.empty and self.loaded_interval in ("1m","3m","5m","15m","30m","1h","2h","4h","1d") and not self._candle_request_running:
            symbol = self.loaded_symbol or self.symbol.get().strip().upper()
            interval = self.loaded_interval
            self._candle_request_running = True
            def worker():
                try:
                    fresh = self.market_data.latest_candles(symbol, interval, limit=3)
                    error = None
                except Exception as exc:
                    fresh, error = None, str(exc)
                def apply_result():
                    self._candle_request_running = False
                    if error:
                        self.status.set(f"Свечи: временная ошибка соединения ({error[:90]}). Повторю попытку.")
                        return
                    if symbol != self.loaded_symbol or interval != self.loaded_interval or self.df is None:
                        return
                    try:
                        old_count = len(self.df)
                        old_last = pd.to_datetime(self.df.timestamp.iloc[-1], utc=True)
                        old_close = float(self.df.close.iloc[-1]); old_high = float(self.df.high.iloc[-1])
                        old_low = float(self.df.low.iloc[-1]); old_volume = float(self.df.volume.iloc[-1])
                        combined = pd.concat([self.df.drop(columns=["PDH","PDL"], errors="ignore"), fresh], ignore_index=True)
                        combined["timestamp"] = pd.to_datetime(combined["timestamp"], utc=True)
                        combined = combined.sort_values("timestamp").drop_duplicates("timestamp", keep="last").reset_index(drop=True)
                        # Keep the same rolling history depth the user initially loaded.
                        # A hard 1200-row cap discards days/weeks needed for PDH/PDL and PWH/PWL.
                        combined = self.indicators.retain_live_history_depth(combined, old_count)
                        new_last = pd.to_datetime(combined.timestamp.iloc[-1], utc=True)
                        changed = (new_last != old_last or float(combined.close.iloc[-1]) != old_close or
                                   float(combined.high.iloc[-1]) != old_high or float(combined.low.iloc[-1]) != old_low or
                                   float(combined.volume.iloc[-1]) != old_volume)
                        if not changed:
                            return
                        self.df = self.indicators.add_levels(combined)
                        # Индикаторы обновляются только после фактического изменения свечей.
                        self.events = self.indicators.find_events(self.df)
                        self.reaction_events = self.indicators.find_price_reactions(self.df)
                        self.order_blocks = self.indicators.find_order_blocks(self.df)
                        self.refresh(preserve_view=True)
                        last_time = new_last.strftime("%Y-%m-%d %H:%M:%S UTC")
                        self.status.set(f"Свечи обновлены: {symbol} {interval}. Последняя свеча: {last_time}.")
                    except Exception as exc:
                        self.status.set(f"Не удалось обновить график: {str(exc)[:120]}")
                self.root.after(0, apply_result)
            threading.Thread(target=worker, daemon=True).start()
        self.root.after(5000, self.update_live_candles)

    def open_rebound_scanner(self):
        """Открывает одно окно сканера, поднимая существующее при повторном вызове."""
        existing = self._rebound_scanner_window
        if existing is not None:
            try:
                if existing.window.winfo_exists():
                    existing.window.deiconify()
                    existing.window.lift()
                    existing.window.focus_force()
                    return existing
            except Exception:
                pass
        self._rebound_scanner_window = ReboundScannerWindow(self.root)
        return self._rebound_scanner_window

    def refresh_symbols(self):
        """Load the exchange symbol list in a worker so startup/UI never freezes."""
        if getattr(self, "_symbols_loading", False):
            return
        self._symbols_loading = True
        self.status.set("Загружаю список доступных USDT-пар Binance Futures USDⓈ-M…")
        def worker():
            try:
                symbols = self.market_data.available_symbols()
                error = None if symbols else "Биржа вернула пустой список торговых пар."
            except Exception as exc:
                symbols, error = [], str(exc)
            def apply_result():
                self._symbols_loading = False
                current = self.symbol.get().strip().upper()
                if symbols:
                    if current and current not in symbols:
                        symbols.append(current)
                    self.symbols = sorted(set(symbols))
                    self.symbol_box.configure(values=self.symbols)
                    self.symbol.set(current or "NEARUSDT")
                    self.status.set(f"Список валют загружен: {len(self.symbols)} USDT-пар Binance Futures USDⓈ-M.")
                else:
                    self.status.set("Не удалось автоматически загрузить список валют. Можно ввести тикер вручную.")
                    # Do not show a modal dialog at startup; allow offline/manual use.
                    if error:
                        print(f"Symbol list error: {error}")
            self.root.after(0, apply_result)
        threading.Thread(target=worker, daemon=True).start()

    def filter_symbols(self, event=None):
        # Фильтруем большой список по введённому началу символа.
        typed=self.symbol.get().strip().upper()
        if not typed:
            matches=self.symbols
        else:
            matches=[item for item in self.symbols if typed in item]
        self.symbol_box.configure(values=matches[:500])

    def on_scroll_zoom(self,event):
        if event.inaxes != self.ax or event.xdata is None or event.ydata is None:
            return
        factor=0.75 if event.button=="up" else 1.33
        left,right=self.ax.get_xlim()
        bottom,top=self.ax.get_ylim()
        cx,cy=event.xdata,event.ydata
        self.ax.set_xlim(cx-(cx-left)*factor, cx+(right-cx)*factor)
        self.ax.set_ylim(cy-(cy-bottom)*factor, cy+(top-cy)*factor)
        self.canvas.draw_idle()

    def zoom_plot(self,factor):
        left,right=self.ax.get_xlim(); bottom,top=self.ax.get_ylim()
        cx=(left+right)/2; cy=(bottom+top)/2
        half_x=(right-left)*factor/2; half_y=(top-bottom)*factor/2
        self.ax.set_xlim(cx-half_x,cx+half_x)
        self.ax.set_ylim(cy-half_y,cy+half_y)
        self.canvas.draw_idle()

    def reset_zoom(self):
        if self.df is None or self.df.empty:
            return
        self.refresh(preserve_view=False)

    def on_double_click(self,event):
        if getattr(event,"dblclick",False):
            self._drag_start=None
            self._drag_xlim=None
            self._drag_ylim=None
            self.reset_zoom()

    def on_pan_start(self,event):
        if event.inaxes != self.ax or event.button != 1 or event.x is None or event.y is None:
            return
        if getattr(event,"dblclick",False):
            return
        self._drag_start=(event.x,event.y)
        self._drag_xlim=self.ax.get_xlim()
        self._drag_ylim=self.ax.get_ylim()

    def on_pan_move(self,event):
        if self._drag_start is None or self._drag_xlim is None or self._drag_ylim is None or event.x is None or event.y is None:
            return
        bbox=self.ax.get_window_extent()
        if bbox.width <= 0 or bbox.height <= 0:
            return
        left,right=self._drag_xlim
        bottom,top=self._drag_ylim
        dx=-(event.x-self._drag_start[0])/bbox.width*(right-left)
        dy=-(event.y-self._drag_start[1])/bbox.height*(top-bottom)
        # No data-bound clamping: the user can freely pan beyond the visible candles
        # and reposition the price range vertically inside the chart viewport.
        self.ax.set_xlim(left+dx,right+dx)
        self.ax.set_ylim(bottom+dy,top+dy)
        self.canvas.draw_idle()

    def on_pan_end(self,event):
        self._drag_start=None
        self._drag_xlim=None
        self._drag_ylim=None

    def _empty(self):
        self.ax.clear(); self.ax.set_title("Crypto Setup Analyzer | NEAR/USDT")
        self.ax.text(.5,.5,"Нажми «Загрузить данные» или «Открыть CSV»",ha="center",va="center",transform=self.ax.transAxes)
        self.canvas.draw_idle()

    def download(self):
        """Загружает историю в фоне, оставляя окно отзывчивым."""
        if self._download_request_running:
            self.status.set("Загрузка уже выполняется…")
            return
        symbol = self.symbol.get().strip().upper()
        interval = self.interval.get()
        days = int(self.days.get())
        if not symbol:
            messagebox.showwarning("Нет инструмента", "Введи тикер торговой пары.")
            return
        self._download_request_running = True
        self.status.set("Загружаю исторические свечи в фоновом режиме…")
        def worker():
            try:
                df = self.market_data.download_history(symbol, interval, days)
                error = None
                (ROOT/"data").mkdir(exist_ok=True)
                df.to_csv(ROOT/"data"/f"{symbol.lower()}_{interval}.csv", index=False)
            except Exception as exc:
                df, error = None, str(exc)
            def apply_result():
                self._download_request_running = False
                if error:
                    self.status.set("Не удалось загрузить данные.")
                    messagebox.showerror("Ошибка загрузки", f"{error}\n\nПопробуй позже или открой CSV.")
                    return
                self.set_data(df, f"Загружено {len(df)} свечей {symbol} {interval}.", symbol=symbol, interval=interval)
            self.root.after(0, apply_result)
        threading.Thread(target=worker, daemon=True).start()

    def download_all_tf_fvg(self):
        if self.df is None or self.df.empty:
            messagebox.showinfo("Сначала загрузите свечи", "Сначала загрузите основной график, затем нажмите эту кнопку.")
            return
        symbol=self.loaded_symbol or self.symbol.get().strip().upper()
        days=int(self.days.get())
        intervals=["1m","3m","5m","15m","30m","1h","2h","4h","1d"]
        self.status.set("Загружаю свечи для FVG всех таймфреймов. Это может занять некоторое время…")
        self.root.update_idletasks()
        failed=[]
        try:
            for tf in intervals:
                try:
                    candles=self.market_data.download_history(symbol,tf,days)
                    self.mtf_data[tf]=candles
                    self.mtf_events[tf]=self.indicators.find_events(candles)
                except Exception as exc:
                    failed.append(f"{tf}: {exc}")
            self.all_tf_fvg.set(True)
            total=sum(int((ev.type.astype(str).str.contains("FVG")).sum()) for ev in self.mtf_events.values() if not ev.empty)
            msg=f"FVG загружены для {len(self.mtf_data)} таймфреймов. Найдено зон: {total}."
            if failed: msg += " Не удалось загрузить: " + "; ".join(failed[:3])
            self.status.set(msg)
            self.refresh()
        except Exception as exc:
            messagebox.showerror("Ошибка загрузки FVG", str(exc))
            self.status.set("Не удалось загрузить FVG всех таймфреймов.")

    def open_csv(self):
        path=filedialog.askopenfilename(title="Выбери CSV со свечами",filetypes=[("CSV","*.csv"),("Все файлы","*.*")])
        if not path:return
        try:self.set_data(self.market_data.load_csv(path),f"Открыт файл {Path(path).name}.",symbol=Path(path).stem,interval="CSV")
        except Exception as e:messagebox.showerror("Ошибка CSV",str(e))

    def set_data(self,df,msg,symbol=None,interval=None):
        self.df=self.indicators.add_levels(df); self.events=self.indicators.find_events(self.df)
        self.reaction_events=self.indicators.find_price_reactions(self.df)
        self.order_blocks=self.indicators.find_order_blocks(self.df)
        self.mtf_data={}; self.mtf_events={}
        self.loaded_interval=interval or self.interval.get()
        self.loaded_symbol=symbol or self.symbol.get().strip().upper()
        self._last_live_price=None
        last_time=pd.to_datetime(self.df.timestamp.iloc[-1],utc=True).strftime("%Y-%m-%d %H:%M UTC")
        self.status.set(f"{msg} Последняя свеча: {last_time}. Фактический таймфрейм: {self.loaded_interval}. Событий: {len(self.events)}. Только визуальный анализ, без ордеров.")
        self.refresh()

    def refresh(self, preserve_view=False):
        old_xlim = self.ax.get_xlim() if preserve_view else None
        old_ylim = self.ax.get_ylim() if preserve_view else None
        if self.df is None or self.df.empty:
            self._empty(); return
        # Keep the full loaded history for calculations; only the candle rendering
        # window is limited to the latest 300 rows for UI responsiveness.
        history_df = self.df
        reference_levels = self.indicators.calculate_reference_levels(history_df)
        df=history_df.tail(300).reset_index(drop=True)
        self._visible_count=len(df)
        first_time=df.timestamp.iloc[0]
        ev=self.events[self.events.time>=first_time].copy() if not self.events.empty else self.events
        if hasattr(self,"reaction_events") and not self.reaction_events.empty:
            rev=self.reaction_events[self.reaction_events.time>=first_time].copy()
            if not rev.empty: ev=pd.concat([ev,rev],ignore_index=True).sort_values("time")
        # Convert source candle indices to positions in the visible chart window.
        time_to_x={t:i for i,t in enumerate(df.timestamp)}
        def chart_x_for_time(t):
            # Map higher-timeframe candle timestamps to the nearest candle on the visible chart.
            if t in time_to_x: return time_to_x[t]
            try:
                ts=pd.Timestamp(t)
                positions=df.timestamp.searchsorted(ts,side="left")
                if positions < len(df): return int(positions)
            except Exception:
                pass
            return None
        # Remove previous figure-level legend before redrawing.
        old_legend=getattr(self,"_figure_legend",None)
        if old_legend is not None:
            old_legend.remove()
            self._figure_legend=None
        self.ax.clear()
        self._profile_ax.clear()
        self._profile_ax.set_visible(self.volume_profile_enabled.get())
        # Подписи справа для горизонтальных уровней и зон. Сначала собираем их в очередь
        # затем раздвигаем по вертикали, чтобы уменьшить наложения.
        self._right_price_tags=[]
        def add_price_tag(price, label, color):
            try:
                price=float(price)
                if pd.notna(price):
                    self._right_price_tags.append((price, str(label), str(color)))
            except (TypeError, ValueError):
                pass
        width=.62
        # Batch candle rendering into collections instead of hundreds of individual artists.
        from matplotlib.collections import LineCollection, PolyCollection
        import numpy as np
        opens=df["open"].to_numpy(dtype=float); highs=df["high"].to_numpy(dtype=float)
        lows=df["low"].to_numpy(dtype=float); closes=df["close"].to_numpy(dtype=float)
        xs=np.arange(len(df),dtype=float); up=closes>=opens
        candle_colors=np.where(up,"#159d68","#d94b4b")
        wick_segments=[[(x,lo),(x,hi)] for x,lo,hi in zip(xs,lows,highs)]
        self.ax.add_collection(LineCollection(wick_segments,colors=candle_colors,linewidths=.65,zorder=3))
        bottoms=np.minimum(opens,closes)
        heights=np.maximum(np.abs(closes-opens),np.maximum(np.abs(closes)*.00003,1e-12))
        tops=bottoms+heights
        candle_verts=[[(x-width/2,b),(x-width/2,t),(x+width/2,t),(x+width/2,b)]
                      for x,b,t in zip(xs,bottoms,tops)]
        self.ax.add_collection(PolyCollection(candle_verts,facecolors=candle_colors,edgecolors=candle_colors,linewidths=.45,zorder=4))
        # Единая функция рисует уровень, центральную подпись и ценовую метку справа.
        def draw_key_level(price, name, color, style=(0, (6, 3)), linewidth=1.65, right_tag=True):
            try:
                price=float(price)
                if not pd.notna(price):
                    return
            except (TypeError, ValueError):
                return
            self.ax.axhline(price,color=color,linestyle=style,linewidth=linewidth,alpha=.95,zorder=2)
            self.ax.text(.5,price,name,transform=self.ax.get_yaxis_transform(),ha="center",va="center",
                         fontsize=7.5,fontweight="bold",color=color,zorder=12,clip_on=True,
                         bbox=dict(boxstyle="round,pad=0.18",facecolor="white",edgecolor=color,linewidth=.8,alpha=.9))
            if right_tag:
                add_price_tag(price,name,color)

        # Daily and weekly levels are calculated from full history, not the
        # 300-candle viewport. Incomplete UTC windows are intentionally omitted.
        if self.levels.get():
            for key,name,color,style in [
                ("PDH","PDH · МАКС. ПРЕДЫДУЩЕГО ДНЯ","#d97706",(0,(8,3))),
                ("PDL","PDL · МИН. ПРЕДЫДУЩЕГО ДНЯ","#2563eb",(0,(3,2,1,2)))]:
                if key in reference_levels:
                    draw_key_level(reference_levels[key],name,color,style,1.9,right_tag=False)

        if self.weekly_levels.get():
            for key,name,color,style,width in [
                ("PWH","PWH · МАКС. ПРЕДЫДУЩЕЙ НЕДЕЛИ","#7c3aed",(0,(10,3)),1.8),
                ("PWL","PWL · МИН. ПРЕДЫДУЩЕЙ НЕДЕЛИ","#0891b2",(0,(2,2)),1.8),
                ("PWC","PWC · ЗАКРЫТИЕ ПРЕДЫДУЩЕЙ НЕДЕЛИ","#64748b","-",1.35)]:
                if key in reference_levels:
                    draw_key_level(reference_levels[key],name,color,style,width)

        ts_all=pd.to_datetime(history_df["timestamp"],utc=True,errors="coerce")

        # Экстремумы и уровни по повторным касаниям. Для защиты от шума проверяем локальные окна.
        if self.swing_levels.get() and len(df)>=7:
            h=highs; l=lows; n=len(df)
            swing_hi=[]; swing_lo=[]
            for i in range(2,n-2):
                if h[i]>=max(h[i-2:i]) and h[i]>max(h[i+1:i+3]): swing_hi.append((i,float(h[i])))
                if l[i]<=min(l[i-2:i]) and l[i]<min(l[i+1:i+3]): swing_lo.append((i,float(l[i])))
            if self.swing_levels.get():
                for idx,price in (swing_hi[-3:]+swing_lo[-3:]):
                    is_high=any(i==idx for i,_ in swing_hi)
                    draw_key_level(price,"Swing High · ЛОКАЛЬНЫЙ МАКСИМУМ" if is_high else "Swing Low · ЛОКАЛЬНЫЙ МИНИМУМ",
                                   "#ea580c" if is_high else "#0f766e",(0,(1,2)),1.15)

        # Максимумы и минимумы каждой торговой сессии группируются по UTC-дате.
        # В подписи указываем дату, чтобы было понятно, к какому дню относится уровень.
        if self.session_levels.get() and ts_all.notna().any():
            work=history_df.loc[ts_all.notna()].copy()
            work["_ts_utc"]=pd.to_datetime(work["timestamp"],utc=True,errors="coerce")
            work["_day_utc"]=work["_ts_utc"].dt.strftime("%d.%m.%Y")
            work["_hour_utc"]=work["_ts_utc"].dt.hour
            # Calculate complete session extremes from history, but only draw
            # sessions belonging to UTC dates represented in the visible chart.
            visible_days=set(pd.to_datetime(df["timestamp"],utc=True,errors="coerce").dt.strftime("%d.%m.%Y").dropna())
            sessions=[("Азия",0,8,"#9333ea"),("Лондон",8,16,"#0284c7"),("Нью-Йорк",13,22,"#ca8a04")]
            for day_label, day_part in work.groupby("_day_utc",sort=True):
                if day_label not in visible_days:
                    continue
                for session_name,start_hour,end_hour,color in sessions:
                    part=day_part[(day_part["_hour_utc"]>=start_hour)&(day_part["_hour_utc"]<end_hour)]
                    if not part.empty:
                        draw_key_level(part.high.max(),f"{session_name} · HIGH · {day_label}",color,(0,(5,2)),1.25,right_tag=False)
                        draw_key_level(part.low.min(),f"{session_name} · LOW · {day_label}",color,(0,(2,2)),1.25,right_tag=False)

        # High/Low текущего дня оставлены отдельным переключателем.
        if self.today_hilo.get():
            if "Today High" in reference_levels:
                draw_key_level(reference_levels["Today High"],"HIGH · МАКСИМУМ ТЕКУЩЕГО ДНЯ","#c026d3",(0,(7,2,1,2)),1.7,right_tag=False)
            if "Today Low" in reference_levels:
                draw_key_level(reference_levels["Today Low"],"LOW · МИНИМУМ ТЕКУЩЕГО ДНЯ","#0891b2",(0,(2,2)),1.7,right_tag=False)

        # FVG: current timeframe plus optional overlays from all downloaded timeframes.
        # Higher-timeframe zones are projected onto the current chart using their timestamps.
        if self.fvg.get():
            zone_sets=[]
            if not ev.empty:
                zone_sets.append((self.loaded_interval or self.interval.get(), ev[ev.type.astype(str).str.contains("FVG")].copy()))
            if self.all_tf_fvg.get():
                for tf, tf_events in self.mtf_events.items():
                    if tf_events is not None and not tf_events.empty:
                        zone_sets.append((tf,tf_events[tf_events.type.astype(str).str.contains("FVG")].copy()))
            tf_colors={"1m":"#7b61a8","3m":"#b07aa1","5m":"#159d68","15m":"#2a9d8f","30m":"#e9c46a","1h":"#f4a261","2h":"#e76f51","4h":"#d1495b","1d":"#6c757d","CSV":"#159d68"}
            drawn=set()
            for tf, zone_events in zone_sets:
                # Keep only the most recent zones per timeframe to avoid visual and CPU overload.
                zone_events=zone_events.tail(120)
                for _,e in zone_events.iterrows():
                    t=e.time
                    x=chart_x_for_time(t)
                    if x is None: continue
                    # Prevent duplicate drawing when main timeframe is also in MTF cache.
                    ident=(str(tf),str(t),float(e.zone_low),float(e.zone_high),str(e.direction))
                    if ident in drawn: continue
                    drawn.add(ident)
                    fill_time=None
                    fill_index=e.get("fill_index",None)
                    source_df=self.mtf_data.get(tf,self.df if tf==(self.loaded_interval or self.interval.get()) else None)
                    if source_df is not None and pd.notna(fill_index) and int(fill_index)<len(source_df):
                        fill_time=source_df.iloc[int(fill_index)].timestamp
                    x_end=len(df)-.5
                    fill_x=chart_x_for_time(fill_time) if fill_time is not None else None
                    if fill_x is not None: x_end=fill_x
                    elif fill_time is not None and fill_time < df.timestamp.iloc[-1]: x_end=x
                    lo,hi=float(e.zone_low),float(e.zone_high)
                    bullish=str(e.direction)=="LONG"
                    # Directional colors keep bullish and bearish FVG visually distinct.
                    base="#16a34a" if bullish else "#dc2626"
                    filled=bool(e.get("filled",False))
                    alpha=.08 if filled else (.18 if tf!=(self.loaded_interval or self.interval.get()) else .28)
                    self.ax.add_patch(Rectangle((x-.45,lo),max(.15,x_end-x+.45),max(hi-lo,1e-12),
                        facecolor=base,edgecolor=base,linewidth=.75 if filled else 1.15,alpha=alpha,zorder=1))
                    self.ax.hlines([lo,hi],x-.45,max(x+.1,x_end),colors=base,linewidth=.7 if filled else 1.0,alpha=.65 if filled else .95,zorder=2)
                    add_price_tag(hi, f"FVG-{tf} верх", base)
                    add_price_tag(lo, f"FVG-{tf} низ", base)
            # FVG timeframe colors are included in the unified legend below.

        # Order blocks: last opposing candle before a structural displacement.
        if self.order_blocks_enabled.get() and hasattr(self, "order_blocks") and not self.order_blocks.empty:
            visible_start = df.timestamp.iloc[0]
            obs = self.order_blocks[self.order_blocks.time >= visible_start].tail(60)
            for _, ob in obs.iterrows():
                x = chart_x_for_time(ob.time)
                if x is None:
                    continue
                bullish_ob = str(ob.direction) == "LONG"
                color = "#16a34a" if bullish_ob else "#dc2626"
                lo, hi = float(ob.zone_low), float(ob.zone_high)
                self.ax.add_patch(Rectangle((x-.45, lo), max(.15, len(df)-x-.05), max(hi-lo, 1e-12),
                    facecolor=color, edgecolor=color, linewidth=1.0, alpha=.16, linestyle="-", zorder=1.5))
                self.ax.hlines([lo, hi], x-.45, len(df)-.5, colors=color, linewidth=.9, alpha=.9, zorder=2)
                add_price_tag(hi, "OB верх", color)
                add_price_tag(lo, "OB низ", color)

        # Live price line, kept independent from the historical candle close.
        self._price_line_artist = None
        self._price_line_label = None
        if self.current_price_line.get() and self._last_live_price is not None:
            live=float(self._last_live_price)
            self._price_line_artist=self.ax.axhline(live,color="#f4d03f",linewidth=1.15,linestyle=(0,(4,2)),zorder=9)
            # Keep the live price badge inside the plotting area, at its right edge.
            self._price_line_label=self.ax.text(.992,live,f"Цена {live:.8g}",transform=self.ax.get_yaxis_transform(),
                ha="right",va="center",fontsize=8,color="#202020",clip_on=True,
                bbox=dict(boxstyle="round,pad=0.22",facecolor="#f4d03f",edgecolor="#b8860b",alpha=.98),zorder=16)

        # HH/HL/LH/LL structure from confirmed swing pivots, with confirmation delay to avoid repainting.
        if self.hhll_enabled.get() and len(df)>=13:
            structure = self.indicators.find_market_structure(df, pivot_window=5, max_pivots=24)
            for _, pivot in structure.iterrows():
                i, price, tag = int(pivot["index"]), float(pivot["price"]), str(pivot["label"])
                if tag in ("HH", "H"):
                    color="#159d68"; marker="v"; offset=(0,7)
                elif tag=="LH":
                    color="#d97736"; marker="v"; offset=(0,7)
                elif tag=="LL":
                    color="#d94b4b"; marker="^"; offset=(0,-12)
                else:
                    color="#2878b5"; marker="^"; offset=(0,-12)
                self.ax.scatter([i],[price],marker=marker,s=28,color=color,zorder=8)
                self.ax.annotate(tag,(i,price),xytext=offset,textcoords="offset points",ha="center",fontsize=8,color=color,fontweight="bold",zorder=9)

        # Volume profile is drawn in its own right-hand panel, never over candles.
        # Approximation: each candle's volume is assigned to its typical price.
        if self.volume_profile_enabled.get() and len(df)>5:
            import numpy as np
            typical=(df.high.to_numpy(dtype=float)+df.low.to_numpy(dtype=float)+df.close.to_numpy(dtype=float))/3.0
            volumes=df.volume.to_numpy(dtype=float)
            lo=float(np.nanmin(df.low)); hi=float(np.nanmax(df.high))
            if hi>lo and np.isfinite(volumes).any():
                bins=min(36,max(12,int(len(df)**0.5)))
                hist,edges=np.histogram(typical,bins=bins,range=(lo,hi),weights=volumes)
                centers=(edges[:-1]+edges[1:])/2; heights=np.diff(edges)
                self._profile_ax.barh(centers,hist,height=heights*.88,color="#7b8da8",alpha=.82,edgecolor="#53657d",linewidth=.25)
                self._profile_ax.set_xlim(0,max(float(hist.max()),1)*1.08)
                self._profile_ax.tick_params(axis="y",left=False,labelleft=False)
                self._profile_ax.tick_params(axis="x",labelsize=7)
                self._profile_ax.set_facecolor("#f3f6fa")
                self._profile_ax.set_title("Профиль объёма",fontsize=9,pad=7)
                poc=float(centers[int(np.argmax(hist))])
                self._profile_ax.axhline(poc,color="#b45309",linewidth=1.5,linestyle="--")
                self._profile_ax.grid(axis="x",alpha=.15)
        else:
            self._profile_ax.set_visible(False)

        # Liquidity sweep: show the breached local level and mark the actual wick candle.
        if self.sweeps.get() and not ev.empty:
            for _,e in ev.iterrows():
                if "Снятие" not in str(e.type): continue
                t=e.time
                if t not in time_to_x: continue
                x=time_to_x[t]; bullish=str(e.direction)=="LONG"
                color="#159d68" if bullish else "#d94b4b"
                level=e.get("level",None)
                if pd.notna(level):
                    self.ax.hlines(float(level),max(-.5,x-6),min(len(df)-.5,x+10),
                        colors=color,linestyles=(0,(3,2)),linewidth=1.0,alpha=.9,zorder=2)
                    add_price_tag(float(level), "SWEEP", color)
                self.ax.scatter([x],[float(e.price)],s=62,marker="^" if bullish else "v",
                    color=color,edgecolors="white",linewidths=.45,zorder=7)

        # Render price labels at the right edge of the main chart. Labels close
        # in price are nudged apart; their text retains the exact level value.
        if self._right_price_tags:
            tags=sorted(self._right_price_tags, key=lambda item: item[0])
            ymin=float(df.low.min()); ymax=float(df.high.max())
            span=max(ymax-ymin, abs(ymax)*1e-6, 1e-12)
            min_gap=span*0.026
            placed=[]
            for price,label,color in tags:
                y=price
                if placed and y-placed[-1][0] < min_gap:
                    y=placed[-1][0]+min_gap
                placed.append((y,price,label,color))
            # If labels spill above the chart, shift the full stack down together.
            overflow=placed[-1][0]-(ymax+span*.03) if placed else 0
            if overflow>0:
                placed=[(y-overflow,price,label,color) for y,price,label,color in placed]
            for y,price,label,color in placed:
                self.ax.text(.995,y,f"{label} {price:.6g}",transform=self.ax.get_yaxis_transform(),
                    ha="right",va="center",fontsize=7,color="white",clip_on=True,zorder=15,
                    bbox=dict(boxstyle="round,pad=0.18",facecolor=color,edgecolor=color,alpha=.94))

        import numpy as np
        ticks=sorted(set(round(x) for x in np.linspace(0,len(df)-1,min(8,len(df)))))
        self.ax.set_xticks(ticks); self.ax.set_xticklabels([df.timestamp.iloc[x].strftime("%d.%m %H:%M") for x in ticks],rotation=25,ha="right")
        display_symbol=self.loaded_symbol or self.symbol.get().upper()
        display_interval=self.loaded_interval or self.interval.get()
        self.ax.set_title(f"{display_symbol} | {display_interval} | Свечи в реальном времени" if self.live_candles.get() and display_interval != "CSV" else f"{display_symbol} | {display_interval} | Исторический анализ")
        self.ax.set_xlabel("Время (UTC)"); self.ax.set_ylabel("Цена"); self.ax.grid(True,alpha=.2)
        # One unified legend explains all enabled overlays. Creating it once avoids
        # Matplotlib replacing the timeframe legend with a later artist legend.
        from matplotlib.lines import Line2D
        legend_handles=[]
        if self.levels.get():
            legend_handles.extend([
                Line2D([0],[0],color="#e39b25",lw=1.8,ls=(0,(8,3)),label="PDH — максимум предыдущего дня"),
                Line2D([0],[0],color="#3687d8",lw=1.8,ls=(0,(3,2,1,2)),label="PDL — минимум предыдущего дня")])
        if self.weekly_levels.get():
            legend_handles.extend([
                Line2D([0],[0],color="#7c3aed",lw=1.8,ls=(0,(10,3)),label="PWH — максимум предыдущей недели"),
                Line2D([0],[0],color="#0891b2",lw=1.8,ls=(0,(2,2)),label="PWL — минимум предыдущей недели"),
                Line2D([0],[0],color="#64748b",lw=1.35,ls="-",label="PWC — закрытие предыдущей недели")])
        if self.today_hilo.get():
            legend_handles.extend([
                Line2D([0],[0],color="#c026d3",lw=1.15,ls="-.",label="High — максимум текущего дня (UTC)"),
                Line2D([0],[0],color="#0891b2",lw=1.15,ls="-.",label="Low — минимум текущего дня (UTC)")])
        if self.session_levels.get():
            legend_handles.append(Line2D([0],[0],color="#0284c7",lw=1.25,ls="--",label="Экстремумы торговых сессий (UTC)"))
        if self.current_price_line.get() and self._last_live_price is not None:
            legend_handles.append(Line2D([0],[0],color="#f4d03f",lw=1.5,ls="--",label="Текущая цена (live)"))
        if self.fvg.get():
            legend_handles.extend([
                Rectangle((0,0),1,1,facecolor="#16a34a",edgecolor="#15803d",alpha=.45,label="Bullish FVG — бычья зона"),
                Rectangle((0,0),1,1,facecolor="#dc2626",edgecolor="#b91c1c",alpha=.45,label="Bearish FVG — медвежья зона")])
            if self.all_tf_fvg.get():
                for tf,color in {"1m":"#7b61a8","3m":"#b07aa1","5m":"#159d68","15m":"#2a9d8f","30m":"#e9c46a","1h":"#f4a261","2h":"#e76f51","4h":"#d1495b","1d":"#6c757d"}.items():
                    if tf in self.mtf_events:
                        legend_handles.append(Line2D([0],[0],color=color,lw=2,label=f"FVG {tf}"))
        if self.sweeps.get():
            legend_handles.extend([
                Line2D([0],[0],color="#159d68",lw=1,ls="--",marker="^",label="Снятие минимума / возврат вверх"),
                Line2D([0],[0],color="#d94b4b",lw=1,ls="--",marker="v",label="Снятие максимума / возврат вниз")])
        if self.hhll_enabled.get():
            legend_handles.extend([
                Line2D([0],[0],color="#159d68",marker="v",lw=0, label="HH — более высокий максимум"),
                Line2D([0],[0],color="#d97736",marker="v",lw=0, label="LH — более низкий максимум"),
                Line2D([0],[0],color="#2878b5",marker="^",lw=0, label="HL — более высокий минимум"),
                Line2D([0],[0],color="#d94b4b",marker="^",lw=0, label="LL — более низкий минимум")])
        if self.volume_profile_enabled.get():
            legend_handles.append(Line2D([0],[0],color="#b45309",lw=1.1,ls="--",label="POC — максимум объёма по цене"))
        if self.order_blocks_enabled.get():
            legend_handles.extend([
                Rectangle((0,0),1,1,facecolor="#16a34a",edgecolor="#16a34a",alpha=.35,label="Bullish OB — бычий ордер-блок"),
                Rectangle((0,0),1,1,facecolor="#dc2626",edgecolor="#dc2626",alpha=.35,label="Bearish OB — медвежий ордер-блок")])
        if legend_handles:
            # Keep the legend in a dedicated strip below the chart instead of covering candles.
            self._figure_legend=self.fig.legend(handles=legend_handles,loc="lower center",bbox_to_anchor=(0.5,0.015),
                            fontsize=7,ncol=4,framealpha=0.96,borderpad=.55,
                            labelspacing=.45,handlelength=2.0,columnspacing=1.1)
        self.fig.subplots_adjust(bottom=0.24 if legend_handles else 0.10,top=0.92,left=0.06,right=0.98)
        self._profile_ax.set_ylim(self.ax.get_ylim())
        if preserve_view and old_xlim and old_ylim:
            self.ax.set_xlim(old_xlim)
            self.ax.set_ylim(old_ylim)
        self.canvas.draw_idle(); self.fill_table(ev)
        # Keep the chart's timeframe truthful if the selector was changed after loading.
        if self.loaded_interval and self.loaded_interval != self.interval.get():
            # Время берём из текущих свечей: локальная переменная из set_data здесь недоступна.
            last_time = pd.to_datetime(self.df.timestamp.iloc[-1], utc=True).strftime("%Y-%m-%d %H:%M UTC")
            self.status.set(f"На графике {self.loaded_symbol} {self.loaded_interval}, последняя свеча {last_time}. В списке выбран {self.interval.get()}; нажми «Загрузить данные», чтобы сменить таймфрейм.")

    def fill_table(self,ev):
        for item in self.table.get_children():self.table.delete(item)
        if ev.empty:
            self.table.insert("","end",values=("-","Событий нет","-","-","Попробуй увеличить историю или выбрать другой таймфрейм."));return
        for _,e in ev.tail(200).iloc[::-1].iterrows():
            self.table.insert("","end",values=(pd.to_datetime(e.time,utc=True).strftime("%Y-%m-%d %H:%M"),e.type,e.direction,f"{float(e.price):.6g}",e.get("details","")))

def main():
    root=tk.Tk(); App(root); root.mainloop()
if __name__=="__main__":main()
