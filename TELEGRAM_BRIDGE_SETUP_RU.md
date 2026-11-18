# Crypto Setup Analyzer RU v1.27: Telegram Bridge (Reversal Lab v51 style)

The scanner writes messages to `telegram_queue` as JSON files and does not contact Telegram over the network. The separate `telegram_bridge\\TelegramBridge.exe` sends them through the route assigned to that EXE in hide.me.

## Setup
1. Copy `.env.example` to `.env` in the project root.
2. Set `TELEGRAM_BOT_TOKEN` and `TELEGRAM_CHANNEL` (for example `@your_channel`). Add the bot as an administrator with permission to post in the channel.
3. Run `telegram_bridge\\BUILD_TELEGRAM_BRIDGE.bat` once. It creates a dedicated venv and builds a standalone EXE.
4. Add only `telegram_bridge\\TelegramBridge.exe` to hide.me VPN routing. Keep the scanner outside the VPN.
5. Run `telegram_bridge\\start_bridge.bat`, check `telegram_bridge_log.txt` for `[NETWORK] TELEGRAM API OK bot=@...`, then run `START.bat`.

## Queue and expiration
Messages are written into `telegram_queue`. Files are removed only after Telegram confirms successful delivery and Observer has archived the event. Failed sends are retried. `LEVEL_APPROACH` alerts expire after 300 seconds; stale level alerts are discarded. Other message types have no TTL unless set by the caller.

If Telegram confirms delivery but Observer/SQLite is temporarily unavailable, Bridge stores the Telegram response and a `telegram_sent` marker in the queue file. It then retries only the local archive operation with backoff; it does not send the Telegram message again. Such files remain in `telegram_queue` until Observer saves the event. Do not manually delete these pending files if you want to preserve the local event history.

## Diagnostics
Log: `telegram_bridge_log.txt` in the project root. DNS, TCP/443 and Bot API `getMe` are checked separately. This package has not been tested against your hide.me installation; confirm the API OK line and a real channel post.


## Reversal Lab Observer

После добавления Observer пересобери Bridge: закрой уже работающий `TelegramBridge.exe` и запусти `telegram_bridge\REBUILD_TELEGRAM_BRIDGE.bat`. Сборка включает локальный модуль `observer.storage`. Затем запускай Bridge обычным способом. После первой успешной отправки в корне проекта появится `observer_data\observer_events.sqlite3` и папка `observer_data\media` с копиями карточек.

Для просмотра отчёта за последние 24 часа запусти `observer\START_OBSERVER_REPORT.bat`. Важно: старый EXE не содержит Observer, пока его не пересобрали. На работу сканера, условия сигналов и доставку уведомлений Observer не влияет.
