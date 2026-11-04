"""Запуск исторического теста стратегии HH ↔ LL."""
import argparse
from pathlib import Path
import pandas as pd
from crypto_setup_analyzer.market_data import download, load_csv, validate
from crypto_setup_analyzer.swing_backtest import backtest_hh_ll


def main():
    parser = argparse.ArgumentParser(description="Бэктест: HH -> SHORT, LL -> LONG; HL/LH игнорируются")
    parser.add_argument("--symbol", default="GTCUSDT", help="Торговая пара Binance Spot, например GTCUSDT")
    parser.add_argument("--interval", default="15m", choices=["1m","3m","5m","15m","30m","1h","2h","4h","1d"])
    parser.add_argument("--days", type=int, default=30, help="История для загрузки: от 1 до 30 дней")
    parser.add_argument("--csv", help="Вместо Binance загрузить свечи из CSV")
    parser.add_argument("--pivot-window", type=int, default=5, help="Количество свечей для подтверждения экстремума справа")
    parser.add_argument("--fee", type=float, default=0.1, help="Комиссия на одну сторону в процентах, по умолчанию 0.1")
    parser.add_argument("--slippage", type=float, default=0.02, help="Проскальзывание на одну сторону в процентах")
    parser.add_argument("--out", default="swing_backtest_results", help="Папка для CSV-отчётов")
    args = parser.parse_args()

    if args.csv:
        candles = load_csv(args.csv)
        source = f"CSV: {args.csv}"
    else:
        candles = download(args.symbol, args.interval, args.days)
        source = f"Binance Spot {args.symbol.upper()} / {args.interval} / {args.days} дней"
    trades, summary, structure = backtest_hh_ll(candles, args.pivot_window, args.fee, args.slippage)
    folder = Path(args.out)
    folder.mkdir(parents=True, exist_ok=True)
    trades.to_csv(folder / "trades.csv", index=False, encoding="utf-8-sig")
    structure.to_csv(folder / "confirmed_extremes.csv", index=False, encoding="utf-8-sig")
    pd.DataFrame([{"Источник данных": source, **summary}]).to_csv(folder / "summary.csv", index=False, encoding="utf-8-sig")
    print("\n=== БЭКТЕСТ HH ↔ LL ===")
    print("Источник:", source)
    for key, value in summary.items():
        print(f"{key}: {value}")
    print("\nОтчёты сохранены в:", folder.resolve())
    print("Важно: это исторический тест гипотезы, не прогноз будущей доходности.")


if __name__ == "__main__":
    main()
