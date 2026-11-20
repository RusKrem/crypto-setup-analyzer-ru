# Crypto Setup Analyzer RU 2.0

**Reversal Lab · Binance USDⓈ-M Futures · Python desktop application**

Crypto Setup Analyzer RU is a desktop research and monitoring application for selected Binance USDⓈ-M perpetual futures altcoins. It monitors market data, tracks reactions around reference price levels, classifies rule-based events, and can deliver chart-based notifications to Telegram.

> **Research software, not an automated trading system.** The application does not place exchange orders and makes no profitability claims.

## Features

- Binance Futures REST market data and WebSocket ticker updates.
- Configurable watchlist of USDT-M perpetual contracts.
- Reference levels including daily and weekly highs/lows and scanner-supported local levels.
- Approach alerts with configurable distance thresholds and repeat-alert hysteresis.
- One-minute rejection analysis using candle body, wick/body ratio, and close position.
- Separate Telegram notification queue and delivery bridge.
- Chart cards generated from actual closed Binance Futures candles.
- SQLite persistence for event records and virtual-trade data.
- Reversal Lab Observer for archiving delivered notifications, structured event data, and PNG cards.
- Desktop interface with a sortable monitoring table.
- Unit tests for scanner logic, storage, card generation, notification queue, and backtest behaviour.

## Screenshots and project presentation

A presentation with screenshots from the running application is available at [the project website](https://ruskrem.github.io/crypto-setup-analyzer-ru/). Screenshots are also stored in `docs/screenshots/`.

## Requirements

- Windows 10/11.
- Python 3.11+ recommended.
- Internet access to Binance public Futures endpoints.
- Optional Telegram bot and channel for notifications.

Dependencies are listed in `requirements.txt`.

## Quick start

1. Download or clone this repository.
2. Open the project folder in Windows.
3. Run `START.bat`.
4. The launcher creates a virtual environment, installs dependencies, and starts the application.

## Telegram setup

1. Copy `.env.example` to `.env` in the project root.
2. Configure `TELEGRAM_BOT_TOKEN` and `TELEGRAM_CHANNEL` locally.
3. Follow [TELEGRAM_BRIDGE_SETUP_RU.md](TELEGRAM_BRIDGE_SETUP_RU.md) to build and configure the separate bridge executable.
4. Rebuild the bridge as described in the setup guide after updating the application.
5. The local Observer report can be launched using `observer/START_OBSERVER_REPORT.bat`.

Never commit `.env`, bot tokens, private queue contents, `observer_data/`, or private logs.

## Tests

Run the test suite from the project root:

```bash
python -m unittest discover -v
```

GitHub Actions runs the test suite on Python 3.11 and 3.13 and builds the Telegram Bridge in Windows CI. Automated checks do not replace interactive GUI acceptance testing or live Telegram delivery testing.

## Architecture

```text
app.py                         Application entry point
ui/                            Tkinter desktop interface
crypto_setup_analyzer/         Market data, scanner, analysis, cards, notifications
services/                      Market-data and indicator services
models/                        Signal and virtual-trade models
infrastructure/                SQLite persistence
telegram_bridge/               Standalone Telegram delivery bridge
observer/                       Local event archive and reporting utility
observer_data/                  Local runtime archive (private)
telegram_queue/                Local notification queue (runtime data)
tests/                         Unit tests
assets/                        Reversal Lab brand assets
```

See [ARCHITECTURE.md](ARCHITECTURE.md) for responsibilities and data flow.

## Data flow

```text
Binance Futures REST + WebSocket
              |
              v
       Market data / scanner
              |
       +------+------+
       |             |
       v             v
   SQLite       Signal-card renderer
                     |
                     v
             telegram_queue/*.json
                     |
                     v
             Telegram Bridge
                     |
                     v
                Telegram API
```

The scanner does not send Telegram network requests directly. The bridge is a separate process so Telegram routing can be configured independently.

## Limitations and responsible use

- Public market-data endpoints can be unavailable, rate-limited, or delayed.
- Rule-based candle rejection classification is not proof of a future reversal.
- Historical results depend on data, assumptions, fees, slippage, and execution models and do not predict future performance.
- This project is not financial advice. Crypto futures are high-risk instruments.
- Exchange order placement is not implemented.

## Portfolio

This project demonstrates practical Python application development, API integration, WebSocket data processing, desktop UI development, SQLite persistence, chart rendering, integration pipelines, and automated testing.

## Reliability and development notes

- [PATCH 10: Telegram queue and scanner state recovery](PATCH_10_QUEUE_AND_STATE_RECOVERY_RU.md)
- [PATCH 11: Telegram delivery pipeline hardening](PATCH_11_DELIVERY_PIPELINE_RU.md)
- [PATCH 12: Scanner lifecycle and state recovery](PATCH_12_SCANNER_LIFECYCLE_RU.md)
- [PATCH 13: Telegram → Observer end-to-end delivery hardening](PATCH_13_TELEGRAM_OBSERVER_E2E_RU.md)
- [PATCH 14: Telegram delivery safety and single-instance lock](PATCH_14_TELEGRAM_DELIVERY_SAFETY_RU.md)
- [PATCH 15: Binance USDⓈ-M Futures data source consistency](PATCH_15_FUTURES_DATA_SOURCE_RU.md)
- [PATCH 16: UI responsiveness and closed-candle lifecycle](PATCH_16_UI_CANDLE_LIFECYCLE_RU.md)
- [PATCH 17: reliability and analysis performance](PATCH_17_RELIABILITY_PERFORMANCE_RU.md)
