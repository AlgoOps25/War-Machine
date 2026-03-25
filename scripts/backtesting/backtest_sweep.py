# backtest_sweep.py — War Machine NVDA Sweep (OPTION A: relaxed entry)
import itertools
import sys
import time
from datetime import datetime
from zoneinfo import ZoneInfo

import pandas as pd
import numpy as np

sys.path.insert(0, "app/data")
from db_connection import get_connection

TICKER             = "NVDA"
ET                 = ZoneInfo("America/New_York")
MAX_BARS_PER_TRADE = 78
ATR_PERIOD         = 14
STARTING_CAPITAL   = 100_000
RISK_PER_TRADE     = 0.01
MIN_TRADES         = 20        # ignore combos with fewer trades than this

SWEEP = {
    "orb_minutes":    [5, 10, 15, 20],
    "atr_multiplier": [1.0, 1.5, 2.0, 2.5, 3.0],
    "volume_pct":     [1.00, 1.25, 1.50, 1.75],
    "fvg_min_pct":    [0.001, 0.002, 0.003, 0.005],
    "profit_r":       [1.5, 2.0, 2.5, 3.0],
}

# ─────────────────────────────────────────────
# DATA LOAD
# ─────────────────────────────────────────────
def load_bars(ticker: str) -> pd.DataFrame:
    with get_connection() as conn:
        df = pd.read_sql(
            "SELECT datetime AS timestamp, open, high, low, close, volume "
            "FROM intraday_bars_5m WHERE ticker = %s ORDER BY datetime ASC",
            conn, params=(ticker,),
        )
    df["timestamp"] = pd.to_datetime(df["timestamp"], utc=True).dt.tz_convert(ET)
    return df.set_index("timestamp").sort_index()


# ─────────────────────────────────────────────
# PRE-COMPUTE (once)
# ─────────────────────────────────────────────
def compute_atr(df: pd.DataFrame, period: int) -> pd.Series:
    high, low, close = df["high"], df["low"], df["close"]
    tr = pd.concat([
        high - low,
        (high - close.shift(1)).abs(),
        (low  - close.shift(1)).abs(),
    ], axis=1).max(axis=1)
    return tr.ewm(span=period, adjust=False).mean()


def build_fvg_sets(df: pd.DataFrame, min_pcts: list) -> dict:
    high  = df["high"].values
    low   = df["low"].values
    close = df["close"].values
    times = df.index

    gaps_bull = np.zeros(len(df))
    gaps_bear = np.zeros(len(df))
    for i in range(2, len(df)):
        gaps_bull[i] = low[i]    - high[i - 2]
        gaps_bear[i] = low[i - 2] - high[i]

    result = {}
    for pct in min_pcts:
        fvg_set = set()
        for i in range(2, len(df)):
            price = close[i]
            if price == 0:
                continue
            if gaps_bull[i] > 0 and (gaps_bull[i] / price) >= pct:
                fvg_set.add(times[i])
            elif gaps_bear[i] > 0 and (gaps_bear[i] / price) >= pct:
                fvg_set.add(times[i])
        result[pct] = fvg_set
        print(f"  [FVG] pct={pct} → {len(fvg_set)} signals")
    return result


def split_into_sessions(df: pd.DataFrame) -> list:
    sessions = []
    for date in sorted(set(df.index.date)):
        day_df  = df[df.index.date == date]
        session = day_df.between_time("09:30", "15:55")
        if len(session) >= 6:
            sessions.append((date, session))
    return sessions


# ─────────────────────────────────────────────
# BACKTEST ENGINE
# ─────────────────────────────────────────────
def backtest(sessions, atr, vol_ma20, fvg_set,
             orb_minutes, atr_multiplier, volume_pct, profit_r) -> dict:
    orb_bars = orb_minutes // 5
    trades   = []
    equity   = STARTING_CAPITAL

    for date, session in sessions:
        if len(session) < orb_bars + ATR_PERIOD + 2:
            continue

        orb_high  = session.iloc[:orb_bars]["high"].max()
        orb_low   = session.iloc[:orb_bars]["low"].min()
        in_trade  = False
        bars_held = 0
        shares    = 1
        entry_px  = stop_px = target_px = 0.0
        direction = None

        for idx in range(orb_bars, len(session)):
            bar    = session.iloc[idx]
            bar_ts = session.index[idx]

            bar_atr = atr.get(bar_ts, np.nan)
            avg_vol = vol_ma20.get(bar_ts, np.nan)
            if np.isnan(bar_atr) or np.isnan(avg_vol) or avg_vol == 0:
                continue

            if in_trade:
                bars_held += 1
                hit_stop   = (direction == "long"  and bar["low"]  <= stop_px) \
                           or (direction == "short" and bar["high"] >= stop_px)
                hit_target = (direction == "long"  and bar["high"] >= target_px) \
                           or (direction == "short" and bar["low"]  <= target_px)
                timeout    = bars_held >= MAX_BARS_PER_TRADE

                if hit_target:
                    pnl    = (target_px - entry_px if direction == "long" else entry_px - target_px) * shares
                    result = "target"
                elif hit_stop:
                    pnl    = (stop_px - entry_px if direction == "long" else entry_px - stop_px) * shares
                    result = "stop"
                elif timeout:
                    pnl    = (bar["close"] - entry_px if direction == "long" else entry_px - bar["close"]) * shares
                    result = "timeout"
                else:
                    continue

                trades.append({"date": date, "direction": direction, "pnl": pnl, "result": result})
                equity  += pnl
                in_trade = False
                continue

            # ── OPTION A: OR logic — FVG OR volume confirmation ──
            vol_ok = bar["volume"] >= avg_vol * volume_pct
            fvg_ok = bar_ts in fvg_set
            if not (vol_ok or fvg_ok):      # <-- OR instead of AND
                continue

            stop_dist = bar_atr * atr_multiplier
            if stop_dist == 0:
                continue
            shares = max(1, int((equity * RISK_PER_TRADE) / stop_dist))

            if bar["close"] > orb_high:
                entry_px  = bar["close"]
                stop_px   = entry_px - stop_dist
                target_px = entry_px + stop_dist * profit_r
                direction = "long"
                in_trade  = True
                bars_held = 0
            elif bar["close"] < orb_low:
                entry_px  = bar["close"]
                stop_px   = entry_px + stop_dist
                target_px = entry_px - stop_dist * profit_r
                direction = "short"
                in_trade  = True
                bars_held = 0

    if len(trades) < MIN_TRADES:
        return {"trades": len(trades)}     # skipped — not enough sample

    df_t      = pd.DataFrame(trades)
    wins      = df_t[df_t["pnl"] > 0]
    losses    = df_t[df_t["pnl"] <= 0]
    total     = len(df_t)
    pf_denom  = abs(losses["pnl"].sum())
    pf        = round(wins["pnl"].sum() / pf_denom, 3) if pf_denom > 0 else 0
    daily_pnl = df_t.groupby("date")["pnl"].sum()
    sharpe    = round(daily_pnl.mean() / daily_pnl.std() * np.sqrt(252), 3) \
                if daily_pnl.std() > 0 else 0
    eq_curve  = STARTING_CAPITAL + df_t["pnl"].cumsum()
    max_dd    = round(((eq_curve - eq_curve.cummax()) / eq_curve.cummax()).min(), 4)

    return {
        "trades":        total,
        "win_rate":      round(len(wins) / total, 4),
        "avg_win":       round(wins["pnl"].mean(), 2)  if len(wins)   else 0,
        "avg_loss":      round(losses["pnl"].mean(), 2) if len(losses) else 0,
        "profit_factor": pf,
        "total_pnl":     round(df_t["pnl"].sum(), 2),
        "sharpe":        sharpe,
        "max_drawdown":  max_dd,
    }


# ─────────────────────────────────────────────
# MAIN
# ─────────────────────────────────────────────
if __name__ == "__main__":
    print(f"[SWEEP] Loading {TICKER} bars...")
    df5m = load_bars(TICKER)
    print(f"[SWEEP] {len(df5m):,} 5m bars | {df5m.index[0]} → {df5m.index[-1]}")

    print("[SWEEP] Pre-computing indicators...")
    atr      = compute_atr(df5m, ATR_PERIOD)
    vol_ma20 = df5m["volume"].rolling(20).mean()
    sessions = split_into_sessions(df5m)
    print(f"[SWEEP] {len(sessions)} trading sessions found")

    print("[SWEEP] Pre-building FVG sets...")
    fvg_cache = build_fvg_sets(df5m, SWEEP["fvg_min_pct"])

    keys   = list(SWEEP.keys())
    combos = list(itertools.product(*SWEEP.values()))
    total  = len(combos)
    print(f"[SWEEP] {total} combinations | MIN_TRADES threshold: {MIN_TRADES}\n")

    results = []
    start   = time.time()

    for i, combo in enumerate(combos, 1):
        params  = dict(zip(keys, combo))
        fvg_set = fvg_cache[params["fvg_min_pct"]]

        stats = backtest(
            sessions, atr, vol_ma20, fvg_set,
            orb_minutes    = params["orb_minutes"],
            atr_multiplier = params["atr_multiplier"],
            volume_pct     = params["volume_pct"],
            profit_r       = params["profit_r"],
        )

        # Only keep combos that passed MIN_TRADES threshold
        if stats.get("trades", 0) >= MIN_TRADES and "sharpe" in stats:
            results.append({**params, **stats})

        if i % 100 == 0 or i == total:
            elapsed = time.time() - start
            print(f"  [{i}/{total}] {i/total*100:.1f}% — {elapsed:.1f}s elapsed")

    if not results:
        print("\n[SWEEP] No combos met the MIN_TRADES threshold. Try lowering MIN_TRADES.")
    else:
        df_out = pd.DataFrame(results).sort_values(
            ["sharpe", "profit_factor", "win_rate"], ascending=False
        ).reset_index(drop=True)

        fname = f"sweep_results_{TICKER}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"
        df_out.to_csv(fname, index=False)

        print(f"\n[SWEEP] Complete — {len(df_out)} valid combos → {fname}")
        print(f"\nTOP 10 BY SHARPE (min {MIN_TRADES} trades):")
        print(df_out.head(10).to_string(index=False))
