# Crypto Setup Analyzer RU 2.0

**Reversal Lab · Binance USDⓈ-M Futures · Python desktop application**

Crypto Setup Analyzer RU is a desktop research tool for monitoring selected Binance USDⓈ-M perpetual futures altcoins, tracking reactions around reference price levels, and sending chart-based event notifications to Telegram.

> **Research software, not an automated trading system.** The project monitors market data and records analytical events. It does not place exchange orders. No profitability claim is made.

## Highlights

- Binance Futures REST market data and WebSocket ticker updates.
- Dynamic watchlist of liquid USDT-M altcoin contracts (configured by scanner rules).
- Reference levels including daily and weekly highs/lows and scanner-supported local levels.
- Approach alerts with configurable distance threshold and repeat-alert hysteresis.
- One-minute rejection analysis using candle body, wick/body ratio, and close position.
- Telegram notification queue separated from the scanner process.
- Branded Telegram image cards rendered from **actual closed Binance Futures klines**; synthetic candles are rejected.
- SQLite persistence for recorded events and virtual-trade data structures.
- Reversal Lab Observer: a local archive of successfully delivered Telegram notifications, structured signal fields, and PNG cards.
- Desktop UI with sortable monitoring table and scrolling.
- Unit tests for scanner logic, storage, card generation, notification queue, and backtest behaviour.

## Screenshots and demo

A project presentation with authentic screenshots from the running version 2.0 is available at [docs/index.html](docs/index.html). The captures are stored in `docs/screenshots/`.

Useful future additions to the portfolio are a current main-window capture after the Futures source update, the Observer report, and a short recording of the scanner lifecycle. Only publish screenshots with API tokens, account identifiers, private paths, and personal data removed.

## Requirements

- Windows 10/11 (the supplied `.bat` launchers target Windows).
- Python 3.11+ recommended; Python 3.13 is attempted first by `START.bat`.
- Internet access to Binance public Futures endpoints.
- Optional Telegram bot and channel for notifications.

Python dependencies are listed in `requirements.txt`.

## Quick start

1. Download or clone this repository.
2. Open the project directory in Windows.
3. Run `START.bat`.
4. The launcher creates `.venv`, installs dependencies, and starts the application.

For Telegram notifications:

1. Copy `.env.example` to `.env` in the project root.
2. Set `TELEGRAM_BOT_TOKEN` and `TELEGRAM_CHANNEL` locally.
3. Follow [TELEGRAM_BRIDGE_SETUP_RU.md](TELEGRAM_BRIDGE_SETUP_RU.md) to build and configure the separate bridge executable.
4. After installing Observer, rebuild the bridge with `telegram_bridge/REBUILD_TELEGRAM_BRIDGE.bat`; the old executable does not include the archive feature.
5. View the local report with `observer/START_OBSERVER_REPORT.bat`.
6. Never commit `.env`, bot tokens, queue contents, `observer_data/`, or private logs.

## Run tests

From the project root:

```bash
python -m unittest discover -v
```

The current test suite runs in GitHub Actions on Python 3.11 and 3.13. The Telegram Bridge executable is also built in a Windows CI job. These checks do not replace a full GUI acceptance test in a Windows desktop session or a live Telegram/VPN delivery test.

## Project structure

```text
app.py                         Application entry point
ui/                            Tkinter desktop interface
crypto_setup_analyzer/         Market data, scanner, analysis, cards, notifications
services/                      Market-data and indicator services
models/                        Signal and virtual-trade models
infrastructure/                SQLite persistence
telegram_bridge/               Standalone Telegram delivery bridge source/build scripts
observer/                       Local event archive and reporting utility
observer_data/                  Local runtime archive (created automatically; private)
telegram_queue/                Local file-based notification queue (runtime data)
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
             Telegram Bridge EXE
                     |
                     v
                Telegram API
```

The scanner does not send Telegram network requests directly. The bridge is a separate process so Telegram routing can be configured independently from the scanner's normal internet connection.

## Limitations and responsible use

- Public market-data endpoints can be unavailable, rate-limited, or delayed.
- A confirmed candle rejection is a rule-based event classification, not proof that price will reverse.
- Historical/backtest results depend on input data, assumptions, fees, slippage, and execution model. They do not predict future performance.
- The project is not financial advice. Crypto futures are high-risk instruments.
- No exchange order placement is implemented in this project release.

## Portfolio note

This repository demonstrates Python application development, API integration, WebSocket processing, event-driven GUI work, SQLite persistence, chart rendering, queue-based integration, and automated tests. It should be presented as a working **research/monitoring application**, not as a proven profitable trading strategy.

## Reliability patches

- [PATCH 10: Telegram queue and scanner state recovery](PATCH_10_QUEUE_AND_STATE_RECOVERY_RU.md)
- [PATCH 11: Telegram delivery pipeline hardening](PATCH_11_DELIVERY_PIPELINE_RU.md)
- [PATCH 12: Scanner lifecycle and state recovery](PATCH_12_SCANNER_LIFECYCLE_RU.md)
- [PATCH 13: Telegram → Observer end-to-end delivery hardening](PATCH_13_TELEGRAM_OBSERVER_E2E_RU.md)
- [PATCH 14: Telegram delivery safety and single-instance lock](PATCH_14_TELEGRAM_DELIVERY_SAFETY_RU.md)
- [PATCH 15: Binance USDⓈ-M Futures data source consistency](PATCH_15_FUTURES_DATA_SOURCE_RU.md)
- [PATCH 16: UI responsiveness and closed-candle lifecycle](PATCH_16_UI_CANDLE_LIFECYCLE_RU.md)
- [PATCH 17: reliability and analysis performance](PATCH_17_RELIABILITY_PERFORMANCE_RU.md)
- [PATCH 14: Telegram delivery safety and single-instance lock](PATCH_14_TELEGRAM_DELIVERY_SAFETY_RU.md)
