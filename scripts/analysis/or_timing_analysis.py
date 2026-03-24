#!/usr/bin/env python3
"""
OR Timing Distribution Analysis
"""

import os
import sys
import json
import logging
import numpy as np
import pandas as pd
import matplotlib.pyplot as plt
import matplotlib.ticker as mtick
from collections import defaultdict
from datetime import time
from zoneinfo import ZoneInfo

# ── Path setup ────────────────────────────────────────────────────────────────
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))

from app.data.db_connection import get_connection   # context manager: with get_connection() as conn
from utils import config

# ── Config ────────────────────────────────────────────────────────────────────
ET = ZoneInfo("America/New_York")
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)

TICKERS          = None   # auto-discovered from DB (see get_eligible_tickers())
MIN_SESSIONS     = 30     # minimum trading sessions required for reliable OR config
SESSION_START    = time(9, 30)
SESSION_END      = time(16, 0)
OR_FIXED_END     = time(9, 40)
SCAN_UNTIL       = time(11, 0)
ATR_PERIOD       = 14
DISP_MULT        = 0.10
FVG_MIN_PCT      = 0.0005
FALSE_BREAK_BARS = 10
FALSE_BREAK_RETRACE = 0.60
OUTPUT_DIR       = "output/or_timing"

os.makedirs(OUTPUT_DIR, exist_ok=True)


# ── DB helpers ────────────────────────────────────────────────────────────────

def get_eligible_tickers(min_sessions: int = MIN_SESSIONS) -> list[str]:
    """
    Query DB for tickers with >= min_sessions distinct trading days.
    Returns list sorted by session count descending.
    """
    with get_connection() as conn:
        cur = conn.cursor()
        cur.execute("""
            SELECT ticker, COUNT(DISTINCT datetime::date) AS sessions
            FROM   intraday_bars
            WHERE  datetime::time >= '09:30:00'
              AND  datetime::time <  '16:00:00'
            GROUP  BY ticker
            HAVING COUNT(DISTINCT datetime::date) >= %s
            ORDER  BY sessions DESC
        """, (min_sessions,))
        rows = cur.fetchall()
        cur.close()
    tickers = [r[0] for r in rows]
    logger.info(f"Eligible tickers ({min_sessions}+ sessions): {len(tickers)} found")
    return tickers

def fetch_all_sessions(ticker: str) -> dict:
    """
    Returns { date_str: [bar_dict, ...] } sorted by datetime ASC.
    """
    with get_connection() as conn:
        cur = conn.cursor()
        cur.execute(
            """
            SELECT datetime AT TIME ZONE 'America/New_York' AS dt,
                   open, high, low, close, volume
            FROM   intraday_bars
            WHERE  ticker = %s
              AND  datetime::time >= '09:25:00'
              AND  datetime::time <  '16:00:00'
            ORDER  BY datetime ASC
            """,
            (ticker,),
        )
        rows = cur.fetchall()
        cur.close()

    sessions = defaultdict(list)
    for r in rows:
        dt = r[0] if hasattr(r, "__getitem__") else r[0]
        # RealDictCursor returns dict-like rows
        if isinstance(r, dict):
            dt, o, h, l, c, v = r[0], r["open"], r["high"], r["low"], r["close"], r["volume"]
        else:
            dt, o, h, l, c, v = r[0], r[1], r[2], r[3], r[4], r[5]

        if hasattr(dt, "tzinfo") and dt.tzinfo is None:
            dt = dt.replace(tzinfo=ET)

        sessions[dt.date().isoformat()].append({
            "datetime": dt,
            "open":  float(o),
            "high":  float(h),
            "low":   float(l),
            "close": float(c),
            "volume": int(v),
        })

    return dict(sorted(sessions.items()))

def compute_atr(bars: list, period: int = ATR_PERIOD) -> float:
    if len(bars) < 2:
        return None
    trs = []
    for i in range(1, len(bars)):
        h, l, pc = bars[i]["high"], bars[i]["low"], bars[i - 1]["close"]
        trs.append(max(h - l, abs(h - pc), abs(l - pc)))
    if not trs:
        return None
    return float(np.mean(trs[-period:]))


def bar_time(bar: dict) -> time:
    dt = bar["datetime"]
    if hasattr(dt, "tzinfo") and dt.tzinfo:
        dt = dt.astimezone(ET)
    return dt.time().replace(second=0, microsecond=0)


def bar_minute_offset(bar: dict) -> int:
    """Minutes since 9:30."""
    t = bar_time(bar)
    return (t.hour - 9) * 60 + t.minute - 30


def find_or_levels(session_bars: list) -> tuple:
    """Compute OR high/low from 9:30–9:40 bars."""
    or_bars = [b for b in session_bars if SESSION_START <= bar_time(b) < OR_FIXED_END]
    if len(or_bars) < 3:
        return None, None
    return max(b["high"] for b in or_bars), min(b["low"] for b in or_bars)


def find_first_bos(session_bars: list, or_high: float, or_low: float, atr: float) -> dict | None:
    """
    Walk bars after 9:40 and find the first bar where:
      - close breaks above or_high (bull BOS) OR below or_low (bear BOS)
      - bar body (abs(close - open)) >= DISP_MULT * ATR  (displacement filter)
      - bar time <= SCAN_UNTIL
    Returns dict with keys: bar, direction, minute_offset
    """
    if atr is None or atr == 0:
        return None

    min_body = DISP_MULT * atr

    for bar in session_bars:
        bt = bar_time(bar)
        if bt < OR_FIXED_END:
            continue
        if bt > SCAN_UNTIL:
            break

        body = abs(bar["close"] - bar["open"])
        if body < min_body:
            continue

        if bar["close"] > or_high:
            return {"bar": bar, "direction": "bull", "minute_offset": bar_minute_offset(bar)}
        if bar["close"] < or_low:
            return {"bar": bar, "direction": "bear", "minute_offset": bar_minute_offset(bar)}

    return None


def is_false_break(session_bars: list, bos: dict, or_high: float, or_low: float) -> bool:
    """
    After BOS bar, check the next FALSE_BREAK_BARS bars.
    If price retraces FALSE_BREAK_RETRACE of the breakout extension → false break.
    """
    bos_bar   = bos["bar"]
    direction = bos["direction"]
    bos_close = bos_bar["close"]

    # find index of bos bar
    try:
        idx = next(i for i, b in enumerate(session_bars) if b["datetime"] == bos_bar["datetime"])
    except StopIteration:
        return False

    forward = session_bars[idx + 1 : idx + 1 + FALSE_BREAK_BARS]
    if not forward:
        return False

    if direction == "bull":
        extension = bos_close - or_high
        if extension <= 0:
            return False
        worst_low = min(b["low"] for b in forward)
        retrace   = bos_close - worst_low
        return retrace >= FALSE_BREAK_RETRACE * extension

    else:  # bear
        extension = or_low - bos_close
        if extension <= 0:
            return False
        worst_high = max(b["high"] for b in forward)
        retrace    = worst_high - bos_close
        return retrace >= FALSE_BREAK_RETRACE * extension


def find_first_fvg(session_bars: list, bos: dict) -> dict | None:
    """
    After BOS bar, find first 3-bar FVG in the same direction.
    Returns dict with minute_offset, size, or None.
    """
    bos_bar   = bos["bar"]
    direction = bos["direction"]

    try:
        idx = next(i for i, b in enumerate(session_bars) if b["datetime"] == bos_bar["datetime"])
    except StopIteration:
        return None

    for i in range(idx + 1, len(session_bars) - 1):
        c0, c2 = session_bars[i - 1], session_bars[i + 1]
        ref = c0["close"]
        if ref == 0:
            continue

        if direction == "bull":
            gap = c2["low"] - c0["high"]
            if gap > 0 and (gap / ref) >= FVG_MIN_PCT:
                return {"minute_offset": bar_minute_offset(session_bars[i + 1]), "size": gap}
        else:
            gap = c0["low"] - c2["high"]
            if gap > 0 and (gap / ref) >= FVG_MIN_PCT:
                return {"minute_offset": bar_minute_offset(session_bars[i + 1]), "size": gap}

    return None


# ── Per-ticker analysis ───────────────────────────────────────────────────────

def analyse_ticker(ticker: str, sessions: dict) -> dict:
    bos_offsets     = []
    fvg_offsets     = []
    false_breaks    = []
    or_class_counts = defaultdict(int)
    total_sessions  = 0
    no_bos_sessions = 0

    for date_str, bars in sessions.items():
        total_sessions += 1

        or_high, or_low = find_or_levels(bars)
        if or_high is None:
            no_bos_sessions += 1
            continue

        atr = compute_atr(bars)
        or_range = or_high - or_low
        if atr and atr > 0:
            ratio = or_range / atr
            if ratio < 0.5:
                or_class_counts["TIGHT"] += 1
            elif ratio < 1.5:
                or_class_counts["NORMAL"] += 1
            else:
                or_class_counts["WIDE"] += 1

        bos = find_first_bos(bars, or_high, or_low, atr)
        if bos is None:
            no_bos_sessions += 1
            continue

        bos_offsets.append(bos["minute_offset"])
        false_breaks.append(is_false_break(bars, bos, or_high, or_low))

        fvg = find_first_fvg(bars, bos)
        if fvg:
            fvg_offsets.append(fvg["minute_offset"])

    return {
        "ticker":           ticker,
        "total_sessions":   total_sessions,
        "no_bos_sessions":  no_bos_sessions,
        "bos_offsets":      bos_offsets,
        "fvg_offsets":      fvg_offsets,
        "false_breaks":     false_breaks,
        "or_class_counts":  dict(or_class_counts),
    }


def summarise(result: dict) -> dict:
    bos  = result["bos_offsets"]
    fvg  = result["fvg_offsets"]
    fb   = result["false_breaks"]

    if not bos:
        return {"ticker": result["ticker"], "error": "no BOS sessions found"}

    p25, p50, p75 = np.percentile(bos, [25, 50, 75])
    false_rate    = sum(fb) / len(fb) if fb else 0.0

    # bucket false-break rate: split sessions into early (<= 10 min) vs late (> 10 min)
    early_fb = [fb[i] for i, o in enumerate(bos) if o <= 10]
    late_fb  = [fb[i] for i, o in enumerate(bos) if o > 10]

    # recommend OR end: minute where 60% of clean BOSes have occurred
    sorted_bos = sorted(bos)
    target      = int(0.60 * len(sorted_bos))
    rec_offset  = sorted_bos[target] if target < len(sorted_bos) else sorted_bos[-1]
    rec_time    = f"09:{30 + rec_offset:02d}" if rec_offset < 30 else f"10:{rec_offset - 30:02d}"

    return {
        "ticker":              result["ticker"],
        "sessions_analysed":   len(bos),
        "total_sessions":      result["total_sessions"],
        "bos_p25_min":         round(float(p25), 1),
        "bos_median_min":      round(float(p50), 1),
        "bos_p75_min":         round(float(p75), 1),
        "false_break_rate":    round(false_rate * 100, 1),
        "early_false_rate":    round(sum(early_fb) / len(early_fb) * 100, 1) if early_fb else None,
        "late_false_rate":     round(sum(late_fb)  / len(late_fb)  * 100, 1) if late_fb  else None,
        "fvg_median_min":      round(float(np.median(fvg)), 1) if fvg else None,
        "recommended_or_end":  rec_time,
        "recommended_offset":  rec_offset,
        "or_class_counts":     result["or_class_counts"],
    }


# ── Charts ────────────────────────────────────────────────────────────────────

def plot_distributions(results: list[dict], summaries: list[dict]):
    n     = len(results)
    cols  = 3
    rows  = (n + cols - 1) // cols
    fig, axes = plt.subplots(rows, cols, figsize=(18, rows * 4))
    axes  = axes.flatten()
    fig.suptitle("BOS Timing Distribution by Ticker (minutes after 9:30)", fontsize=16, fontweight="bold", y=1.01)

    for i, (res, summ) in enumerate(zip(results, summaries)):
        ax  = axes[i]
        bos = res["bos_offsets"]
        fb  = res["false_breaks"]

        if not bos:
            ax.set_visible(False)
            continue

        bins = range(0, 92, 5)
        ax.hist(bos, bins=bins, color="#4C72B0", edgecolor="white", alpha=0.85, label="All BOS")

        # false break overlay
        fb_offsets = [o for o, f in zip(bos, fb) if f]
        if fb_offsets:
            ax.hist(fb_offsets, bins=bins, color="#DD4444", edgecolor="white", alpha=0.65, label="False break")

        # vertical lines
        ax.axvline(10, color="#FFAA00", linewidth=1.8, linestyle="--", label="Current OR end (9:40)")
        ax.axvline(summ.get("recommended_offset", 10), color="#22BB55",
                   linewidth=2.0, linestyle="-", label=f"Recommended ({summ['recommended_or_end']})")

        ax.set_title(f"{res['ticker']}  |  median {summ['bos_median_min']}m  |  FB {summ['false_break_rate']}%",
                     fontsize=10, fontweight="bold")
        ax.set_xlabel("Minutes after 9:30")
        ax.set_ylabel("Sessions")
        ax.legend(fontsize=7)
        ax.set_xlim(0, 90)

    for j in range(i + 1, len(axes)):
        axes[j].set_visible(False)

    plt.tight_layout()
    path = os.path.join(OUTPUT_DIR, "or_timing_distribution.png")
    plt.savefig(path, dpi=150, bbox_inches="tight")
    plt.close()
    logger.info(f"Chart saved → {path}")


def plot_false_break_heatmap(summaries: list[dict]):
    tickers    = [s["ticker"] for s in summaries if "error" not in s]
    early_fb   = [s.get("early_false_rate") or 0 for s in summaries if "error" not in s]
    late_fb    = [s.get("late_false_rate")  or 0 for s in summaries if "error" not in s]
    rec_offset = [s.get("recommended_offset", 10) for s in summaries if "error" not in s]

    x = np.arange(len(tickers))
    w = 0.35

    fig, ax = plt.subplots(figsize=(14, 5))
    bars1 = ax.bar(x - w/2, early_fb, w, label="Early BOS (≤10 min)",  color="#DD4444", alpha=0.85)
    bars2 = ax.bar(x + w/2, late_fb,  w, label="Late BOS (>10 min)",   color="#4C72B0", alpha=0.85)

    # recommended OR offset as scatter
    ax2 = ax.twinx()
    ax2.plot(x, rec_offset, "D--", color="#22BB55", markersize=8, linewidth=1.5, label="Rec. OR offset (min)")
    ax2.set_ylabel("Recommended OR end (min after 9:30)", color="#22BB55")
    ax2.tick_params(axis="y", labelcolor="#22BB55")
    ax2.set_ylim(0, 45)

    ax.axhline(30, color="#FFAA00", linewidth=1.2, linestyle=":", label="30% false break ref")
    ax.set_xticks(x)
    ax.set_xticklabels(tickers, fontsize=11)
    ax.set_ylabel("False Break Rate (%)")
    ax.set_title("False Break Rate: Early vs Late BOS  +  Recommended OR End per Ticker", fontsize=13, fontweight="bold")
    ax.yaxis.set_major_formatter(mtick.PercentFormatter())

    lines1, labels1 = ax.get_legend_handles_labels()
    lines2, labels2 = ax2.get_legend_handles_labels()
    ax.legend(lines1 + lines2, labels1 + labels2, fontsize=9, loc="upper left")

    plt.tight_layout()
    path = os.path.join(OUTPUT_DIR, "false_break_heatmap.png")
    plt.savefig(path, dpi=150, bbox_inches="tight")
    plt.close()
    logger.info(f"Chart saved → {path}")


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    logger.info("Starting OR timing analysis...")

    all_results   = []
    all_summaries = []

    tickers = get_eligible_tickers(MIN_SESSIONS)
    for ticker in tickers:
        logger.info(f"  Fetching {ticker}...")
        sessions = fetch_all_sessions(ticker)
        logger.info(f"  {ticker}: {len(sessions)} sessions loaded")

        result  = analyse_ticker(ticker, sessions)
        summary = summarise(result)

        all_results.append(result)
        all_summaries.append(summary)
        logger.info(f"  {ticker}: median BOS={summary.get('bos_median_min')}m  "
                    f"FB={summary.get('false_break_rate')}%  "
                    f"rec_OR_end={summary.get('recommended_or_end')}")

    # ── Save CSV ──────────────────────────────────────────────────────────────
    df = pd.DataFrame([s for s in all_summaries if "error" not in s])
    csv_path = os.path.join(OUTPUT_DIR, "or_timing_summary.csv")
    df.to_csv(csv_path, index=False)
    logger.info(f"Summary CSV → {csv_path}")

    # ── Save raw JSON ─────────────────────────────────────────────────────────
    raw = {r["ticker"]: {"bos_offsets": r["bos_offsets"], "false_breaks": r["false_breaks"]} for r in all_results}
    with open(os.path.join(OUTPUT_DIR, "or_timing_raw.json"), "w") as f:
        json.dump(raw, f)
        # ── Save per-ticker OR config (for backtest wiring) ──────────────────────
    or_config = {
        s["ticker"]: {
            "or_end_time":       s["recommended_or_end"],
            "or_end_offset_min": s["recommended_offset"],
            "sessions":          s["sessions_analysed"],
            "false_break_rate":  s["false_break_rate"],
            "tradeable":         s["false_break_rate"] < 95.0,  # flag extreme FB tickers
        }
        for s in all_summaries if "error" not in s
}
    config_path = os.path.join(OUTPUT_DIR, "ticker_or_config.json")
    with open(config_path, "w") as f:
        json.dump(or_config, f, indent=2)
    logger.info(f"OR config JSON → {config_path}")

    # ── Charts ────────────────────────────────────────────────────────────────
    plot_distributions(all_results, all_summaries)
    plot_false_break_heatmap(all_summaries)

    # ── Print table ───────────────────────────────────────────────────────────
    print("\n" + "="*90)
    print(f"{'TICKER':<7} {'SESSIONS':>9} {'BOS_P25':>8} {'BOS_MED':>8} {'BOS_P75':>8} "
          f"{'FB%':>6} {'EARLY_FB%':>10} {'LATE_FB%':>9} {'FVG_MED':>8} {'REC_END':>9}")
    print("="*90)
    for s in all_summaries:
        if "error" in s:
            print(f"{s['ticker']:<7}  ERROR: {s['error']}")
            continue
        print(
            f"{s['ticker']:<7} {s['sessions_analysed']:>9} "
            f"{s['bos_p25_min']:>8} {s['bos_median_min']:>8} {s['bos_p75_min']:>8} "
            f"{s['false_break_rate']:>6} "
            f"{str(s['early_false_rate'] or '-'):>10} "
            f"{str(s['late_false_rate']  or '-'):>9} "
            f"{str(s['fvg_median_min']   or '-'):>8} "
            f"{s['recommended_or_end']:>9}"
        )
    print("="*90)


if __name__ == "__main__":
    main()    # no asyncio.run() needed
