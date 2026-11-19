from pathlib import Path
import time
import math
import requests
import pandas as pd

URL = "https://fapi.binance.com/fapi/v1/klines"
EXCHANGE_INFO_URL = "https://fapi.binance.com/fapi/v1/exchangeInfo"
TICKER_PRICE_URL = "https://fapi.binance.com/fapi/v1/ticker/price"
MS = {"1m":60000,"3m":180000,"5m":300000,"15m":900000,"30m":1800000,
      "1h":3600000,"2h":7200000,"4h":14400000,"1d":86400000}

def available_usdt_symbols():
    """Возвращает торгуемые бессрочные Binance USDⓈ-M USDT-контракты."""
    with requests.Session() as session:
        response = session.get(EXCHANGE_INFO_URL, timeout=20)
        response.raise_for_status()
        payload = response.json()
    symbols = [
        item["symbol"] for item in payload.get("symbols", [])
        if item.get("status") == "TRADING"
        and item.get("quoteAsset") == "USDT"
        and item.get("contractType") == "PERPETUAL"
    ]
    return sorted(set(symbols))

def realtime_price(symbol="NEARUSDT"):
    """Fetch the latest Binance USDⓈ-M perpetual-contract price (REST polling)."""
    symbol = str(symbol).strip().upper()
    if not symbol or not symbol.isalnum():
        raise ValueError("Укажи корректный тикер, например NEARUSDT.")
    url = TICKER_PRICE_URL
    with requests.Session() as session:
        response = session.get(url, params={"symbol": symbol}, timeout=5)
        response.raise_for_status()
        payload = response.json()
    if "price" not in payload:
        raise RuntimeError(f"Binance не вернула цену для {symbol}.")
    price = float(payload["price"])
    if not math.isfinite(price) or price <= 0:
        raise RuntimeError(f"Binance вернула недопустимую цену для {symbol}.")
    return price


def validate(df):
    cols = ["timestamp","open","high","low","close","volume"]
    missing = [c for c in cols if c not in df.columns]
    if missing: raise ValueError("В CSV не хватает столбцов: " + ", ".join(missing))
    out = df[cols].copy()
    out["timestamp"] = pd.to_datetime(out["timestamp"], utc=True, errors="coerce")
    for c in ["open","high","low","close","volume"]: out[c] = pd.to_numeric(out[c], errors="coerce")
    if out.isna().any().any(): raise ValueError("Есть пустые или некорректные значения.")
    if (out[["open","high","low","close"]] <= 0).any().any(): raise ValueError("Цены должны быть положительными.")
    if (out.volume < 0).any(): raise ValueError("Объём не может быть отрицательным.")
    if (out.high < out[["open","close","low"]].max(axis=1)).any(): raise ValueError("Некорректный максимум свечи.")
    if (out.low > out[["open","close","high"]].min(axis=1)).any(): raise ValueError("Некорректный минимум свечи.")
    return out.sort_values("timestamp").drop_duplicates("timestamp", keep="last").reset_index(drop=True)

def load_csv(path):
    return validate(pd.read_csv(path))

def download(symbol="NEARUSDT", interval="1m", days=3):
    if interval not in MS: raise ValueError("Неподдерживаемый таймфрейм.")
    if not 1 <= int(days) <= 30: raise ValueError("Период должен быть от 1 до 30 дней.")
    end = int(time.time()*1000)
    cursor = end-int(days)*86400000
    rows = []
    with requests.Session() as s:
        while cursor < end:
            r = s.get(URL, params={"symbol":symbol.upper(),"interval":interval,
                "startTime":cursor,"endTime":end,"limit":1000}, timeout=20)
            r.raise_for_status()
            batch = r.json()
            if not batch: break
            rows.extend(batch)
            nxt = int(batch[-1][0])+MS[interval]
            if nxt <= cursor: break
            cursor = nxt
            if len(batch) < 1000: break
            time.sleep(.12)
    if not rows: raise RuntimeError("Binance не вернула свечи. Проверь символ и доступность API.")
    raw = pd.DataFrame(rows, columns=["ot","open","high","low","close","volume","ct","qv","trades","tb","tq","ignore"])
    df = pd.DataFrame({"timestamp":pd.to_datetime(raw.ot.astype("int64"),unit="ms",utc=True),
        "open":raw.open.astype(float),"high":raw.high.astype(float),"low":raw.low.astype(float),
        "close":raw.close.astype(float),"volume":raw.volume.astype(float)})
    return validate(df)


def latest_candles(symbol="NEARUSDT", interval="5m", limit=3):
    """Fetch the most recent Binance USDⓈ-M candles, including the currently forming candle."""
    if interval not in MS:
        raise ValueError("Неподдерживаемый таймфрейм.")
    symbol = str(symbol).strip().upper()
    if not symbol or not symbol.isalnum():
        raise ValueError("Укажи корректный тикер, например NEARUSDT.")
    with requests.Session() as session:
        response = session.get(URL, params={"symbol": symbol, "interval": interval, "limit": max(2, min(int(limit), 10))}, timeout=5)
        response.raise_for_status()
        rows = response.json()
    if not rows:
        raise RuntimeError("Binance не вернула последние свечи.")
    raw = pd.DataFrame(rows, columns=["ot","open","high","low","close","volume","ct","qv","trades","tb","tq","ignore"])
    df = pd.DataFrame({
        "timestamp": pd.to_datetime(raw.ot.astype("int64"), unit="ms", utc=True),
        "open": raw.open.astype(float), "high": raw.high.astype(float),
        "low": raw.low.astype(float), "close": raw.close.astype(float),
        "volume": raw.volume.astype(float)
    })
    return validate(df)
