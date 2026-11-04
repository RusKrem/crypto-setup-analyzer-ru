"""Фирменные графические карточки Reversal Lab для Telegram."""
from __future__ import annotations

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import Rectangle, FancyBboxPatch, Circle
from matplotlib.lines import Line2D
from matplotlib.offsetbox import OffsetImage, AnnotationBbox
from matplotlib.image import imread
from pathlib import Path
from datetime import datetime, timezone

BG = "#050d16"
PANEL = "#0b1926"
PANEL2 = "#101f2d"
BORDER = "#243c50"
TEXT = "#f3f7fc"
MUTED = "#a9bfd2"
GREEN = "#29df91"
RED = "#ff5364"
GOLD = "#f3bd55"
BLUE = "#39bdf7"


def _panel(ax, xy, width, height, radius=.012, face=PANEL, edge=BORDER, lw=.8):
    patch = FancyBboxPatch(xy, width, height,
        boxstyle=f"round,pad=0.008,rounding_size={radius}",
        transform=ax.transAxes, facecolor=face, edgecolor=edge,
        linewidth=lw, zorder=0)
    ax.add_patch(patch)
    return patch


def _fmt_price(value):
    return f"{float(value):.10g}"


def _direction(signal):
    return signal.get("direction") or (
        "LONG" if signal.get("level_name") in ("PDL", "PWL", "Today Low") else "SHORT")


def _draw_brand(ax, project_root: Path):
    """Показывает оригинальную эмблему Reversal Lab без чёрной квадратной подложки."""
    logo_path = project_root / "assets" / "reversal_lab_logo_transparent.png"
    if not logo_path.is_file():
        logo_path = project_root / "assets" / "reversal_lab_logo.png"
    if logo_path.is_file():
        try:
            logo = imread(logo_path)
            image = OffsetImage(logo, zoom=.105)
            ab = AnnotationBbox(image, (.072, .944), xycoords=ax.transAxes,
                                frameon=False, box_alignment=(.5, .5), zorder=20,
                                pad=0)
            ax.add_artist(ab)
        except Exception:
            pass
    ax.text(.125, .955, "REVERSAL", transform=ax.transAxes, color=TEXT,
            fontsize=16.5, weight="bold", va="center", ha="left")
    ax.text(.252, .955, "LAB", transform=ax.transAxes, color=GREEN,
            fontsize=16.5, weight="bold", va="center", ha="left")
    ax.text(.126, .925, "SIGNALS  ·  CRYPTO SETUP ANALYZER RU", transform=ax.transAxes,
            color=MUTED, fontsize=7.6, va="center", ha="left", alpha=.95)


def _candle_time(candle):
    try:
        return datetime.fromtimestamp(float(candle[0]) / 1000, tz=timezone.utc).strftime("%H:%M")
    except Exception:
        return ""


def _validate_binance_candles(candles):
    """Проверяет реальные OHLC-массивы Binance; синтетические/пустые данные не принимаются."""
    rows = list(candles or [])
    if len(rows) < 5:
        raise ValueError("Для графической карточки нужны минимум 5 реальных свечей Binance.")
    validated = []
    previous_open_time = None
    for row in rows:
        if not isinstance(row, (list, tuple)) or len(row) < 7:
            raise ValueError("Некорректный формат свечи Binance.")
        open_time = int(row[0])
        o, h, low, close = map(float, (row[1], row[2], row[3], row[4]))
        if min(o, h, low, close) <= 0 or h < max(o, close, low) or low > min(o, close, h):
            raise ValueError("Некорректные OHLC-значения свечи Binance.")
        if previous_open_time is not None and open_time <= previous_open_time:
            raise ValueError("Свечи Binance должны идти в хронологическом порядке без повторов.")
        previous_open_time = open_time
        validated.append(row)
    return validated


def _draw_chart(ax, signal, candles, kind):
    ax.set_facecolor("#081522")
    for spine in ax.spines.values():
        spine.set_color(BORDER)
        spine.set_linewidth(.8)
    ax.tick_params(colors=MUTED, labelsize=8, length=0, pad=6)
    ax.grid(True, color="#1a3042", linewidth=.55, alpha=.95)
    data = _validate_binance_candles(candles)[-64:]

    xs, highs, lows = list(range(len(data))), [], []
    for i, c in enumerate(data):
        o, h, lo, close = map(float, (c[1], c[2], c[3], c[4]))
        highs.append(h); lows.append(lo)
        color = GREEN if close >= o else RED
        ax.vlines(i, lo, h, color=color, linewidth=1.15, zorder=3)
        body_y = min(o, close)
        body_h = max(abs(close-o), max(h-lo, 1e-12)*.018)
        ax.add_patch(Rectangle((i-.30, body_y), .60, body_h,
                               facecolor=color, edgecolor=color, linewidth=.5, zorder=4))

    level = float(signal["level"])
    price = float(signal.get("price", data[-1][4]))
    ax.axhline(level, color=BLUE, linestyle=(0, (5, 3)), linewidth=1.45, zorder=2)
    ax.axhline(price, color=GREEN, linestyle=(0, (1, 2)), linewidth=1.15, alpha=.95, zorder=2)
    ax.set_xlim(-1, len(data)+2)
    ymin, ymax = min(lows+[level, price]), max(highs+[level, price])
    pad = max((ymax-ymin)*.13, abs(level)*.001, 1e-12)
    ax.set_ylim(ymin-pad, ymax+pad)
    ax.set_title(f"{signal['symbol']}  ·  1m  ·  BINANCE FUTURES USDT-M",
                 color=TEXT, fontsize=9.5, loc="left", pad=9, weight="bold")

    # Fixed legend in the top-right corner: labels never collide when prices are close.
    ax.text(.985, .965, f"{signal.get('level_name', 'Уровень')}: {_fmt_price(level)}",
            transform=ax.transAxes, color=BLUE, fontsize=7.7, weight="bold",
            ha="right", va="top", bbox=dict(boxstyle="round,pad=.28", fc="#0b2638", ec=BLUE, lw=.6))
    ax.text(.985, .885, f"Текущая цена: {_fmt_price(price)}",
            transform=ax.transAxes, color=GREEN, fontsize=7.5,
            ha="right", va="top", bbox=dict(boxstyle="round,pad=.25", fc="#0b2a22", ec=GREEN, lw=.5))

    tick_count = min(6, len(data))
    tick_idx = sorted(set(round(i*(len(data)-1)/max(1,tick_count-1)) for i in range(tick_count)))
    ax.set_xticks(tick_idx)
    ax.set_xticklabels([_candle_time(data[i]) or str(i) for i in tick_idx])

    if kind == "CONFIRMED":
        hi = float(signal.get("candle_high", data[-1][2]))
        lo = float(signal.get("candle_low", data[-1][3]))
        cl = float(signal.get("candle_close", data[-1][4]))
        idx = len(data)-1
        rejection_open_time = signal.get("candle_open_time")
        if rejection_open_time is not None:
            matches = [j for j, candle in enumerate(data) if int(candle[0]) == int(rejection_open_time)]
            if not matches:
                raise ValueError("Свеча подтверждения отсутствует в реальном наборе свечей графика.")
            idx = matches[-1]
        else:
            matches = [j for j, candle in enumerate(data)
                       if all(abs(float(candle[k])-v) <= max(abs(v)*1e-8, 1e-12)
                              for k, v in ((1, float(signal.get("candle_open", candle[1]))),
                                           (2, hi), (3, lo), (4, cl)))]
            if not matches:
                raise ValueError("Не удалось найти реальную свечу подтверждения на графике.")
            idx = matches[-1]
        # Narrow frame around the exact rejection candle, never a broad rectangle over neighbours.
        ax.add_patch(Rectangle((idx-.42, lo), .84, max(hi-lo, 1e-12),
                               facecolor="none", edgecolor=GOLD, linewidth=1.7, zorder=7))
        wick_y = hi if _direction(signal) == "SHORT" else lo
        halo = Circle((idx, wick_y), radius=max((ymax-ymin)*.025, abs(wick_y)*.0004),
                      facecolor="none", edgecolor=GOLD, linewidth=1.8, zorder=8)
        ax.add_patch(halo)
        # Short callout sits next to the rejection candle; no long arrow across the chart.
        if _direction(signal) == "SHORT":
            label_y, label_va = hi + pad*.62, "bottom"
        else:
            label_y, label_va = lo - pad*.62, "top"
        ax.annotate("СВЕЧА ОТВЕРЖЕНИЯ", xy=(idx, wick_y),
                    xytext=(max(1, idx-8), label_y),
                    color=GOLD, fontsize=7.0, weight="bold", ha="center", va=label_va,
                    arrowprops=dict(arrowstyle="->", color=GOLD, lw=1.1,
                                    connectionstyle="arc3,rad=0.12"),
                    bbox=dict(boxstyle="round,pad=.32", fc="#2a2114", ec=GOLD, lw=.8),
                    annotation_clip=True)


def render_signal_card(signal: dict, candles: list, kind: str, output_path: str) -> str:
    """Создаёт фирменную карточку Reversal Lab для приближения или подтверждения."""
    confirmed = str(kind).upper() == "CONFIRMED"
    candles = _validate_binance_candles(candles)
    direction = _direction(signal)
    accent = GREEN if confirmed else GOLD
    level = float(signal["level"])
    price = float(signal.get("price", 0))
    if confirmed:
        rejection_open_time = signal.get("candle_open_time")
        if rejection_open_time is not None:
            rejection_rows = [c for c in candles if int(c[0]) == int(rejection_open_time)]
        else:
            rejection_rows = [c for c in candles if
                abs(float(c[2])-float(signal.get("candle_high", c[2]))) <= max(abs(float(c[2]))*1e-8, 1e-12)
                and abs(float(c[3])-float(signal.get("candle_low", c[3]))) <= max(abs(float(c[3]))*1e-8, 1e-12)
                and abs(float(c[4])-float(signal.get("candle_close", c[4]))) <= max(abs(float(c[4]))*1e-8, 1e-12)]
        if not rejection_rows:
            raise ValueError("Карточка подтверждения требует реальную закрытую свечу Binance.")
        rejection = rejection_rows[-1]
        for key, idx in (("candle_open", 1), ("candle_high", 2), ("candle_low", 3), ("candle_close", 4)):
            if key in signal and abs(float(signal[key])-float(rejection[idx])) > max(abs(float(rejection[idx]))*1e-8, 1e-12):
                raise ValueError("OHLC подтверждения не совпадает с реальной свечой Binance.")
    distance = float(signal.get("distance_pct", abs(price-level)/level*100 if level else 0))
    level_name = str(signal.get("level_name", "Ключевой уровень"))
    group = str(signal.get("level_group", ""))
    symbol = str(signal.get("symbol", "UNKNOWN"))
    title = "РЕАКЦИЯ ПОДТВЕРЖДЕНА" if confirmed else "СИГНАЛ ПРИБЛИЖЕНИЯ К УРОВНЮ"
    now_ms = signal.get("time")
    try:
        stamp = datetime.fromtimestamp(float(now_ms)/1000, tz=timezone.utc).strftime("%d.%m.%Y  %H:%M:%S UTC") if now_ms else datetime.now(timezone.utc).strftime("%d.%m.%Y  %H:%M:%S UTC")
    except (ValueError, TypeError, OSError):
        stamp = datetime.now(timezone.utc).strftime("%d.%m.%Y  %H:%M:%S UTC")

    fig = plt.figure(figsize=(13.0, 9.8), facecolor=BG)
    root = fig.add_axes([0, 0, 1, 1]); root.set_axis_off()
    _panel(root, (.012, .012), .976, .976, radius=.018, face="#07131f", edge=BORDER, lw=1.0)
    _panel(root, (.025, .895), .95, .085, radius=.014, face="#0c1c2b", edge="#29445c")
    project_root = Path(__file__).resolve().parent.parent
    _draw_brand(root, project_root)

    # Header title and timeframe badge are aligned on a fixed grid.
    root.text(.43, .956, title, transform=root.transAxes, color=TEXT,
              fontsize=14.2, weight="bold", va="center", ha="left")
    root.text(.43, .921, "BINANCE FUTURES USDT-M  ·  ТОЛЬКО АЛЬТКОИНЫ",
              transform=root.transAxes, color=MUTED, fontsize=7.8, va="center", ha="left")
    _panel(root, (.84, .916), .052, .044, radius=.01, face="#0b3a2d", edge=GREEN, lw=1)
    root.text(.866, .938, "1m", transform=root.transAxes, color=TEXT,
              fontsize=13, weight="bold", ha="center", va="center")
    root.text(.902, .938, "РАБОЧИЙ\nТАЙМФРЕЙМ", transform=root.transAxes,
              color=MUTED, fontsize=6.8, va="center", ha="left")

    # Instrument row: symbol, direction and timestamp never share the same horizontal slot.
    root.text(.04, .855, symbol, transform=root.transAxes, color=TEXT,
              fontsize=23, weight="bold", va="center", ha="left")
    badge_color = "#123b32" if direction == "LONG" else "#411d29"
    direction_color = GREEN if direction == "LONG" else RED
    _panel(root, (.30, .833), .105, .043, radius=.012, face=badge_color, edge=direction_color, lw=1.0)
    root.text(.3525, .854, direction, transform=root.transAxes,
              color=direction_color, fontsize=12.5, weight="bold", ha="center", va="center")
    root.text(.96, .854, stamp, transform=root.transAxes, color=MUTED,
              fontsize=8.0, ha="right", va="center")

    if confirmed:
        reason = f"Цена отреагировала на уровень {level_name}."
        subreason = "Сформировано выраженное отвержение уровня на закрытой минутной свече."
    else:
        reason = f"Цена приближается к уровню {level_name}."
        subreason = f"Расстояние: {distance:.3f}% · Реакция ещё не подтверждена."
    root.text(.04, .798, reason, transform=root.transAxes, color=TEXT,
              fontsize=11.2, weight="bold", va="center", ha="left")
    root.text(.04, .772, subreason, transform=root.transAxes, color=MUTED,
              fontsize=8.8, va="center", ha="left")

    # Chart and its annotations occupy a dedicated panel with generous margins.
    _panel(root, (.025, .315), .95, .425, radius=.012, face="#081522", edge=BORDER)
    chart = fig.add_axes([.055, .345, .89, .345])
    _draw_chart(chart, signal, candles, "CONFIRMED" if confirmed else "APPROACH")

    # Four equally sized metric cells with restrained labels and consistent baselines.
    _panel(root, (.025, .218), .95, .078, radius=.012, face="#0c1b2a", edge=BORDER)
    metric_x = [.047, .285, .535, .775]
    metric_values = [
        ("ТЕКУЩАЯ ЦЕНА", _fmt_price(price), TEXT),
        ("УРОВЕНЬ", _fmt_price(level), TEXT),
        ("РАССТОЯНИЕ ДО УРОВНЯ", f"{distance:.3f}%", accent),
        ("НАПРАВЛЕНИЕ", direction, direction_color),
    ]
    for x, (label, value, color) in zip(metric_x, metric_values):
        root.text(x, .269, label, transform=root.transAxes, color=MUTED,
                  fontsize=7.2, va="center", ha="left")
        root.text(x, .237, value, transform=root.transAxes, color=color,
                  fontsize=13.0, weight="bold", va="center", ha="left")
    for x in (.265, .515, .755):
        root.add_line(Line2D([x, x], [.23, .283], transform=root.transAxes,
                             color=BORDER, linewidth=.8))

    # Recommendation block, with separate rows for recommendation and criteria.
    _panel(root, (.025, .085), .95, .112, radius=.012, face="#0c1c2b", edge=BORDER)
    root.text(.05, .168, "РЕКОМЕНДАЦИЯ", transform=root.transAxes,
              color=GREEN if confirmed else GOLD, fontsize=10.5, weight="bold", va="center")
    rec = (f"Рассматривайте возможный вход в {direction} после оценки риск-менеджмента."
           if confirmed else f"Наблюдайте за реакцией цены. Возможный сценарий: {direction} после подтверждения.")
    root.text(.05, .139, rec, transform=root.transAxes, color=TEXT,
              fontsize=8.6, va="center")
    if confirmed:
        ratio = float(signal.get("wick_body_ratio", 0))
        close_pos = float(signal.get("close_position", 0))
        close_text = f"Позиция закрытия: {close_pos:.0%} от минимума свечи"
        criteria = f"✓ Тень / тело: {ratio:.2f}     ✓ {close_text}     ✓ Касание / прокол уровня"
        root.text(.05, .108, criteria, transform=root.transAxes,
                  color=GREEN, fontsize=7.8, weight="bold", va="center")
    else:
        root.text(.05, .108, f"Уровень: {level_name} · {group}     ⚠ Предупреждение, не торговый вход.",
                  transform=root.transAxes, color=GOLD, fontsize=7.8, va="center")

    root.text(.04, .047,
              "⚠  " + ("Подтверждение по закрытой минутной свече не гарантирует продолжения движения."
                       if confirmed else "Приближение к уровню не подтверждает отскок. Цена может пробить уровень."),
              transform=root.transAxes, color="#d7e2ed", fontsize=7.8, va="center")
    root.text(.96, .025, "REVERSAL LAB  ·  DISCIPLINE  ·  DATA  ·  BETTER DECISIONS",
              transform=root.transAxes, color="#718ba2", fontsize=6.7, va="center", ha="right")

    Path(output_path).parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(output_path, dpi=160, facecolor=fig.get_facecolor())
    plt.close(fig)
    return output_path
