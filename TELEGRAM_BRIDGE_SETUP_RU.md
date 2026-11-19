# Crypto Setup Analyzer RU: Telegram Bridge

The scanner writes messages to `telegram_queue` as JSON files and does not contact Telegram over the network. The separate `telegram_bridge\\TelegramBridge.exe` sends them through the route assigned to that EXE in hide.me.

## Setup
1. Copy `.env.example` to `.env` in the project root.
2. Set `TELEGRAM_BOT_TOKEN` and `TELEGRAM_CHANNEL` (for example `@your_channel`). Add the bot as an administrator with permission to post in the channel.
3. Run `telegram_bridge\\BUILD_TELEGRAM_BRIDGE.bat` to build a standalone EXE. Rebuild it after Bridge source updates; the EXE does not update itself.
4. Add only `telegram_bridge\\TelegramBridge.exe` to hide.me VPN routing. Keep the scanner outside the VPN.
5. Run `telegram_bridge\\start_bridge.bat`, check `telegram_bridge_log.txt` for `[NETWORK] TELEGRAM API OK bot=@...`, then run `START.bat`.

## Queue and expiration
Messages are written into `telegram_queue`. Files are removed only after Telegram confirms successful delivery and Observer has archived the event. Explicit Telegram rejections are retried with backoff. A timeout, connection interruption, invalid response after the request starts, or HTTP 5xx is an **uncertain delivery** and is never retried automatically. Such files are moved to `telegram_queue/failed/delivery_unknown/` for manual reconciliation. `LEVEL_APPROACH` alerts expire after 300 seconds; stale level alerts are discarded. Other message types have no TTL unless set by the caller.

Before sending, Bridge persists `delivery_state="sending"`. On confirmed success it stores `delivery_state="sent"`, the Telegram response and `telegram_sent=true`. If Observer/SQLite is temporarily unavailable, Bridge retries only local archiving and does not send the Telegram message again. Such files remain in `telegram_queue` until Observer saves the event.\n\nIf Bridge stops while an item is marked `sending`, or the network result is ambiguous, it is quarantined under `telegram_queue/failed/delivery_unknown/`. Check the Telegram channel manually before deciding whether to restore it to the active queue. Telegram Bot API does not provide an idempotency key, so exactly-once delivery cannot be guaranteed. The Bridge also uses an OS-level lock; a second instance exits instead of processing the same queue concurrently.

## Diagnostics
Log: `telegram_bridge_log.txt` in the project root. DNS, TCP/443 and Bot API `getMe` are checked separately. This package has not been tested against your hide.me installation; confirm the API OK line and a real channel post.


## Reversal Lab Observer

После добавления Observer пересобери Bridge: закрой уже работающий `TelegramBridge.exe` и запусти `telegram_bridge\REBUILD_TELEGRAM_BRIDGE.bat`. Сборка включает локальный модуль `observer.storage`. Затем запускай Bridge обычным способом. После первой успешной отправки в корне проекта появится `observer_data\observer_events.sqlite3` и папка `observer_data\media` с копиями карточек.

Для просмотра отчёта за последние 24 часа запусти `observer\START_OBSERVER_REPORT.bat`. Важно: старый EXE не содержит Observer, пока его не пересобрали. На работу сканера, условия сигналов и доставку уведомлений Observer не влияет.
\n\nДополнительные детали и правила ручной сверки: [PATCH 14: безопасность доставки Telegram](PATCH_14_TELEGRAM_DELIVERY_SAFETY_RU.md).\n

## Безопасность доставки и обновление EXE

После PATCH 14 Bridge сохраняет состояние отправки перед сетевым запросом. Если запрос завершился timeout, обрывом соединения, ошибкой ответа или HTTP 5xx, сообщение не отправляется повторно автоматически. JSON переносится в `telegram_queue/failed/delivery_unknown/`. Сначала проверь канал Telegram вручную. Если сообщение уже есть, не восстанавливай элемент в активную очередь. Если сообщения нет, его можно вернуть в очередь после ручной проверки, установив `delivery_state="pending"` и удалив поля подтверждённой отправки.

Если Bridge перезапустился с элементом `delivery_state="sending"`, он также переводит его в ручной карантин. Файл блокировки `.telegram_bridge.lock` создаётся в корне проекта; удалять его при работающем Bridge не следует. Второй экземпляр завершится, не обрабатывая очередь.

Подробности: [PATCH 14](PATCH_14_TELEGRAM_DELIVERY_SAFETY_RU.md).
