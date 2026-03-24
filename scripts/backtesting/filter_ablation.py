#!/usr/bin/env python3
"""
Filter Ablation Testing for War Machine Backtests
--------------------------------------------------
Loads all *_trades.csv from backtests/results/, runs a baseline pass
(all filters ON), then one ablation pass per filter (that filter OFF),
and reports the delta impact of each filter.

Usage:
    python scripts/backtesting/filter_ablation.py
    python scripts/backtesting/filter_ablation.py --results-dir backtests/results
    python scripts/backtesting/filter_ablation.py --csv-out ablation_results.csv
"""

import argparse
import glob
import os
import sys
from pathlib import Path
from typing import Dict, List, Any

import pandas as pd

# ---------------------------------------------------------------------------
# Default filter configuration — mirrors Phase 1.37 production settings
# ---------------------------------------------------------------------------
DEFAULT_CONFIG = {
    "rvol_gate":             1.2,    # Minimum RVOL to take a trade
    "grade_gate":            ["A", "B"],  # Allowed signal grades
    "confidence_gate":       0.5,    # Minimum confidence score
    "dead_zone_start_hour":  9,      # Dead zone: 9:30–9:45 AM
    "dead_zone_start_min":   30,
    "dead_zone_end_hour":    9,
    "dead_zone_end_min":     45,
    "eod_cutoff_hour":       15,     # No entries at or after 3:30 PM
    "eod_cutoff_min":        30,
    "or_range_max_pct":      3.0,    # Skip overly wide OR (choppy open)
    "or_range_min_pct":      0.2,    # Skip paper-thin OR (no range)
    "fvg_size_min_pct":      0.01,   # Skip micro gaps
}

# ---------------------------------------------------------------------------
# Filter functions — each returns True if the trade PASSES the filter
# ---------------------------------------------------------------------------

def f_rvol(row, cfg) -> bool:
    return float(row.get("rvol", 0)) >= cfg["rvol_gate"]

def f_grade(row, cfg) -> bool:
    return str(row.get("grade", "")).upper() in [g.upper() for g in cfg["grade_gate"]]

def f_confidence(row, cfg) -> bool:
    return float(row.get("confidence", 0)) >= cfg["confidence_gate"]

def f_dead_zone(row, cfg) -> bool:
    """Reject trades fired in the 9:30–9:45 dead zone."""
    try:
        h = int(row.get("entry_hour", 0))
        m = int(row.get("entry_minute", 0))
        dz_start = cfg["dead_zone_start_hour"] * 60 + cfg["dead_zone_start_min"]
        dz_end   = cfg["dead_zone_end_hour"]   * 60 + cfg["dead_zone_end_min"]
        trade_min = h * 60 + m
        return not (dz_start <= trade_min < dz_end)
    except Exception:
        return True

def f_eod_cutoff(row, cfg) -> bool:
    """Reject entries at or after EOD cutoff."""
    try:
        h = int(row.get("entry_hour", 0))
        m = int(row.get("entry_minute", 0))
        cutoff = cfg["eod_cutoff_hour"] * 60 + cfg["eod_cutoff_min"]
        return (h * 60 + m) < cutoff
    except Exception:
        return True

def f_or_range(row, cfg) -> bool:
    """Reject OR ranges that are too wide or too narrow."""
    try:
        rng = float(row.get("or_range_pct", 1.0))
        return cfg["or_range_min_pct"] <= rng <= cfg["or_range_max_pct"]
    except Exception:
        return True

def f_fvg_size(row, cfg) -> bool:
    """Reject micro FVGs."""
    try:
        return float(row.get("fvg_size_pct", 1.0)) >= cfg["fvg_size_min_pct"]
    except Exception:
        return True

# Registry: name → (filter_fn, human label)
FILTERS: Dict[str, tuple] = {
    "RVOL Gate":       (f_rvol,       f"RVOL ≥ {DEFAULT_CONFIG['rvol_gate']}x"),
    "Grade Gate":      (f_grade,      "Grade A/B only"),
    "Confidence Gate": (f_confidence, f"Confidence ≥ {DEFAULT_CONFIG['confidence_gate']}"),
    "Dead Zone":       (f_dead_zone,  "No trades 9:30–9:45"),
    "EOD Cutoff":      (f_eod_cutoff, "No entries after 15:30"),
    "OR Range":        (f_or_range,   f"OR range {DEFAULT_CONFIG['or_range_min_pct']}–{DEFAULT_CONFIG['or_range_max_pct']}%"),
    "FVG Size":        (f_fvg_size,   f"FVG ≥ {DEFAULT_CONFIG['fvg_size_min_pct']}%"),
}

# ---------------------------------------------------------------------------
# Core helpers
# ---------------------------------------------------------------------------

def load_all_trades(results_dir: str) -> pd.DataFrame:
    pattern = os.path.join(results_dir, "*_trades.csv")
    files = sorted(glob.glob(pattern))
    if not files:
        sys.exit(f"[ERROR] No *_trades.csv files found in: {results_dir}")
    frames = []
    for f in files:
        try:
            df = pd.read_csv(f)
            frames.append(df)
        except Exception as e:
            print(f"  [WARN] Could not read {f}: {e}")
    if not frames:
        sys.exit("[ERROR] All trade files failed to load.")
    combined = pd.concat(frames, ignore_index=True)
    print(f"Loaded {len(combined)} trades from {len(files)} symbols.")
    return combined


def apply_all_filters(df: pd.DataFrame, cfg: dict, skip_filter: str = None) -> pd.DataFrame:
    """Return subset of df that passes all filters, optionally skipping one."""
    mask = pd.Series([True] * len(df), index=df.index)
    for name, (fn, _) in FILTERS.items():
        if name == skip_filter:
            continue
        mask &= df.apply(lambda row: fn(row, cfg), axis=1)
    return df[mask].copy()


def compute_stats(df: pd.DataFrame) -> Dict[str, Any]:
    if df.empty:
        return {"trades": 0, "win_rate": 0.0, "avg_r": 0.0, "total_r": 0.0}
    trades   = len(df)
    win_rate = df["win"].astype(int).mean() * 100
    avg_r    = df["r_multiple"].mean()
    total_r  = df["r_multiple"].sum()
    return {
        "trades":    trades,
        "win_rate":  round(win_rate, 1),
        "avg_r":     round(avg_r, 3),
        "total_r":   round(total_r, 2),
    }

# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description="War Machine filter ablation test")
    parser.add_argument(
        "--results-dir", default="backtests/results",
        help="Directory containing *_trades.csv files (default: backtests/results)"
    )
    parser.add_argument(
        "--csv-out", default=None,
        help="Optional path to save results as CSV (e.g. ablation_results.csv)"
    )
    args = parser.parse_args()

    df_all = load_all_trades(args.results_dir)

    cfg = DEFAULT_CONFIG.copy()

    # Baseline — all filters ON
    df_base = apply_all_filters(df_all, cfg)
    base    = compute_stats(df_base)

    print("\n" + "=" * 75)
    print(" WAR MACHINE  —  FILTER ABLATION REPORT")
    print("=" * 75)
    print(f"{'Filter':<22} {'Trades':>7} {'WR%':>7} {'Avg R':>8} {'Total R':>9} {'ΔTrades':>8} {'ΔWR%':>7} {'ΔAvgR':>8} {'ΔTotalR':>9}")
    print("-" * 75)

    base_label = "BASELINE (all ON)"
    print(
        f"{base_label:<22} {base['trades']:>7} {base['win_rate']:>6.1f}%"
        f" {base['avg_r']:>+8.3f} {base['total_r']:>+9.2f}"
        f" {'—':>8} {'—':>7} {'—':>8} {'—':>9}"
    )
    print("-" * 75)

    rows_csv = [{"filter": base_label, **base,
                 "delta_trades": 0, "delta_wr": 0.0, "delta_avg_r": 0.0, "delta_total_r": 0.0}]

    for name, (fn, desc) in FILTERS.items():
        df_abl  = apply_all_filters(df_all, cfg, skip_filter=name)
        stats   = compute_stats(df_abl)

        d_trades  = stats["trades"]   - base["trades"]
        d_wr      = stats["win_rate"] - base["win_rate"]
        d_avg_r   = stats["avg_r"]    - base["avg_r"]
        d_total_r = stats["total_r"]  - base["total_r"]

        label = f"No {name}"
        print(
            f"{label:<22} {stats['trades']:>7} {stats['win_rate']:>6.1f}%"
            f" {stats['avg_r']:>+8.3f} {stats['total_r']:>+9.2f}"
            f" {d_trades:>+8} {d_wr:>+6.1f}% {d_avg_r:>+8.3f} {d_total_r:>+9.2f}"
        )

        rows_csv.append({
            "filter": label, **stats,
            "delta_trades": d_trades, "delta_wr": d_wr,
            "delta_avg_r": d_avg_r, "delta_total_r": d_total_r,
        })

    print("=" * 75)
    print("\nKey: positive Δ = removing this filter ADDS trades/performance")
    print("     negative Δ = this filter is PROTECTING performance\n")

    # --- No-filter baseline (everything off) for reference ---
    stats_none = compute_stats(df_all)
    d_trades  = stats_none["trades"]   - base["trades"]
    d_wr      = stats_none["win_rate"] - base["win_rate"]
    d_avg_r   = stats_none["avg_r"]    - base["avg_r"]
    d_total_r = stats_none["total_r"]  - base["total_r"]
    print(
        f"  Reference — NO filters at all:"
        f" {stats_none['trades']} trades | {stats_none['win_rate']:.1f}% WR"
        f" | {stats_none['avg_r']:+.3f} avg R | {stats_none['total_r']:+.2f} total R"
        f"  (Δ trades: {d_trades:+}, ΔTotalR: {d_total_r:+.2f})\n"
    )

    if args.csv_out:
        out_df = pd.DataFrame(rows_csv)
        out_df.to_csv(args.csv_out, index=False)
        print(f"Results saved to: {args.csv_out}\n")


if __name__ == "__main__":
    main()
