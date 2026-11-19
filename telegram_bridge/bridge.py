import json
import os
import socket
import time
import urllib.parse
import urllib.request
from urllib.error import HTTPError, URLError
import sys

if getattr(sys, "frozen", False):
    BASE_DIR = os.path.abspath(os.path.join(os.path.dirname(sys.executable), ".."))
else:
    BASE_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
# Корень проекта добавляется в sys.path, чтобы Observer работал и в EXE-сборке.
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

try:
    from observer.storage import archive_delivery
except Exception:
    archive_delivery = None

QUEUE_DIR = os.path.join(BASE_DIR, "telegram_queue")
LOG_FILE = os.path.join(BASE_DIR, "telegram_bridge_log.txt")
POLL_SECONDS = 1.0
REQUEST_TIMEOUT = 12
HEALTH_INTERVAL = 30
HOST = "api.telegram.org"
DEFAULT_TTL_SECONDS = 300
LOCK_FILE = os.path.join(BASE_DIR, ".telegram_bridge.lock")

class BridgeAlreadyRunning(RuntimeError):
    """Raised when another Telegram Bridge owns the process lock."""


class SingleInstanceLock:
    """OS-released inter-process lock that works on Windows and POSIX."""
    def __init__(self, path):
        self.path = path
        self._file = None

    def acquire(self):
        os.makedirs(os.path.dirname(os.path.abspath(self.path)), exist_ok=True)
        self._file = open(self.path, "a+b")
        try:
            self._file.seek(0, os.SEEK_END)
            if self._file.tell() == 0:
                self._file.write(b"0")
                self._file.flush()
            self._file.seek(0)
            if os.name == "nt":
                import msvcrt
                msvcrt.locking(self._file.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(self._file.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except (OSError, BlockingIOError):
            self._file.close()
            self._file = None
            raise BridgeAlreadyRunning("Another Telegram Bridge instance is already running")
        return self

    def release(self):
        if self._file is None:
            return
        try:
            self._file.seek(0)
            if os.name == "nt":
                import msvcrt
                msvcrt.locking(self._file.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                import fcntl
                fcntl.flock(self._file.fileno(), fcntl.LOCK_UN)
        finally:
            self._file.close()
            self._file = None

    def __enter__(self):
        return self.acquire()

    def __exit__(self, exc_type, exc, tb):
        self.release()
        return False



def load_env(key, default=""):
    env_path = os.path.join(BASE_DIR, ".env")
    try:
        with open(env_path, "r", encoding="utf-8-sig") as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                k, v = line.split("=", 1)
                if k.strip() == key:
                    return v.strip().strip('"').strip("'")
    except Exception:
        pass
    return os.getenv(key, default)


def log(text):
    line = time.strftime("[%Y-%m-%d %H:%M:%S]") + " " + str(text)
    try:
        print(line, flush=True)
    except UnicodeEncodeError:
        # Windows consoles may use a legacy code page that cannot encode Cyrillic.
        print(line.encode("ascii", errors="backslashreplace").decode("ascii"), flush=True)
    try:
        with open(LOG_FILE, "a", encoding="utf-8") as f:
            f.write(line + "\n")
    except Exception:
        pass


def telegram_get_me(token):
    url = f"https://{HOST}/bot{token}/getMe"
    req = urllib.request.Request(url, method="GET")
    with urllib.request.urlopen(req, timeout=REQUEST_TIMEOUT) as response:
        data = json.loads(response.read().decode("utf-8", errors="replace"))
    if not data.get("ok"):
        raise RuntimeError(data.get("description", "Telegram API error"))
    return data


def network_health(token):
    try:
        infos = socket.getaddrinfo(HOST, 443, type=socket.SOCK_STREAM)
        addresses = list(dict.fromkeys(x[4][0] for x in infos))
        if not addresses:
            raise RuntimeError("DNS returned no addresses")
        log(f"[NETWORK] DNS OK {HOST} -> {', '.join(addresses[:3])}")
    except Exception as exc:
        log(f"[NETWORK] DNS FAILED {HOST}: {exc}")
        return False
    try:
        with socket.create_connection((HOST, 443), timeout=REQUEST_TIMEOUT):
            pass
        log(f"[NETWORK] TCP OK {HOST}:443")
    except Exception as exc:
        log(f"[NETWORK] TCP FAILED {HOST}:443: {exc}")
        return False
    try:
        data = telegram_get_me(token)
        username = data.get("result", {}).get("username", "?")
        log(f"[NETWORK] TELEGRAM API OK bot=@{username}")
        return True
    except Exception as exc:
        log(f"[NETWORK] TELEGRAM API FAILED: {exc}")
        return False


def iter_messages():
    os.makedirs(QUEUE_DIR, exist_ok=True)
    return [os.path.join(QUEUE_DIR, n) for n in sorted(os.listdir(QUEUE_DIR)) if n.endswith(".json")]


def _save_queue_item(path, item):
    """Атомарно сохраняет состояние очереди и очищает temp-файл при сбое."""
    tmp = path + ".tmp"
    try:
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(item, f, ensure_ascii=False, indent=2)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, path)
    finally:
        try:
            if os.path.exists(tmp):
                os.remove(tmp)
        except OSError:
            pass


def _validate_queue_item(item):
    """Проверяет структуру JSON очереди до обращения к её полям."""
    import math

    if not isinstance(item, dict):
        raise ValueError("Корень JSON очереди должен быть объектом")
    if not isinstance(item.get("id"), str) or not item["id"].strip():
        raise ValueError("У события отсутствует корректный id")
    if not isinstance(item.get("text", ""), str):
        raise ValueError("Поле text должно быть строкой")
    if item.get("delivery_state", "pending") not in ("pending", "sending", "sent", "delivery_unknown"):
        raise ValueError("Поле delivery_state имеет неизвестное значение")
    if "telegram_sent" in item and not isinstance(item["telegram_sent"], bool):
        raise ValueError("Поле telegram_sent должно быть логическим")
    if item.get("delivery_state") == "sent" and not item.get("telegram_sent", False):
        raise ValueError("Состояние sent требует telegram_sent=true")
    if "delivery_state" in item and item.get("telegram_sent") and item["delivery_state"] != "sent":
        raise ValueError("telegram_sent=true несовместим с текущим delivery_state")
    if item.get("telegram_sent"):
        if not isinstance(item.get("telegram_result"), dict):
            raise ValueError("У доставленного события отсутствует telegram_result")
        if not item["telegram_result"].get("ok"):
            raise ValueError("telegram_result не подтверждает успешную доставку")
        if item.get("sent_ts") is None:
            raise ValueError("У доставленного события отсутствует sent_ts")
    numeric_fields = (
        "created_ts", "ttl_seconds", "attempts", "next_attempt_ts",
        "archive_attempts", "archive_next_attempt_ts", "sent_ts",
    )
    for field in numeric_fields:
        value = item.get(field)
        if value is None:
            continue
        if isinstance(value, bool):
            raise ValueError(f"Поле {field} имеет неверный тип")
        try:
            number = float(value)
        except (TypeError, ValueError, OverflowError) as exc:
            raise ValueError(f"Поле {field} имеет неверный формат") from exc
        if not math.isfinite(number) or number < 0:
            raise ValueError(f"Поле {field} имеет недопустимое значение")
    return item


def _validated_photo_path(photo_name):
    """Возвращает реальный путь только к файлу внутри telegram_queue."""
    from pathlib import Path

    queue_root = Path(QUEUE_DIR).resolve()
    photo_path = Path(str(photo_name)).resolve()
    try:
        photo_path.relative_to(queue_root)
    except ValueError:
        raise RuntimeError("Photo file missing or outside telegram_queue")
    if not photo_path.is_file():
        raise RuntimeError("Photo file missing or outside telegram_queue")
    return str(photo_path)


def _schedule_archive_retry(path, item, reason):
    """Сохраняет отдельный backoff для Observer, не затрагивая статус Telegram."""
    attempts = int(item.get("archive_attempts", 0) or 0) + 1
    delay = min(300, max(5, 2 ** min(attempts, 8)))
    item["archive_attempts"] = attempts
    item["archive_last_error"] = str(reason)
    item["archive_next_attempt_ts"] = time.time() + delay
    try:
        _save_queue_item(path, item)
    except Exception as state_exc:
        log(f"[CRITICAL] Could not persist Observer retry state for {item.get('id', path)}: {state_exc}")


def _is_definite_pre_send_error(error):
    """Recognize failures that prove the HTTP request never reached Telegram."""
    reason = error.reason if isinstance(error, URLError) else error
    return isinstance(reason, (socket.gaierror, ConnectionRefusedError))

def _mark_delivery_unknown(path, item, reason):
    """Blocks automatic resend and preserves an ambiguous delivery for review."""
    item["delivery_state"] = "delivery_unknown"
    item["delivery_unknown_reason"] = str(reason)
    try:
        _save_queue_item(path, item)
        failed_dir = os.path.join(QUEUE_DIR, "failed", "delivery_unknown")
        os.makedirs(failed_dir, exist_ok=True)
        target = os.path.join(failed_dir, os.path.basename(path))
        if os.path.exists(target):
            target = os.path.join(failed_dir, f"{int(time.time() * 1000)}_{os.path.basename(path)}")
        os.replace(path, target)
        log(f"[DELIVERY UNKNOWN] id={item.get('id', path)} moved to {target}; manual reconciliation required; automatic resend disabled")
    except Exception as exc:
        log(f"[CRITICAL] Could not quarantine uncertain delivery {item.get('id', path)}: {exc}")

def _finish_archived_delivery(path, item):
    """Повторяет только локальную архивацию уже отправленного сообщения."""
    msg_id = item.get("id", os.path.basename(path))
    if time.time() < float(item.get("archive_next_attempt_ts", 0) or 0):
        return False
    if archive_delivery is None:
        reason = "observer.storage не загружен"
        _schedule_archive_retry(path, item, reason)
        log(f"[OBSERVER PENDING] id={msg_id}: {reason}; Telegram повторно не отправляется")
        return False
    try:
        added = archive_delivery(
            BASE_DIR,
            item,
            item.get("telegram_result"),
            sent_at=item.get("sent_ts"),
        )
    except Exception as exc:
        _schedule_archive_retry(path, item, str(exc))
        log(f"[OBSERVER RETRY] id={msg_id}: {exc}")
        return False

    item.pop("archive_attempts", None)
    item.pop("archive_next_attempt_ts", None)
    item.pop("archive_last_error", None)
    if added:
        log(f"[OBSERVER SAVED] kind={item.get('kind', 'message')} id={msg_id}")
    else:
        log(f"[OBSERVER DUPLICATE] id={msg_id}")

    photo_name = item.get("photo_path")
    if photo_name:
        try:
            photo_path = _validated_photo_path(photo_name)
            os.remove(photo_path)
        except (OSError, RuntimeError):
            pass
    try:
        os.remove(path)
    except FileNotFoundError:
        pass
    except OSError as exc:
        # Архив уже сохранён. Оставляем telegram_sent JSON для безопасной
        # повторной очистки, не останавливая весь Bridge.
        log(f"[QUEUE CLEANUP PENDING] id={msg_id}: {exc}")
        return False
    log(f"[TELEGRAM SENT] {item.get('kind', 'message')} id={msg_id}")
    return True


def _remove_queued_photo(item):
    """Удаляет только локальную карточку, принадлежащую каталогу очереди."""
    photo_name = item.get("photo_path")
    if not photo_name:
        return
    try:
        os.remove(_validated_photo_path(photo_name))
    except (OSError, RuntimeError):
        pass


def _quarantine_corrupt_item(path, reason):
    """Убирает повреждённый JSON из активной очереди, сохраняя его для разбора."""
    failed_dir = os.path.join(QUEUE_DIR, "failed")
    try:
        os.makedirs(failed_dir, exist_ok=True)
        name = os.path.basename(path)
        target = os.path.join(failed_dir, f"{int(time.time() * 1000)}_{name}")
        suffix = 1
        while os.path.exists(target):
            target = os.path.join(failed_dir, f"{int(time.time() * 1000)}_{suffix}_{name}")
            suffix += 1
        os.replace(path, target)
        log(f"[QUEUE QUARANTINED] {name}: {reason}; сохранено: {target}")
    except OSError as exc:
        log(f"[BRIDGE ERROR] Cannot quarantine {os.path.basename(path)}: {exc}")


def process_file(path, token, default_channel):
    try:
        with open(path, "r", encoding="utf-8-sig") as f:
            item = json.load(f)
    except Exception as exc:
        _quarantine_corrupt_item(path, exc)
        return
    try:
        _validate_queue_item(item)
    except (TypeError, ValueError) as exc:
        _quarantine_corrupt_item(path, exc)
        return
    if item.get("delivery_state") == "sending":
        _mark_delivery_unknown(path, item, "Bridge restarted while delivery was marked sending")
        return
    if item.get("delivery_state") == "delivery_unknown":
        return
    # Если Telegram уже подтвердил доставку, повторяем только архивирование.
    # TTL и отправка здесь больше не применяются.
    if item.get("telegram_sent"):
        _finish_archived_delivery(path, item)
        return

    now = time.time()
    created = float(item.get("created_ts", now) or now)
    ttl = item.get("ttl_seconds")
    if ttl is None and item.get("kind") in ("LEVEL_APPROACH", "APPROACH", "PROXIMITY", "ALERT"):
        ttl = DEFAULT_TTL_SECONDS
    if ttl is not None and now - created > float(ttl):
        _remove_queued_photo(item)
        try:
            os.remove(path)
        except OSError:
            pass
        log(f"[EXPIRED] kind={item.get('kind', 'message')} id={item.get('id', os.path.basename(path))}")
        return
    if now < float(item.get("next_attempt_ts", 0) or 0):
        return
    channel = item.get("channel") or default_channel
    msg = str(item.get("text", ""))
    msg_id = item.get("id", os.path.basename(path))
    attempts = int(item.get("attempts", 0) or 0)
    request_started = False
    try:
        photo_name = item.get("photo_path")
        if photo_name:
            # Фотографии разрешены только из локальной очереди приложения.
            photo_path = _validated_photo_path(photo_name)
            boundary = "----ReversalLab" + str(int(time.time() * 1000))
            chunks = []
            def field(name, value):
                chunks.append((f"--{boundary}\r\nContent-Disposition: form-data; name=\"{name}\"\r\n\r\n{value}\r\n").encode())
            field("chat_id", channel)
            field("caption", msg[:1024])
            chunks.append((f"--{boundary}\r\nContent-Disposition: form-data; name=\"photo\"; filename=\"{os.path.basename(photo_path)}\"\r\nContent-Type: image/png\r\n\r\n").encode())
            with open(photo_path, "rb") as photo:
                chunks.append(photo.read())
            chunks.append(f"\r\n--{boundary}--\r\n".encode())
            req = urllib.request.Request(f"https://{HOST}/bot{token}/sendPhoto", data=b"".join(chunks), method="POST")
            req.add_header("Content-Type", f"multipart/form-data; boundary={boundary}")
        else:
            url = f"https://{HOST}/bot{token}/sendMessage"
            body = urllib.parse.urlencode({"chat_id": channel, "text": msg, "disable_web_page_preview": "true"}).encode("utf-8")
            req = urllib.request.Request(url, data=body, method="POST")
            req.add_header("Content-Type", "application/x-www-form-urlencoded")
        # Persist intent immediately before the network call. A restart after
        # this point must not blindly send the same notification a second time.
        item["delivery_state"] = "sending"
        _save_queue_item(path, item)
        request_started = True
        try:
            with urllib.request.urlopen(req, timeout=REQUEST_TIMEOUT) as response:
                data = json.loads(response.read().decode("utf-8", errors="replace"))
        except HTTPError as http_exc:
            if 400 <= http_exc.code < 500:
                item["delivery_state"] = "pending"
                raise RuntimeError(f"Telegram HTTP rejection {http_exc.code}: {http_exc}") from http_exc
            _mark_delivery_unknown(path, item, f"Telegram HTTP {http_exc.code}: outcome may be ambiguous")
            return
        except Exception as network_exc:
            if _is_definite_pre_send_error(network_exc):
                item["delivery_state"] = "pending"
                raise RuntimeError(f"Telegram connection failed before request send: {network_exc}") from network_exc
            _mark_delivery_unknown(path, item, f"{type(network_exc).__name__}: {network_exc}")
            return
        if not isinstance(data, dict) or not data.get("ok"):
            item["delivery_state"] = "pending"
            description = data.get("description", "Telegram API rejected the request") if isinstance(data, dict) else "Invalid Telegram API response"
            raise RuntimeError(description)

        # Сначала фиксируем подтверждённую Telegram доставку в очереди.
        # При сбое SQLite следующий проход повторит архивирование, а не отправку.
        item["telegram_sent"] = True
        item["delivery_state"] = "sent"
        item["telegram_result"] = data
        item["sent_ts"] = time.time()
        try:
            _save_queue_item(path, item)
        except Exception as state_exc:
            log(f"[CRITICAL] Telegram accepted id={msg_id}, but delivery state could not be persisted: {state_exc}")
            return

        _finish_archived_delivery(path, item)
    except Exception as exc:
        if item.get("delivery_state") == "sending" and request_started:
            _mark_delivery_unknown(path, item, exc)
            return
        if item.get("delivery_state") == "sending":
            # Intent persistence failed before urlopen: the HTTP request never started.
            item["delivery_state"] = "pending"
        attempts += 1
        delay = min(300, max(5, 2 ** min(attempts, 8)))
        item["attempts"] = attempts
        item["last_error"] = str(exc)
        item["next_attempt_ts"] = time.time() + delay
        try:
            _save_queue_item(path, item)
        except Exception:
            pass
        log(f"[TELEGRAM RETRY] id={msg_id} attempt={attempts} next={delay}s error={exc}")


def main():
    os.makedirs(QUEUE_DIR, exist_ok=True)
    token = load_env("TELEGRAM_BOT_TOKEN")
    channel = load_env("TELEGRAM_CHANNEL", load_env("TELEGRAM_CHAT_ID", "@reversallab"))
    if not token or not channel or token.startswith("ВСТАВЬТЕ"):
        log("[BRIDGE STOPPED] Fill TELEGRAM_BOT_TOKEN and TELEGRAM_CHANNEL in root .env")
        return 2
    log("[BRIDGE] Crypto Setup Analyzer Telegram Bridge started")
    log(f"[BRIDGE] Queue: {QUEUE_DIR}")
    log(f"[BRIDGE] Channel: {channel}")
    log("[BRIDGE] Route ONLY this executable through hide.me VPN.")
    network_health(token)
    last_health = time.time()
    last_empty = 0
    try:
        while True:
            now = time.time()
            if now - last_health >= HEALTH_INTERVAL:
                network_health(token)
                last_health = now
            paths = iter_messages()
            for path in paths:
                process_file(path, token, channel)
            if not paths and now - last_empty >= 60:
                log("[BRIDGE] Queue empty. Waiting.")
                last_empty = now
            time.sleep(POLL_SECONDS)
    except KeyboardInterrupt:
        log("[BRIDGE] Stopped by user")
    return 0


if __name__ == "__main__":
    try:
        with SingleInstanceLock(LOCK_FILE):
            raise SystemExit(main())
    except BridgeAlreadyRunning as exc:
        log(f"[BRIDGE STOPPED] {exc}")
        raise SystemExit(2)
