"""Консольный отчёт по архиву Reversal Lab Observer."""
from __future__ import annotations

import argparse
import csv
import sqlite3
from contextlib import closing
import sys
from datetime import datetime, timezone
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
DB_PATH = BASE_DIR / "observer_data" / "observer_events.sqlite3"


def local_time(timestamp: float | None) -> str:
    if timestamp is None:
        return "-"
    return datetime.fromtimestamp(timestamp).astimezone().strftime("%Y-%m-%d %H:%M:%S")


def make_report(hours: float = 24, csv_path: str | None = None) -> int:
    if not DB_PATH.exists():
        print("Архив Observer пока пуст. Сначала отправьте хотя бы одно уведомление через Telegram Bridge.")
        return 0
    since = datetime.now(timezone.utc).timestamp() - hours * 3600
    with closing(sqlite3.connect(DB_PATH)) as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            "SELECT * FROM events WHERE sent_at >= ? ORDER BY sent_at DESC", (since,)
        ).fetchall()
        total = conn.execute("SELECT COUNT(*) FROM events").fetchone()[0]
    conn.close()

    print("=" * 68)
    print("REVERSAL LAB OBSERVER · ОТЧЁТ")
    print(f"Период: последние {hours:g} ч. | Всего в архиве: {total}")
    print(f"Событий за период: {len(rows)}")
    print("-" * 68)
    counts: dict[str, int] = {}
    for row in rows:
        counts[row["kind"]] = counts.get(row["kind"], 0) + 1
    if counts:
        for kind, count in sorted(counts.items()):
            print(f"{kind:<24} {count:>5}")
    else:
        print("За выбранный период событий нет.")

    # Повторяющийся ключ лишь повод для проверки, а не автоматическое
    # утверждение о дубле: после гистерезиса один уровень может сработать снова.
    groups: dict[tuple[str, str, str, str, str], list[sqlite3.Row]] = {}
    for row in rows:
        if not row["symbol"] or not row["level_name"]:
            continue
        period = datetime.fromtimestamp(row["sent_at"], timezone.utc).strftime("%Y-%m-%d")
        key = (row["kind"], row["symbol"], row["direction"] or "", row["level_name"], period)
        groups.setdefault(key, []).append(row)
    repeats = [(key, values) for key, values in groups.items() if len(values) > 1]
    print("-" * 68)
    print("ПОВТОРЯЮЩИЕСЯ КОМБИНАЦИИ (требуют ручной проверки):")
    if not repeats:
        print("Не обнаружены.")
    else:
        for (kind, symbol, direction, level, period), values in sorted(repeats, key=lambda x: x[1][0]["sent_at"], reverse=True):
            prices = ", ".join(f"{r['level_price']:g}" for r in values if r["level_price"] is not None)
            print(f"{len(values)}× {kind} | {symbol} {direction} | {level} | UTC-дата: {period} | уровни: {prices or '-'}")
            for row in values:
                print(f"    {local_time(row['sent_at'])} · цена {row['price'] if row['price'] is not None else '-'}")

    print("-" * 68)
    print("ПОСЛЕДНИЕ СОБЫТИЯ:")
    for row in rows[:20]:
        price = f"{row['price']:g}" if row["price"] is not None else "-"
        level_price = f"{row['level_price']:g}" if row["level_price"] is not None else "-"
        print(f"{local_time(row['sent_at'])} | {row['kind']:<18} | {row['symbol'] or '-':<12} | "
              f"{row['direction'] or '-':<5} | {row['level_name'] or '-'} {level_price} | цена {price}")

    if csv_path:
        fieldnames = list(rows[0].keys()) if rows else []
        if fieldnames:
            with open(csv_path, "w", newline="", encoding="utf-8-sig") as file:
                writer = csv.DictWriter(file, fieldnames=fieldnames)
                writer.writeheader()
                writer.writerows(dict(row) for row in rows)
            print(f"CSV сохранён: {Path(csv_path).resolve()}")
        else:
            print("CSV не создан: за выбранный период нет событий.")
    print("=" * 68)
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Отчёт по Reversal Lab Observer")
    parser.add_argument("--hours", type=float, default=24, help="Период отчёта в часах (по умолчанию 24)")
    parser.add_argument("--csv", metavar="PATH", help="Дополнительно сохранить события в CSV")
    args = parser.parse_args()
    if args.hours <= 0:
        parser.error("--hours должен быть больше нуля")
    return make_report(args.hours, args.csv)


if __name__ == "__main__":
    raise SystemExit(main())
