"""Regression tests: the primary chart must use Binance USDⓈ-M Futures."""
import unittest
from unittest.mock import patch

from crypto_setup_analyzer import market_data


class FakeResponse:
    def __init__(self, payload):
        self.payload = payload

    def raise_for_status(self):
        pass

    def json(self):
        return self.payload


class FakeSession:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def get(self, url, **kwargs):
        self.calls.append((url, kwargs))
        return FakeResponse(self.responses.pop(0))


class FuturesMarketDataTests(unittest.TestCase):
    def test_primary_endpoints_are_usdm_futures(self):
        self.assertEqual(market_data.URL, "https://fapi.binance.com/fapi/v1/klines")
        self.assertEqual(
            market_data.EXCHANGE_INFO_URL,
            "https://fapi.binance.com/fapi/v1/exchangeInfo",
        )
        self.assertEqual(
            market_data.TICKER_PRICE_URL,
            "https://fapi.binance.com/fapi/v1/ticker/price",
        )

    def test_available_symbols_accepts_only_trading_usdt_perpetuals(self):
        payload = {"symbols": [
            {"symbol": "NEARUSDT", "status": "TRADING", "quoteAsset": "USDT",
             "contractType": "PERPETUAL"},
            {"symbol": "NEARUSDC", "status": "TRADING", "quoteAsset": "USDC",
             "contractType": "PERPETUAL"},
            {"symbol": "NEARUSDT_OLD", "status": "TRADING", "quoteAsset": "USDT",
             "contractType": "CURRENT_QUARTER"},
            {"symbol": "BADUSDT", "status": "BREAK", "quoteAsset": "USDT",
             "contractType": "PERPETUAL"},
            {"symbol": "SPOTUSDT", "status": "TRADING", "quoteAsset": "USDT",
             "isSpotTradingAllowed": True},
        ]}
        session = FakeSession([payload])
        with patch.object(market_data.requests, "Session", return_value=session):
            self.assertEqual(market_data.available_usdt_symbols(), ["NEARUSDT"])
        self.assertEqual(session.calls[0][0], market_data.EXCHANGE_INFO_URL)

    def test_realtime_price_uses_futures_ticker_endpoint(self):
        session = FakeSession([{"symbol": "NEARUSDT", "price": "5.25"}])
        with patch.object(market_data.requests, "Session", return_value=session):
            self.assertEqual(market_data.realtime_price("NEARUSDT"), 5.25)
        self.assertEqual(session.calls[0][0], market_data.TICKER_PRICE_URL)


    def test_realtime_price_rejects_non_finite_or_non_positive_values(self):
        for value in ("nan", "inf", "0", "-1"):
            session = FakeSession([{"symbol": "NEARUSDT", "price": value}])
            with patch.object(market_data.requests, "Session", return_value=session):
                with self.assertRaises(RuntimeError):
                    market_data.realtime_price("NEARUSDT")

    def test_latest_candles_uses_futures_klines_endpoint(self):
        row = [1700000000000, "5", "6", "4", "5.5", "100",
               1700000299999, "0", 1, "0", "0", "0"]
        session = FakeSession([[row]])
        with patch.object(market_data.requests, "Session", return_value=session):
            frame = market_data.latest_candles("NEARUSDT", "5m", limit=1)
        self.assertEqual(len(frame), 1)
        self.assertEqual(session.calls[0][0], market_data.URL)
        self.assertEqual(session.calls[0][1]["params"]["symbol"], "NEARUSDT")


if __name__ == "__main__":
    unittest.main()
