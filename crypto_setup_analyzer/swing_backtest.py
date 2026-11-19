"""Бэктест модели HH ↔ LL без использования будущих данных при входе."""
from __future__ import annotations
import math
import pandas as pd


def _validate_backtest_candles(candles: pd.DataFrame) -> pd.DataFrame:
    """Validate OHLC and strict chronological order before any swing calculations."""
    if not isinstance(candles, pd.DataFrame):
        raise TypeError("candles должен быть pandas.DataFrame")
    required = {"timestamp", "open", "high", "low", "close"}
    missing = required - set(candles.columns)
    if missing:
        raise ValueError("Не хватает столбцов: " + ", ".join(sorted(missing)))
    df = candles.reset_index(drop=True).copy()
    df["timestamp"] = pd.to_datetime(df["timestamp"], utc=True, errors="coerce")
    if df["timestamp"].isna().any():
        raise ValueError("Временные метки содержат пустые или некорректные значения")
    if not df["timestamp"].is_monotonic_increasing or df["timestamp"].duplicated().any():
        raise ValueError("Свечи должны идти строго по времени без повторов")
    for column in ("open", "high", "low", "close"):
        df[column] = pd.to_numeric(df[column], errors="coerce")
    if df[["open", "high", "low", "close"]].isna().any().any():
        raise ValueError("OHLC содержит пустые или нечисловые значения")
    values = df[["open", "high", "low", "close"]]
    if not all(math.isfinite(float(value)) for value in values.to_numpy().ravel()):
        raise ValueError("OHLC содержит бесконечные или нечисловые значения")
    if (values <= 0).any().any():
        raise ValueError("Цены OHLC должны быть положительными")
    if (df["high"] < df[["open", "close", "low"]].max(axis=1)).any():
        raise ValueError("Некорректный максимум свечи")
    if (df["low"] > df[["open", "close", "high"]].min(axis=1)).any():
        raise ValueError("Некорректный минимум свечи")
    return df

def confirmed_structure(candles: pd.DataFrame, pivot_window: int = 5) -> pd.DataFrame:
    """Размечает свинги и указывает индекс свечи, на которой экстремум подтверждён."""
    if isinstance(pivot_window, bool) or not isinstance(pivot_window, int) or pivot_window < 1:
        raise ValueError("pivot_window должен быть целым числом не меньше 1")
    df = _validate_backtest_candles(candles)
    if len(df) < pivot_window * 2 + 1:
        return pd.DataFrame(columns=["pivot_index", "confirmed_index", "time", "price", "kind", "label"])

    highs = df.high.astype(float).to_numpy()
    lows = df.low.astype(float).to_numpy()
    pivots = []
    # Экстремум становится известен только после закрытия pivot_window свечей справа.
    for i in range(pivot_window, len(df) - pivot_window):
        is_high_pivot = (
            highs[i] >= highs[i-pivot_window:i].max()
            and highs[i] > highs[i+1:i+pivot_window+1].max()
        )
        is_low_pivot = (
            lows[i] <= lows[i-pivot_window:i].min()
            and lows[i] < lows[i+1:i+pivot_window+1].min()
        )
        # A single outside bar cannot define both sides of structure without
        # an intrabar sequence. Exclude the ambiguous pivot instead of letting
        # DataFrame sort order manufacture two opposite executions.
        if is_high_pivot and is_low_pivot:
            continue
        if is_high_pivot:
            pivots.append({"pivot_index": i, "confirmed_index": i + pivot_window,
                           "time": df.timestamp.iloc[i], "price": float(highs[i]), "kind": "H"})
        elif is_low_pivot:
            pivots.append({"pivot_index": i, "confirmed_index": i + pivot_window,
                           "time": df.timestamp.iloc[i], "price": float(lows[i]), "kind": "L"})
    pivots.sort(key=lambda p: (p["pivot_index"], 0 if p["kind"] == "H" else 1))

    previous_high = previous_low = None
    labelled = []
    for p in pivots:
        label = None
        if p["kind"] == "H":
            if previous_high is not None:
                label = "HH" if p["price"] > previous_high else "LH" if p["price"] < previous_high else None
            previous_high = p["price"]
        else:
            if previous_low is not None:
                label = "HL" if p["price"] > previous_low else "LL" if p["price"] < previous_low else None
            previous_low = p["price"]
        if label:
            labelled.append({**p, "label": label})
    return pd.DataFrame(labelled, columns=["pivot_index", "confirmed_index", "time", "price", "kind", "label"])


def backtest_hh_ll(candles: pd.DataFrame, pivot_window: int = 5,
                   fee_pct: float = 0.1, slippage_pct: float = 0.02) -> tuple[pd.DataFrame, dict, pd.DataFrame]:
    """Переворот: HH -> SHORT, LL -> LONG; HL/LH игнорируются.

    Сигнал, подтверждённый закрытием свечи, исполняется по open следующей свечи.
    До первого HH/LL позиция отсутствует. Последняя открытая позиция закрывается
    по close последней свечи. Комиссия и проскальзывание применяются на входе и выходе.
    Проценты задаются в обычных единицах: 0.1 означает 0.1%.
    """
    df = _validate_backtest_candles(candles)
    if len(df) < 3:
        raise ValueError("Для теста нужно минимум 3 свечи")
    try:
        fee_pct = float(fee_pct)
        slippage_pct = float(slippage_pct)
    except (TypeError, ValueError, OverflowError) as exc:
        raise ValueError("Комиссия и проскальзывание должны быть числами") from exc
    if (not math.isfinite(fee_pct) or not math.isfinite(slippage_pct)
            or fee_pct < 0 or slippage_pct < 0 or fee_pct >= 100 or slippage_pct >= 100):
        raise ValueError("Комиссия и проскальзывание должны быть конечными значениями от 0 до 100%")
    structure = confirmed_structure(df, pivot_window)
    signals = structure[structure.label.isin(["HH", "LL"])].sort_values(["confirmed_index", "pivot_index"])
    fee = fee_pct / 100
    slip = slippage_pct / 100
    position = 0  # +1 long, -1 short
    entry_price = None
    entry_index = None
    entry_label = None
    equity = 1.0
    trades = []
    equity_curve = []

    for _, sig in signals.iterrows():
        exec_i = int(sig.confirmed_index) + 1
        if exec_i >= len(df):
            continue
        target = -1 if sig.label == "HH" else 1
        if target == position:
            continue
        raw_price = float(df.iloc[exec_i].open)
        # Учитываем неблагоприятное проскальзывание на исполнении.
        exec_price = raw_price * (1 + slip if target == 1 else 1 - slip)
        if position != 0 and entry_price is not None:
            raw_ret = (exec_price / entry_price - 1) * position
            net_ret = (1 + raw_ret) * (1-fee) * (1-fee) - 1
            equity *= (1 + net_ret)
            trades.append({"Вход UTC": df.iloc[entry_index].timestamp, "Выход UTC": df.iloc[exec_i].timestamp,
                "Направление": "LONG" if position == 1 else "SHORT", "Сигнал выхода": sig.label,
                "Цена входа": entry_price, "Цена выхода": exec_price,
                "Свечей в сделке": exec_i-entry_index, "До издержек %": raw_ret*100,
                "Результат %": net_ret*100, "Капитал после сделки %": (equity-1)*100})
        position = target
        entry_price = exec_price
        entry_index = exec_i
        entry_label = sig.label
        equity_curve.append({"timestamp": df.iloc[exec_i].timestamp, "equity": equity, "signal": entry_label})

    # Закрытие позиции на последней доступной цене, без использования будущего.
    if position and entry_price is not None and entry_index < len(df)-1:
        last_i = len(df)-1
        raw_price = float(df.iloc[last_i].close)
        exit_price = raw_price * (1-slip if position == 1 else 1+slip)
        raw_ret = (exit_price / entry_price - 1) * position
        net_ret = (1 + raw_ret) * (1-fee) * (1-fee) - 1
        equity *= (1 + net_ret)
        trades.append({"Вход UTC": df.iloc[entry_index].timestamp, "Выход UTC": df.iloc[last_i].timestamp,
            "Направление": "LONG" if position == 1 else "SHORT", "Сигнал выхода": "Конец истории",
            "Цена входа": entry_price, "Цена выхода": exit_price,
            "Свечей в сделке": last_i-entry_index, "До издержек %": raw_ret*100,
            "Результат %": net_ret*100, "Капитал после сделки %": (equity-1)*100})

    tdf = pd.DataFrame(trades)
    if len(tdf):
        returns = tdf["Результат %"].astype(float)
        wins = returns[returns > 0]
        losses = returns[returns <= 0]
        summary = {
            "Свечей": len(df), "Экстремумов HH/LL (сигналов)": len(signals), "Сделок закрыто": len(tdf),
            "Прибыльных сделок %": round(float((returns > 0).mean()*100), 2),
            "Суммарный результат %": round((equity-1)*100, 3),
            "Средний результат сделки %": round(float(returns.mean()), 4),
            "Средняя прибыль %": round(float(wins.mean()), 4) if len(wins) else 0.0,
            "Средний убыток %": round(float(losses.mean()), 4) if len(losses) else 0.0,
            "Макс. просадка капитала %": _max_drawdown(tdf["Капитал после сделки %"].astype(float).to_list()),
            "Комиссия на сторону %": fee_pct, "Проскальзывание на сторону %": slippage_pct,
            "Окно подтверждения свечей": pivot_window,
        }
    else:
        summary = {"Свечей": len(df), "Экстремумов HH/LL (сигналов)": len(signals), "Сделок закрыто": 0,
                   "Суммарный результат %": 0.0, "Примечание": "На выбранном отрезке не сформировалось закрытых сделок."}
    return tdf, summary, structure


def _max_drawdown(cumulative_returns_pct: list[float]) -> float:
    """Просадка по последовательности закрытых сделок, в процентах."""
    values = [1.0] + [1.0 + x/100 for x in cumulative_returns_pct]
    peak = values[0]
    worst = 0.0
    for value in values:
        peak = max(peak, value)
        if peak > 0:
            worst = min(worst, (value/peak-1)*100)
    return round(worst, 3)
