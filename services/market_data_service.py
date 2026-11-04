"""Сервис получения и проверки рыночных данных. UI не обращается к API напрямую."""
from crypto_setup_analyzer import market_data


class MarketDataService:
    """Единая точка доступа к Binance REST и CSV-источникам."""

    def available_symbols(self):
        return market_data.available_usdt_symbols()

    def realtime_price(self, symbol):
        return market_data.realtime_price(symbol)

    def latest_candles(self, symbol, interval, limit=3):
        return market_data.latest_candles(symbol, interval, limit=limit)

    def download_history(self, symbol, interval, days):
        return market_data.download(symbol, interval, days)

    def load_csv(self, path):
        return market_data.load_csv(path)
