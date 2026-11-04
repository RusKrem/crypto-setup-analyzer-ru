"""Сравнение входов в отскок от PDH/PDL на 1m, 3m и 5m."""
import argparse
from pathlib import Path
import pandas as pd

def load_data(path):
    df = pd.read_csv(path)
    df["timestamp"] = pd.to_datetime(df["timestamp"], utc=True)
    df = df.sort_values("timestamp").drop_duplicates("timestamp").reset_index(drop=True)
    for col in ("open", "high", "low", "close"):
        df[col] = pd.to_numeric(df[col], errors="coerce")
    return df.dropna(subset=["open","high","low","close"])

def aggregate(df, minutes):
    if minutes == 1:
        return df.copy()
    x = df.set_index("timestamp")
    out = x.resample(f"{minutes}min", label="left", closed="left").agg(
        {"open":"first","high":"max","low":"min","close":"last","volume":"sum"}
    ).dropna(subset=["open","high","low","close"]).reset_index()
    return out

def run_one(symbol, df1m, timeframe, fee_pct=0.1, slippage_pct=0.02):
    """Тестирует отскок от вчерашних уровней, вход со следующего открытия."""
    bars = aggregate(df1m, timeframe)
    if len(bars) < 10:
        return []
    # Уровни рассчитываются по полной предыдущей UTC-дате.
    daily = df1m.set_index("timestamp").resample("1D").agg(
        {"high":"max","low":"min"}).dropna()
    daily.index = daily.index.date
    prev = {}
    dates = sorted(daily.index)
    for i in range(1, len(dates)):
        prev[dates[i]] = (float(daily.loc[dates[i-1],"high"]), float(daily.loc[dates[i-1],"low"]))
    trades=[]
    for i in range(1, len(bars)-1):
        row=bars.iloc[i]
        date=row["timestamp"].date()
        if date not in prev: continue
        pdh,pdl=prev[date]
        direction=None; level_name=None; level=None
        # Только закрытая свеча: прокол/касание и возврат за уровень.
        if row["low"] <= pdl and row["close"] > pdl and row["close"] > row["open"]:
            direction,level_name,level="LONG","PDL",pdl
        elif row["high"] >= pdh and row["close"] < pdh and row["close"] < row["open"]:
            direction,level_name,level="SHORT","PDH",pdh
        if not direction: continue
        # Реалистичнее закрытия сигнальной свечи: вход на следующей свечи open.
        entry=float(bars.iloc[i+1]["open"])
        if direction=="LONG":
            stop=float(row["low"])*0.999
            risk=entry-stop
            target=entry+2*risk
        else:
            stop=float(row["high"])*1.001
            risk=stop-entry
            target=entry-2*risk
        if risk<=0 or target<=0: continue
        exit_price=None; outcome="OPEN"; exit_time=None
        # Смотрим 1m бары после входа, даже если подтверждение было 3m/5m.
        start=bars.iloc[i+1]["timestamp"]
        future=df1m[df1m["timestamp"]>=start]
        # Не открываем бесконечный трейд: максимум 24 часа данных после входа.
        for _, candle in future.iterrows():
            if (candle["timestamp"]-start).total_seconds()>86400: break
            if direction=="LONG":
                hit_stop=candle["low"]<=stop
                hit_target=candle["high"]>=target
            else:
                hit_stop=candle["high"]>=stop
                hit_target=candle["low"]<=target
            if hit_stop and hit_target:
                outcome="AMBIGUOUS_STOP_FIRST"; exit_price=stop; exit_time=candle["timestamp"]; break
            if hit_stop:
                outcome="STOP"; exit_price=stop; exit_time=candle["timestamp"]; break
            if hit_target:
                outcome="TARGET"; exit_price=target; exit_time=candle["timestamp"]; break
        if exit_price is None:
            continue
        gross=(exit_price-entry)/entry*100
        if direction=="SHORT": gross=-gross
        # Издержки на вход и выход, в процентах от оборота (приближение).
        net=gross-2*(fee_pct+slippage_pct)
        r_mult=(net/100*entry)/risk if direction=="LONG" else (net/100*entry)/risk
        trades.append({
            "symbol":symbol,"timeframe_min":timeframe,"signal_time":row["timestamp"],
            "entry_time":start,"direction":direction,"level_name":level_name,
            "level":level,"entry":entry,"stop":stop,"target":target,
            "exit_time":exit_time,"exit":exit_price,"outcome":outcome,
            "gross_pct":round(gross,5),"net_pct":round(net,5),"net_R":round(r_mult,4)
        })
    return trades

def main():
    parser=argparse.ArgumentParser(description="Сравнение таймфреймов подтверждения отскока.")
    parser.add_argument("--data-dir",default="data",help="Папка с *_1m.csv файлами")
    parser.add_argument("--output-dir",default="rebound_tf_results",help="Папка отчётов")
    parser.add_argument("--fee-pct",type=float,default=0.1,help="Комиссия на одну сторону, проценты")
    parser.add_argument("--slippage-pct",type=float,default=0.02,help="Проскальзывание на одну сторону, проценты")
    args=parser.parse_args()
    data_dir=Path(args.data_dir); out=Path(args.output_dir); out.mkdir(parents=True,exist_ok=True)
    all_trades=[]
    for file in sorted(data_dir.glob("*_1m.csv")):
        symbol=file.name.replace("_1m.csv","").upper()
        df=load_data(file)
        for tf in (1,3,5):
            all_trades.extend(run_one(symbol,df,tf,args.fee_pct,args.slippage_pct))
    trades=pd.DataFrame(all_trades)
    trades.to_csv(out/"trades_comparison.csv",index=False)
    if trades.empty:
        summary=pd.DataFrame(columns=["timeframe_min","trades","targets","stops","win_rate_pct","net_pct_sum","net_R_sum"])
    else:
        summary=trades.groupby("timeframe_min").agg(
            trades=("outcome","size"),
            targets=("outcome",lambda x:int((x=="TARGET").sum())),
            stops=("outcome",lambda x:int(x.str.contains("STOP").sum())),
            win_rate_pct=("outcome",lambda x:round((x=="TARGET").mean()*100,2)),
            net_pct_sum=("net_pct","sum"),
            net_R_sum=("net_R","sum"),
        ).reset_index()
    summary.to_csv(out/"summary_comparison.csv",index=False)
    print("Сравнение завершено.")
    print(summary.to_string(index=False) if not summary.empty else "Нет завершённых сделок на имеющихся данных.")
    print(f"Отчёты: {out.resolve()}")
if __name__=="__main__":
    main()
