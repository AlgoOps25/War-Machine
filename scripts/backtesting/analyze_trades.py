"""
analyze_trades.py

Loads all per-ticker *_trades.csv files from backtests/results/,
merges them into a single DataFrame, and performs feature analysis
to identify which conditions separate wins from losses.

Outputs:
  - backtests/analysis/feature_summary.csv     (win vs loss means per feature)
  - backtests/analysis/filter_candidates.txt   (recommended hard filters)
  - backtests/analysis/trade_data.csv          (full merged dataset)

Usage:
  python scripts/backtesting/analyze_trades.py
  python scripts/backtesting/analyze_trades.py --results backtests/results --out backtests/analysis
"""

import argparse
import math
from pathlib import Path

import pandas as pd
from scipy.stats import mannwhitneyu


# ── CLI ───────────────────────────────────────────────────────────────────────
def parse_args():
    p = argparse.ArgumentParser()
    p.add_argument("--results", default="backtests/results",
                   help="Folder containing *_trades.csv files")
    p.add_argument("--out", default="backtests/analysis",
                   help="Output folder for reports")
    p.add_argument("--min-trades", type=int, default=2,
                   help="Minimum trades per ticker to include (default 2)")
    return p.parse_args()


# ── LOAD ──────────────────────────────────────────────────────────────────────
def load_trades(results_dir: Path, min_trades: int) -> pd.DataFrame:
    frames = []
    for csv in sorted(results_dir.glob("*_trades.csv")):
        df = pd.read_csv(csv)
        if len(df) >= min_trades:
            frames.append(df)
    if not frames:
        raise FileNotFoundError(f"No *_trades.csv files found in {results_dir}")
    df = pd.concat(frames, ignore_index=True)
    print(f"Loaded {len(df)} trades from {len(frames)} tickers")
    return df


# ── FEATURE ENGINEERING ───────────────────────────────────────────────────────
def engineer_features(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()

    # Entry timing
    df["entry_minute_abs"] = df["entry_hour"] * 60 + df["entry_minute"]
    df["minutes_from_open"] = df["entry_minute_abs"] - (9 * 60 + 30)

    # OR characteristics
    df["or_range_pct"] = df["or_range_pct"].astype(float)
    df["or_range_wide"] = (df["or_range_pct"] >= 3.0).astype(int)

    # FVG quality
    df["fvg_size_pct"] = df["fvg_size_pct"].astype(float)

    # RVOL
    df["rvol"] = df["rvol"].astype(float)
    df["rvol_strong"] = (df["rvol"] >= 1.5).astype(int)

    # Grade numeric
    grade_map = {"A+": 2, "A": 1, "B": 0}
    df["grade_num"] = df["grade"].map(grade_map).fillna(0)

    # Entry hour bucket
    df["early_entry"] = (df["entry_hour"] == 9).astype(int)

    # R multiple bins
    df["r_bucket"] = pd.cut(
        df["r_multiple"],
        bins=[-99, -1, 0, 0.5, 1.0, 2.0, 99],
        labels=["full_stop", "partial_loss", "scratch", "small_win", "t1", "t2+"]
    )

    return df


# ── FEATURE ANALYSIS ──────────────────────────────────────────────────────────
NUMERIC_FEATURES = [
    "or_range_pct",
    "fvg_size_pct",
    "rvol",
    "confidence",
    "grade_num",
    "minutes_from_open",
    "entry_hour",
]


def analyze_features(df: pd.DataFrame) -> pd.DataFrame:
    wins = df[df["win"] == 1]
    losses = df[df["win"] == 0]

    rows = []
    for feat in NUMERIC_FEATURES:
        if feat not in df.columns:
            continue
        w = wins[feat].dropna()
        l = losses[feat].dropna()
        try:
            stat, p = mannwhitneyu(w, l, alternative="two-sided")
        except Exception:
            p = float("nan")

        rows.append({
            "feature": feat,
            "win_mean": round(w.mean(), 3),
            "loss_mean": round(l.mean(), 3),
            "win_median": round(w.median(), 3),
            "loss_median": round(l.median(), 3),
            "diff_mean": round(w.mean() - l.mean(), 3),
            "p_value": round(p, 4) if not math.isnan(p) else None,
            "significant": "YES" if p < 0.10 else "no",
        })

    return pd.DataFrame(rows).sort_values("p_value")


# ── THRESHOLD SCAN ────────────────────────────────────────────────────────────
def scan_thresholds(df: pd.DataFrame) -> list[dict]:
    """
    For each numeric feature, scan thresholds and find the cutoff
    that maximises the win rate improvement while retaining >= 30% of trades.
    """
    candidates = []
    total = len(df)

    for feat in ["or_range_pct", "rvol", "fvg_size_pct", "minutes_from_open"]:
        if feat not in df.columns:
            continue
        col = df[feat].dropna()
        percentiles = [10, 20, 30, 40, 50, 60, 70, 80]
        best = None

        for pct in percentiles:
            thresh = col.quantile(pct / 100)
            for direction, subset in [("above", df[df[feat] >= thresh]),
                                      ("below", df[df[feat] < thresh])]:
                if len(subset) < 5:
                    continue
                wr = subset["win"].mean()
                retain_pct = len(subset) / total
                if retain_pct < 0.30:
                    continue
                baseline_wr = df["win"].mean()
                improvement = wr - baseline_wr
                if improvement > 0.03:
                    if best is None or improvement > best["improvement_pp"] / 100:
                        best = {
                            "feature": feat,
                            "direction": direction,
                            "threshold": round(thresh, 3),
                            "win_rate": round(wr * 100, 1),
                            "baseline_wr": round(baseline_wr * 100, 1),
                            "improvement_pp": round(improvement * 100, 1),
                            "trades_retained": len(subset),
                            "retain_pct": round(retain_pct * 100, 1),
                        }
        if best:
            candidates.append(best)

    return sorted(candidates, key=lambda x: -x["improvement_pp"])


# ── EXIT REASON BREAKDOWN ─────────────────────────────────────────────────────
def exit_breakdown(df: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for reason, grp in df.groupby("exit_reason"):
        rows.append({
            "exit_reason": reason,
            "count": len(grp),
            "win_rate": round(grp["win"].mean() * 100, 1),
            "avg_r": round(grp["r_multiple"].mean(), 3),
            "median_r": round(grp["r_multiple"].median(), 3),
        })
    return pd.DataFrame(rows).sort_values("count", ascending=False)


# ── TICKER RANKING ────────────────────────────────────────────────────────────
def ticker_ranking(df: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for ticker, grp in df.groupby("ticker"):
        wins_r = grp[grp["win"] == 1]["r_multiple"]
        loss_r = grp[grp["win"] == 0]["r_multiple"]
        pf = (wins_r.sum() / abs(loss_r.sum())) if loss_r.sum() != 0 else float("inf")
        rows.append({
            "ticker": ticker,
            "trades": len(grp),
            "win_rate": round(grp["win"].mean() * 100, 1),
            "avg_r": round(grp["r_multiple"].mean(), 3),
            "profit_factor": round(pf, 2) if pf != float("inf") else 999,
            "avg_or_range_pct": round(grp["or_range_pct"].mean(), 2),
            "avg_rvol": round(grp["rvol"].mean(), 2),
            "eod_pct": round((grp["exit_reason"] == "EOD").mean() * 100, 1),
        })
    return pd.DataFrame(rows).sort_values("avg_r", ascending=False)


# ── REPORT ────────────────────────────────────────────────────────────────────
def write_report(out_dir: Path, df: pd.DataFrame, feat_df: pd.DataFrame,
                 candidates: list, exit_df: pd.DataFrame, ticker_df: pd.DataFrame):
    out_dir.mkdir(parents=True, exist_ok=True)

    df.to_csv(out_dir / "trade_data.csv", index=False)
    feat_df.to_csv(out_dir / "feature_summary.csv", index=False)
    ticker_df.to_csv(out_dir / "ticker_ranking.csv", index=False)

    lines = []
    lines.append("=" * 70)
    lines.append("WAR MACHINE — TRADE ANALYSIS REPORT")
    lines.append(f"Total trades: {len(df)} | Win rate: {df['win'].mean()*100:.1f}% | "
                 f"Avg R: {df['r_multiple'].mean():.3f}")
    lines.append("=" * 70)

    lines.append("\n── EXIT REASON BREAKDOWN ──")
    lines.append(exit_df.to_string(index=False))

    lines.append("\n── FEATURE SEPARATION (wins vs losses) ──")
    lines.append(feat_df.to_string(index=False))

    lines.append("\n── FILTER CANDIDATES (threshold scan) ──")
    if candidates:
        for c in candidates:
            lines.append(
                f"  {c['feature']} {c['direction']} {c['threshold']}: "
                f"WR {c['baseline_wr']}% → {c['win_rate']}% "
                f"(+{c['improvement_pp']}pp), "
                f"retains {c['trades_retained']} trades ({c['retain_pct']}%)"
            )
    else:
        lines.append("  No strong single-feature filters found — try combinations.")

    lines.append("\n── TICKER RANKING (by avg R) ──")
    lines.append(ticker_df.to_string(index=False))

    report_path = out_dir / "filter_candidates.txt"
    report_path.write_text("\n".join(lines))
    print(f"\nReport written to {report_path}")
    print("\n" + "\n".join(lines))


# ── MAIN ──────────────────────────────────────────────────────────────────────
def main():
    args = parse_args()
    results_dir = Path(args.results)
    out_dir = Path(args.out)

    df = load_trades(results_dir, args.min_trades)
    df = engineer_features(df)

    feat_df = analyze_features(df)
    candidates = scan_thresholds(df)
    exit_df = exit_breakdown(df)
    ticker_df = ticker_ranking(df)

    write_report(out_dir, df, feat_df, candidates, exit_df, ticker_df)


if __name__ == "__main__":
    main()
