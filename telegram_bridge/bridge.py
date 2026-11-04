import json
import os
import socket
import time
import urllib.parse
import urllib.request
import sys

if getattr(sys, "frozen", False):
    BASE_DIR = os.path.abspath(os.path.join(os.path.dirname(sys.executable), ".."))
else:
    BASE_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
QUEUE_DIR = os.path.join(BASE_DIR, "telegram_queue")
LOG_FILE = os.path.join(BASE_DIR, "telegram_bridge_log.txt")
POLL_SECONDS = 1.0
REQUEST_TIMEOUT = 12
HEALTH_INTERVAL = 30
HOST = "api.telegram.org"
DEFAULT_TTL_SECONDS = 300


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
    print(line, flush=True)
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


def process_file(path, token, default_channel):
    try:
        with open(path, "r", encoding="utf-8-sig") as f:
            item = json.load(f)
    except Exception as exc:
        log(f"[BRIDGE ERROR] Cannot read {os.path.basename(path)}: {exc}")
        return
    now = time.time()
    created = float(item.get("created_ts", now) or now)
    ttl = item.get("ttl_seconds")
    if ttl is None and item.get("kind") in ("LEVEL_APPROACH", "APPROACH", "PROXIMITY", "ALERT"):
        ttl = DEFAULT_TTL_SECONDS
    if ttl is not None and now - created > float(ttl):
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
    try:
        photo_name = item.get("photo_path")
        if photo_name:
            # Фотографии разрешены только из локальной очереди приложения.
            photo_path = os.path.abspath(photo_name)
            queue_root = os.path.abspath(QUEUE_DIR) + os.sep
            if not photo_path.startswith(queue_root) or not os.path.isfile(photo_path):
                raise RuntimeError("Photo file missing or outside telegram_queue")
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
        with urllib.request.urlopen(req, timeout=REQUEST_TIMEOUT) as response:
            data = json.loads(response.read().decode("utf-8", errors="replace"))
        if not data.get("ok"):
            raise RuntimeError(data.get("description", "Telegram API error"))
        os.remove(path)
        if photo_name:
            try:
                os.remove(photo_path)
            except OSError:
                pass
        log(f"[TELEGRAM SENT] {item.get('kind', 'message')} id={msg_id}")
    except Exception as exc:
        attempts += 1
        delay = min(300, max(5, 2 ** min(attempts, 8)))
        item["attempts"] = attempts
        item["last_error"] = str(exc)
        item["next_attempt_ts"] = time.time() + delay
        tmp = path + ".tmp"
        try:
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(item, f, ensure_ascii=False, indent=2)
            os.replace(tmp, path)
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
    log("[BRIDGE] Crypto Setup Analyzer Telegram Bridge based on Reversal Lab v51 started")
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
    raise SystemExit(main())
