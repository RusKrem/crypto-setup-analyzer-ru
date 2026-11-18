import pandas as pd

def add_levels(candles):
    df = candles.copy()
    df["_day"] = df.timestamp.dt.floor("D")
    daily = df.groupby("_day").agg(day_high=("high", "max"), day_low=("low", "min"))
    daily["PDH"] = daily.day_high.shift(1)
    daily["PDL"] = daily.day_low.shift(1)
    return df.join(daily[["PDH", "PDL"]], on="_day").drop(columns="_day")


def calculate_reference_levels(candles):
    """Calculate UTC reference levels from the full available candle history.

    Incomplete previous-day or previous-week windows are omitted instead of
    being presented as valid levels. The current-day range is available only
    when the supplied history starts close to 00:00 UTC for that day.
    """
    required = {"timestamp", "high", "low", "close"}
    missing = sorted(required.difference(candles.columns))
    if missing:
        raise ValueError("Не хватает столбцов для расчёта уровней: " + ", ".join(missing))
    if candles.empty:
        return {}

    work = candles[["timestamp", "high", "low", "close"]].copy()
    work["_ts"] = pd.to_datetime(work["timestamp"], utc=True, errors="coerce")
    for column in ("high", "low", "close"):
        work[column] = pd.to_numeric(work[column], errors="coerce")
    work = work.dropna(subset=["_ts", "high", "low", "close"]).sort_values("_ts")
    if work.empty:
        return {}

    deltas = work["_ts"].diff().dropna().dt.total_seconds() * 1000
    deltas = deltas[deltas > 0]
    if deltas.empty:
        return {}
    interval_ms = float(deltas.median())
    if not pd.notna(interval_ms) or interval_ms <= 0:
        return {}

    latest = work["_ts"].iloc[-1]
    today_start = latest.floor("D")
    interval = pd.Timedelta(milliseconds=interval_ms)
    result = {}

    def has_no_large_gaps(window):
        gaps = window["_ts"].diff().dropna()
        return gaps.empty or bool((gaps <= interval * 1.5).all())

    today = work[work["_ts"] >= today_start]
    # Do not call a partial or internally gapped intraday download the full range.
    if (not today.empty
            and today["_ts"].iloc[0] <= today_start + interval * 1.5
            and has_no_large_gaps(today)):
        result["Today High"] = float(today["high"].max())
        result["Today Low"] = float(today["low"].min())

    def complete_window(window, start, end):
        """Accept a window only when both boundaries and most candles exist."""
        if window.empty:
            return False
        first_ts = window["_ts"].iloc[0]
        last_ts = window["_ts"].iloc[-1]
        if first_ts > start + interval * 1.5:
            return False
        if last_ts < end - interval * 1.5:
            return False
        expected = (end - start).total_seconds() * 1000 / interval_ms
        if len(window) < expected * 0.95:
            return False
        return has_no_large_gaps(window)

    previous_day_start = today_start - pd.Timedelta(days=1)
    previous_day = work[(work["_ts"] >= previous_day_start) & (work["_ts"] < today_start)]
    if complete_window(previous_day, previous_day_start, today_start):
        result["PDH"] = float(previous_day["high"].max())
        result["PDL"] = float(previous_day["low"].min())

    week_start = today_start - pd.Timedelta(days=today_start.weekday())
    previous_week_start = week_start - pd.Timedelta(days=7)
    previous_week = work[(work["_ts"] >= previous_week_start) & (work["_ts"] < week_start)]
    if complete_window(previous_week, previous_week_start, week_start):
        result["PWH"] = float(previous_week["high"].max())
        result["PWL"] = float(previous_week["low"].min())
        result["PWC"] = float(previous_week["close"].iloc[-1])

    return result


def retain_live_history_depth(combined, previous_count, minimum_rows=500):
    """Keep the user's loaded history depth while allowing a small warm-up floor."""
    keep_rows = max(int(previous_count), int(minimum_rows))
    if len(combined) <= keep_rows:
        return combined.reset_index(drop=True)
    return combined.tail(keep_rows).reset_index(drop=True)

def find_events(candles, lookback=20, min_fvg_pct=0.02):
    """Find visual FVG zones and liquidity sweeps; no trading signals/orders."""
    df = candles.reset_index(drop=True)
    events = []

    # FVG zones are tracked forward until fully filled. Filled zones remain in
    # the event list so the chart can show historical zones with reduced opacity.
    for i in range(2, len(df)):
        a, r = df.iloc[i - 2], df.iloc[i]
        zone = None
        if float(a.high) < float(r.low):
            lo, hi = float(a.high), float(r.low)
            if (hi - lo) / float(r.close) * 100 >= min_fvg_pct:
                zone = (lo, hi, "Bullish FVG", "LONG")
        elif float(a.low) > float(r.high):
            lo, hi = float(r.high), float(a.low)
            if (hi - lo) / float(r.close) * 100 >= min_fvg_pct:
                zone = (lo, hi, "Bearish FVG", "SHORT")
        if zone:
            lo, hi, kind, direction = zone
            fill_index = None
            for j in range(i + 1, len(df)):
                # Full fill means price has crossed the far edge of the gap.
                if (direction == "LONG" and float(df.iloc[j].low) <= lo) or (direction == "SHORT" and float(df.iloc[j].high) >= hi):
                    fill_index = j
                    break
            filled_text = f"Заполнена на свече {df.iloc[fill_index].timestamp:%Y-%m-%d %H:%M} UTC" if fill_index is not None else "Ещё не заполнена"
            events.append({
                "index": i, "time": r.timestamp, "type": kind, "price": (lo + hi) / 2,
                "zone_low": lo, "zone_high": hi, "direction": direction,
                "fill_index": fill_index, "filled": fill_index is not None,
                "details": f"Зона {lo:.6g}–{hi:.6g} · {filled_text}"
            })

    # Sweep events carry the exact local level that was breached, not only the wick price.
    for i in range(lookback, len(df)):
        r = df.iloc[i]
        prev = df.iloc[i - lookback:i]
        lo, hi = float(prev.low.min()), float(prev.high.max())
        if float(r.low) < lo and float(r.close) > lo:
            events.append({"index": i, "time": r.timestamp, "type": "Снятие минимума",
                "price": float(r.low), "level": lo, "direction": "LONG",
                "details": f"Прокол уровня {lo:.6g} и возврат выше"})
        if float(r.high) > hi and float(r.close) < hi:
            events.append({"index": i, "time": r.timestamp, "type": "Снятие максимума",
                "price": float(r.high), "level": hi, "direction": "SHORT",
                "details": f"Прокол уровня {hi:.6g} и возврат ниже"})

    return pd.DataFrame(events).sort_values(["time", "type"]).reset_index(drop=True) if events else pd.DataFrame()


def find_price_reactions(candles, pivot_window=5, tolerance_pct=0.12, max_levels=80):
    """Find reactions to confirmed local swing highs/lows (min/max levels).

    A reaction is counted when a later candle approaches a prior pivot level and
    closes back away from it. This is a visual detector, not a trade signal.
    """
    df=candles.reset_index(drop=True)
    if len(df) < pivot_window*2+3:
        return pd.DataFrame()
    events=[]
    highs=df.high.astype(float).tolist(); lows=df.low.astype(float).tolist()
    # Confirm pivots only after pivot_window candles on the right have completed.
    pivots=[]
    for i in range(pivot_window, len(df)-pivot_window):
        left_h=max(highs[i-pivot_window:i]); right_h=max(highs[i+1:i+pivot_window+1])
        left_l=min(lows[i-pivot_window:i]); right_l=min(lows[i+1:i+pivot_window+1])
        if highs[i] >= left_h and highs[i] > right_h:
            pivots.append((i,highs[i],"max"))
        if lows[i] <= left_l and lows[i] < right_l:
            pivots.append((i,lows[i],"min"))
    pivots=pivots[-max_levels:]
    used=set()
    for pi,level,kind in pivots:
        # Look forward for the first meaningful retest/rejection after pivot confirmation.
        start=pi+pivot_window+1
        for j in range(start,len(df)):
            r=df.iloc[j]
            tol=max(level*tolerance_pct/100, 1e-12)
            if kind=="max":
                touched=float(r.high)>=level-tol and float(r.high)<=level+tol*2
                rejected=touched and float(r.close)<level and float(r.close)<float(r.open)
                direction="SHORT"; typ="Реакция на максимум"
                price=float(r.high)
            else:
                touched=float(r.low)<=level+tol and float(r.low)>=level-tol*2
                rejected=touched and float(r.close)>level and float(r.close)>float(r.open)
                direction="LONG"; typ="Реакция на минимум"
                price=float(r.low)
            if rejected and (j,kind) not in used:
                events.append({"index":j,"time":r.timestamp,"type":typ,"direction":direction,
                    "price":price,"level":level,"details":f"Цена протестировала уровень {level:.6g} и закрылась обратно от него"})
                used.add((j,kind))
                break
    return pd.DataFrame(events).sort_values("time").reset_index(drop=True) if events else pd.DataFrame()


def find_order_blocks(candles, structure_lookback=10, search_back=6, max_blocks=80, atr_period=14, displacement_atr=0.8):
    """Detect heuristic OBs after a directional structure break with displacement.

    Bullish: a bullish close breaks the previous N-candle high and its body is
    at least displacement_atr * ATR; OB is the last bearish candle in the
    preceding search window. Bearish is the inverse. The returned zone is the
    full high/low of the candidate candle. This is a transparent heuristic,
    not a universal definition of institutional order flow.
    """
    df = candles.reset_index(drop=True).copy()
    if len(df) < max(structure_lookback + 2, atr_period + 2):
        return pd.DataFrame()
    high = df.high.astype(float); low = df.low.astype(float)
    close = df.close.astype(float); open_ = df.open.astype(float)
    prev_close = close.shift(1)
    tr = pd.concat([high-low, (high-prev_close).abs(), (low-prev_close).abs()], axis=1).max(axis=1)
    atr = tr.rolling(atr_period, min_periods=max(3, atr_period//2)).mean()
    out = []
    for i in range(max(structure_lookback, atr_period), len(df)):
        prior = df.iloc[i-structure_lookback:i]
        body = abs(float(close.iloc[i]) - float(open_.iloc[i]))
        av = float(atr.iloc[i]) if pd.notna(atr.iloc[i]) else 0.0
        if av <= 0 or body < displacement_atr * av:
            continue
        if float(close.iloc[i]) > float(open_.iloc[i]) and float(close.iloc[i]) > float(prior.high.max()):
            direction = "LONG"
        elif float(close.iloc[i]) < float(open_.iloc[i]) and float(close.iloc[i]) < float(prior.low.min()):
            direction = "SHORT"
        else:
            continue
        candidate = None
        for j in range(i-1, max(-1, i-search_back-1), -1):
            o, c = float(open_.iloc[j]), float(close.iloc[j])
            if (direction == "LONG" and c < o) or (direction == "SHORT" and c > o):
                candidate = j
                break
        if candidate is None:
            continue
        c = df.iloc[candidate]
        zlo, zhi = float(c.low), float(c.high)
        if zhi <= zlo:
            continue
        # Mark whether the zone was invalidated after its structural break.
        future = df.iloc[i+1:]
        if direction == "LONG":
            invalidated = bool((future.low.astype(float) < zlo).any())
        else:
            invalidated = bool((future.high.astype(float) > zhi).any())
        out.append({
            "index": candidate, "time": c.timestamp,
            "type": "Bullish OB" if direction == "LONG" else "Bearish OB",
            "direction": direction, "zone_low": zlo, "zone_high": zhi,
            "break_index": i, "price": (zlo+zhi)/2, "invalidated": invalidated,
            "details": f"OB {zlo:.6g}–{zhi:.6g}; пробой структуры {df.iloc[i].timestamp:%Y-%m-%d %H:%M} UTC; {'пробит' if invalidated else 'не инвалидирован'}"
        })
    if not out:
        return pd.DataFrame()
    result = pd.DataFrame(out).drop_duplicates(["break_index", "direction", "zone_low", "zone_high"])
    return result.tail(max_blocks).reset_index(drop=True)


def find_market_structure(candles, pivot_window=5, max_pivots=100):
    """Return confirmed swing pivots labelled HH/LH and HL/LL.

    A pivot is only confirmed after `pivot_window` complete candles on its
    right. Equal highs/lows are not classified as HH/LL; they are omitted as
    ambiguous structure. Classification compares consecutive confirmed swing
    highs to highs and lows to lows, separately.
    """
    df = candles.reset_index(drop=True)
    if len(df) < pivot_window*2+1:
        return pd.DataFrame(columns=["index", "price", "kind", "label", "time"])
    highs = df.high.astype(float).to_numpy(); lows = df.low.astype(float).to_numpy()
    pivots = []
    for i in range(pivot_window, len(df)-pivot_window):
        left_h = highs[i-pivot_window:i]; right_h = highs[i+1:i+pivot_window+1]
        left_l = lows[i-pivot_window:i]; right_l = lows[i+1:i+pivot_window+1]
        # Strict on the right avoids selecting multiple equal highs/lows.
        if highs[i] >= left_h.max() and highs[i] > right_h.max():
            pivots.append({"index": i, "price": float(highs[i]), "kind": "H", "time": df.timestamp.iloc[i]})
        if lows[i] <= left_l.min() and lows[i] < right_l.min():
            pivots.append({"index": i, "price": float(lows[i]), "kind": "L", "time": df.timestamp.iloc[i]})
    pivots.sort(key=lambda item: (item["index"], 0 if item["kind"] == "H" else 1))
    prev_high = prev_low = None
    labelled = []
    for pivot in pivots:
        price = pivot["price"]
        if pivot["kind"] == "H":
            if prev_high is None:
                label = "H"
            elif price > prev_high:
                label = "HH"
            elif price < prev_high:
                label = "LH"
            else:
                continue
            prev_high = price
        else:
            if prev_low is None:
                label = "L"
            elif price > prev_low:
                label = "HL"
            elif price < prev_low:
                label = "LL"
            else:
                continue
            prev_low = price
        labelled.append({**pivot, "label": label})
    return pd.DataFrame(labelled).tail(max_pivots).reset_index(drop=True)
