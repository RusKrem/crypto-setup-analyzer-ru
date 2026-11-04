# Architecture

## Runtime components

- `app.py` starts the desktop application.
- `ui/` contains Tkinter windows and user interaction.
- `crypto_setup_analyzer/market_data.py` and `services/market_data_service.py` isolate market-data access.
- `crypto_setup_analyzer/rebound_scanner.py` tracks symbols, prices, levels, and reaction conditions.
- `crypto_setup_analyzer/signal_card.py` renders branded cards. It validates the Binance kline shape and OHLC consistency before drawing.
- `crypto_setup_analyzer/telegram_notifier.py` writes notification jobs to a local file queue.
- `telegram_bridge/bridge.py` is a separate delivery process for Telegram Bot API calls.
- `infrastructure/storage.py` persists application records in SQLite.
- `models/` contains signal and virtual-trade data models.
- `tests/` covers key behaviours without requiring live exchange credentials.

## Notification flow

1. The scanner detects an approach or a confirmed reaction.
2. The notifier requests closed one-minute Futures klines if they are not already present in the event payload.
3. The card renderer validates and draws the actual OHLC data.
4. The notifier writes a JSON job referencing the rendered image into `telegram_queue/`.
5. The bridge reads queued jobs and delivers them to the configured Telegram channel.

The queue/bridge separation keeps Telegram network routing independent of Binance market-data traffic.

## Persistence

SQLite is used for local event and virtual-trade persistence. Runtime database files are intentionally excluded from the public source package. A user should back up their own database before upgrading or changing application files.

## Testing boundary

Unit tests validate deterministic logic and local integrations. They do not prove strategy profitability, uninterrupted WebSocket operation, live Binance availability, Windows GUI behaviour, or Telegram delivery in every network/VPN configuration.
