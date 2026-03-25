#!/usr/bin/env python3
"""
OR Range Threshold Grid Search for War Machine
-----------------------------------------------
Grid searches or_range_min_pct and or_range_max_pct while keeping all
other filters at their Phase 1.37 baseline values.

Outputs a ranked table sorted by Total R, plus an optional CSV.

Usage:
    python scripts/backtesting/or_range_grid.py
    python scripts/backtesting/or_range_grid.py --results-dir backtests/results
    python scripts/backtesting/or_range_grid.py --csv-out backtests/results/or_range_grid.csv
"""

import argparse
import glob
import os
import sys
from itertools import product
from typing import Dict, Any

import pandas as pd

# ---------------------------------------------------------------------------
# Baseline filter config (all filters except OR Range stay fixed)
# ---------------------------------------------------------------------------
BASELINE_CFG = {
    "rvol_gate":           1.2,
    "grade_gate":          ["A", "B"],
    "confidence_gate":     0.5,
    "dead_zone_start_hour": 9,
    "dead_zone_start_min":  30,
    "dead_zone_end_hour":   9,
    "dead_zone_end_min":    45,
    "eod_cutoff_hour":     15,
    "eod_cutoff_min":      30,
    "fvg_size_min_pct":    0.01,
}

# ---------------------------------------------------------------------------
# OR Range grid values to test
# ---------------------------------------------------------------------------
OR_MIN_VALUES = [0.0, 0.1, 0.2, 0.3, 0.5]          # lower bound on OR range %
OR_MAX_VALUES = [1.5, 2.0, 2.5, 3.0, 4.0, 5.0, 99.0]  # upper bound (99 = no cap)

# ---------------------------------------------------------------------------
# Filter helpers (same logic as filter_ablation.py)
# ---------------------------------------------------------------------------

def passes_baseline(row, cfg) -> bool:
    """Check all non-OR-range filters."""
    # RVOL
    if float(row.get("rvol", 0)) < cfg["rvol_gate"]:
        return False
    # Grade
    if str(row.get("grade", "")).upper() not in [g.upper() for g in cfg["grade_gate"]]:
        return False
    # Confidence
    if float(row.get("confidence", 0)) < cfg["confidence_gate"]:
        return False
    # Dead zone
    try:
        h = int(row.get("entry_hour", 0))
        m = int(row.get("entry_minute", 0))
        dz_start = cfg["dead_zone_start_hour"] * 60 + cfg["dead_zone_start_min"]
        dz_end   = cfg["dead_zone_end_hour"]   * 60 + cfg["dead_zone_end_min"]
        trade_min = h * 60 + m
        if dz_start <= trade_min < dz_end:
            return False
    except Exception:
        pass
    # EOD cutoff
    try:
        h = int(row.get("entry_hour", 0))
        m = int(row.get("entry_minute", 0))
        cutoff = cfg["eod_cutoff_hour"] * 60 + cfg["eod_cutoff_min"]
        if (h * 60 + m) >= cutoff:
            return False
    except Exception:
        pass
    # FVG size
    try:
        if float(row.get("fvg_size_pct", 1.0)) < cfg["fvg_size_min_pct"]:
            return False
    except Exception:
        pass
    return True


def passes_or_range(row, or_min: float, or_max: float) -> bool:
    try:
        rng = float(row.get("or_range_pct", 1.0))
        return or_min <= rng <= or_max
    except Exception:
        return True


# ---------------------------------------------------------------------------
# Data loading
# ---------------------------------------------------------------------------

def load_all_trades(results_dir: str) -> pd.DataFrame:
    pattern = os.path.join(results_dir, "*_trades.csv")
    files = sorted(glob.glob(pattern))
    if not files:
        sys.exit(f"[ERROR] No *_trades.csv files found in: {results_dir}")
    frames = []
    for f in files:
        try:
            frames.append(pd.read_csv(f))
        except Exception as e:
            print(f"  [WARN] Could not read {f}: {e}")
    if not frames:
        sys.exit("[ERROR] All trade files failed to load.")
    combined = pd.concat(frames, ignore_index=True)
    print(f"Loaded {len(combined)} trades from {len(files)} symbols.")
    return combined


def compute_stats(df: pd.DataFrame) -> Dict[str, Any]:
    if df.empty:
        return {"trades": 0, "win_rate": 0.0, "avg_r": 0.0, "total_r": 0.0}
    return {
        "trades":   len(df),
        "win_rate": round(df["win"].astype(int).mean() * 100, 1),
        "avg_r":    round(df["r_multiple"].mean(), 3),
        "total_r":  round(df["r_multiple"].sum(), 2),
    }


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description="OR Range grid search")
    parser.add_argument("--results-dir", default="backtests/results")
    parser.add_argument("--csv-out", default=None)
    parser.add_argument("--min-trades", type=int, default=5,
                        help="Minimum trades to include a row in results (default: 5)")
    args = parser.parse_args()

    df_all = load_all_trades(args.results_dir)

    cfg = BASELINE_CFG.copy()

    # Pre-filter: apply all baseline filters once
    base_mask = df_all.apply(lambda row: passes_baseline(row, cfg), axis=1)
    df_base_filtered = df_all[base_mask].copy()
    print(f"Trades passing all non-OR-range filters: {len(df_base_filtered)}\n")

    # --- Baseline (current OR range 0.2–3.0) ---
    CURRENT_MIN = 0.2
    CURRENT_MAX = 3.0
    df_current = df_base_filtered[
        df_base_filtered.apply(
            lambda r: passes_or_range(r, CURRENT_MIN, CURRENT_MAX), axis=1
        )
    ]
    current_stats = compute_stats(df_current)

    # --- Grid search ---
    results = []
    for or_min, or_max in product(OR_MIN_VALUES, OR_MAX_VALUES):
        if or_min >= or_max:
            continue
        df_filtered = df_base_filtered[
            df_base_filtered.apply(
                lambda r: passes_or_range(r, or_min, or_max), axis=1
            )
        ]
        stats = compute_stats(df_filtered)
        if stats["trades"] < args.min_trades:
            continue
        results.append({
            "or_min": or_min,
            "or_max": or_max,
            "trades":    stats["trades"],
            "win_rate":  stats["win_rate"],
            "avg_r":     stats["avg_r"],
            "total_r":   stats["total_r"],
            "delta_total_r": round(stats["total_r"] - current_stats["total_r"], 2),
            "delta_trades":  stats["trades"] - current_stats["trades"],
        })

    results_df = pd.DataFrame(results).sort_values("total_r", ascending=False).reset_index(drop=True)

    # --- Print report ---
    print("=" * 80)
    print(" OR RANGE GRID SEARCH  —  sorted by Total R  (all other filters: baseline)")
    print("=" * 80)
    print(f"  Current setting: or_min={CURRENT_MIN}  or_max={CURRENT_MAX}")
    print(f"  Current result : {current_stats['trades']} trades | "
          f"{current_stats['win_rate']:.1f}% WR | "
          f"{current_stats['avg_r']:+.3f} avg R | "
          f"{current_stats['total_r']:+.2f} total R")
    print()
    print(f"  {'Rank':<5} {'or_min':>7} {'or_max':>7} {'Trades':>7} {'WR%':>7} "
          f"{'Avg R':>8} {'Total R':>9} {'ΔTrades':>8} {'ΔTotalR':>9}")
    print("-" * 80)

    for i, row in results_df.iterrows():
        marker = " ← current" if (row["or_min"] == CURRENT_MIN and row["or_max"] == CURRENT_MAX) else ""
        max_label = "∞" if row["or_max"] >= 99 else f"{row['or_max']}"
        print(
            f"  {i+1:<5} {row['or_min']:>7.2f} {max_label:>7} "
            f"{int(row['trades']):>7} {row['win_rate']:>6.1f}% "
            f"{row['avg_r']:>+8.3f} {row['total_r']:>+9.2f} "
            f"{int(row['delta_trades']):>+8} {row['delta_total_r']:>+9.2f}"
            f"{marker}"
        )

    print("=" * 80)

    # Best by avg R (quality)
    best_avg_r = results_df.loc[results_df["avg_r"].idxmax()]
    # Best by total R (volume * quality)
    best_total_r = results_df.iloc[0]

    print(f"\n  Best Avg R  : or_min={best_avg_r['or_min']}  or_max={best_avg_r['or_max']}  "
          f"→ {best_avg_r['avg_r']:+.3f} avg R | {best_avg_r['trades']} trades")
    print(f"  Best Total R: or_min={best_total_r['or_min']}  or_max={best_total_r['or_max']}  "
          f"→ {best_total_r['total_r']:+.2f} total R | {best_total_r['trades']} trades")
    print()

    if args.csv_out:
        results_df.to_csv(args.csv_out, index=False)
        print(f"  Results saved to: {args.csv_out}\n")


if __name__ == "__main__":
    main()
