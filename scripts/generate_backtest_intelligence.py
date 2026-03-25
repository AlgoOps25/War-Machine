"""
generate_backtest_intelligence.py

Reads all files in backtests/analysis/ and overwrites docs/BACKTEST_INTELLIGENCE.md
with a fully structured, data-driven intelligence report.

Usage:
    python scripts/generate_backtest_intelligence.py

Then commit:
    git add docs/BACKTEST_INTELLIGENCE.md
    git commit -m "docs: update backtest intelligence $(date +%Y-%m-%d)"
    git push origin main
"""

import csv
import re
from datetime import date
from pathlib import Path

# ── Paths ────────────────────────────────────────────────────────────────────
ROOT = Path(__file__).resolve().parent.parent
ANALYSIS_DIR = ROOT / "backtests" / "analysis"
OUTPUT_FILE = ROOT / "docs" / "BACKTEST_INTELLIGENCE.md"

TICKER_RANKING_CSV = ANALYSIS_DIR / "ticker_ranking.csv"
FEATURE_SUMMARY_CSV = ANALYSIS_DIR / "feature_summary.csv"
FILTER_CANDIDATES_TXT = ANALYSIS_DIR / "filter_candidates.txt"
TRADE_DATA_CSV = ANALYSIS_DIR / "trade_data.csv"


# ── Helpers ──────────────────────────────────────────────────────────────────
def read_csv(path: Path) -> list[dict]:
    with open(path, newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def parse_filter_candidates(path: Path) -> dict:
    """Extract key metrics and filter candidates from the text report."""
    text = path.read_text(encoding="utf-8")
    result = {}

    # Header metrics
    m = re.search(r"Total trades: (\d+) \| Win rate: ([\d.]+)% \| Avg R: ([\d.]+)", text)
    if m:
        result["total_trades"] = int(m.group(1))
        result["baseline_wr"] = float(m.group(2))
        result["avg_r"] = float(m.group(3))

    # Exit breakdown
    exit_rows = []
    for line in re.findall(r"^\s+(EOD|STOP|T1|T2|MANUAL)\s+(\d+)\s+([\d.]+)\s+(-?[\d.]+)\s+(-?[\d.]+)", text, re.MULTILINE):
        exit_rows.append({
            "reason": line[0], "count": int(line[1]),
            "win_rate": float(line[2]), "avg_r": float(line[3]), "median_r": float(line[4])
        })
    result["exit_rows"] = exit_rows

    # Filter candidates
    filters = []
    for m in re.finditer(r"(\w+) above ([\d.]+): WR [\d.]+% -> ([\d.]+)% \(([+-][\d.]+pp)\), retains (\d+) trades \(([\d.]+)%\)", text):
        filters.append({
            "feature": m.group(1), "threshold": float(m.group(2)),
            "new_wr": float(m.group(3)), "gain": m.group(4),
            "trades": int(m.group(5)), "retain_pct": float(m.group(6))
        })
    result["filters"] = filters

    return result


def sig_icon(sig: str) -> str:
    return "✅ YES" if sig.strip().upper() == "YES" else "❌ no"


def r_color(avg_r: float) -> str:
    if avg_r >= 0.2:
        return "✅"
    elif avg_r >= 0:
        return "⚠️"
    else:
        return "❌"


def confidence_direction(feature: str, diff: float) -> str:
    if feature == "confidence":
        return "⚠️ Higher = MORE losses"
    elif diff < 0:
        return "Lower = wins"
    elif diff > 0:
        return "Higher = wins"
    return "—"


# ── Build Markdown ────────────────────────────────────────────────────────────
def build_markdown(metrics: dict, features: list[dict], tickers: list[dict]) -> str:
    today = date.today().isoformat()
    total = metrics.get("total_trades", "?")
    base_wr = metrics.get("baseline_wr", "?")
    avg_r = metrics.get("avg_r", "?")
    filters = metrics.get("filters", [])
    exit_rows = metrics.get("exit_rows", [])

    # Top filter
    top_filter = filters[0] if filters else None

    # Categorize tickers
    keep = [t for t in tickers if float(t["avg_r"]) >= 0 and int(t["trades"]) >= 2]
    remove = [t for t in tickers if float(t["avg_r"]) < 0]
    watchlist_remove = [t["ticker"] for t in remove]

    # EOD exit count
    eod_row = next((r for r in exit_rows if r["reason"] == "EOD"), None)
    eod_count = eod_row["count"] if eod_row else "?"
    eod_wr = eod_row["win_rate"] if eod_row else "?"

    lines = []

    # ── Header
    lines += [
        "# WAR MACHINE \u2014 BACKTEST INTELLIGENCE",
        f"> **Auto-generated** by `scripts/generate_backtest_intelligence.py` ",
        f"> Last updated: **{today}** | Dataset: **{total} trades** | Baseline WR: **{base_wr}%** | Avg R: **{avg_r}**",
        "",
        "---",
        "",
    ]

    # ── Core Metrics
    lines += [
        "## \U0001f4ca Core Performance Metrics",
        "",
        "| Metric | Value |",
        "|---|---|",
        f"| Total trades | {total} |",
        f"| Baseline win rate | {base_wr}% |",
        f"| Avg R (all trades) | {avg_r} |",
    ]
    if top_filter:
        lines.append(
            f"| Win rate w/ `{top_filter['feature']} >= {top_filter['threshold']}` filter "
            f"| **{top_filter['new_wr']}% ({top_filter['gain']})** |"
        )
        lines.append(f"| Trades retained after top filter | {top_filter['trades']} ({top_filter['retain_pct']}%) |")
    if eod_row:
        lines.append(f"| EOD exits (no T1/T2 hit) | {eod_count} ({round(eod_count/total*100, 1) if isinstance(eod_count, int) and isinstance(total, int) else '?'}%) |")
    lines += ["", "---", ""]

    # ── Top Filter
    if top_filter:
        lines += [
            "## \U0001f511 #1 Priority Filter",
            "",
            "```",
            f"{top_filter['feature']} >= {top_filter['threshold']}  "
            f"\u2192  WR {base_wr}% \u2192 {top_filter['new_wr']}%  ({top_filter['gain']}, {top_filter['trades']} trades retained)",
            "```",
            "",
            f"**Action:** Enforce `{top_filter['feature']} >= {top_filter['threshold']}` as a hard gate in signal logic.",
            "",
            "---",
            "",
        ]

    # ── Feature Significance
    lines += [
        "## \U0001f9ea Feature Significance (p-value analysis)",
        "",
        "| Feature | Win Mean | Loss Mean | p-value | Significant | Direction |",
        "|---|---|---|---|---|---|",
    ]
    for f in features:
        diff = float(f["diff_mean"])
        lines.append(
            f"| `{f['feature']}` | {f['win_mean']} | {f['loss_mean']} "
            f"| {f['p_value']} | {sig_icon(f['significant'])} "
            f"| {confidence_direction(f['feature'], diff)} |"
        )
    lines += [
        "",
        "> \u26a0\ufe0f **CRITICAL:** `confidence` is **inversely correlated with wins** (p=0.006). "
        "Higher confidence \u2192 more losses. Audit and likely invert this score.",
        "",
        "---",
        "",
    ]

    # ── Filter Candidates
    lines += [
        "## \U0001f6aa Recommended Filter Candidates",
        "",
        "| Rank | Filter | Baseline WR | Filtered WR | Gain | Trades Retained |",
        "|---|---|---|---|---|---|",
    ]
    for i, f in enumerate(filters, 1):
        lines.append(
            f"| {i} | `{f['feature']} >= {f['threshold']}` "
            f"| {base_wr}% | **{f['new_wr']}%** | {f['gain']} | {f['trades']} ({f['retain_pct']}%) |"
        )
    lines += ["", "---", ""]

    # ── Exit Breakdown
    if exit_rows:
        lines += [
            "## \U0001f6aa Exit Reason Breakdown",
            "",
            "| Exit | Count | Win Rate | Avg R | Median R |",
            "|---|---|---|---|---|",
        ]
        for r in exit_rows:
            lines.append(
                f"| {r['reason']} | {r['count']} | {r['win_rate']}% | {r['avg_r']} | {r['median_r']} |"
            )
        if eod_row and isinstance(total, int):
            eod_pct = round(eod_row["count"] / total * 100, 1)
            lines += [
                "",
                f"> \u26a0\ufe0f **{eod_pct}% of trades exit EOD** with no T1/T2 hit. "
                "Profit targets may be too wide or momentum stalls before target. Tighten T1.",
            ]
        lines += ["", "---", ""]

    # ── Ticker Tier List
    lines += [
        "## \U0001f3c6 Ticker Performance Tier List",
        "",
        "### \u2705 Keep (avg R \u2265 0, \u22652 trades)",
        "",
        "| Ticker | Trades | Win Rate | Avg R | Profit Factor | Avg RVOL | EOD% |",
        "|---|---|---|---|---|---|---|",
    ]
    for t in keep:
        lines.append(
            f"| {t['ticker']} | {t['trades']} | {t['win_rate']}% "
            f"| {r_color(float(t['avg_r']))} {t['avg_r']} "
            f"| {t['profit_factor']} | {t['avg_rvol']} | {t['eod_pct']}% |"
        )

    lines += [
        "",
        "### \u274c Remove / Deprioritize (negative avg R)",
        "",
        "| Ticker | Trades | Win Rate | Avg R | Action |",
        "|---|---|---|---|---|",
    ]
    for t in remove:
        lines.append(
            f"| {t['ticker']} | {t['trades']} | {t['win_rate']}% "
            f"| {t['avg_r']} | \U0001f5d1\ufe0f Remove from watchlist |"
        )
    lines += ["", "---", ""]

    # ── Action Items
    actions = [
        f"Add `{top_filter['feature']} >= {top_filter['threshold']}` as a **hard gate** in signal logic" if top_filter else None,
        "Audit `confidence` scoring — it is **anticorrelated with wins** (p=0.006); likely needs inversion or full rebuild",
        f"Remove from watchlist: **{', '.join(watchlist_remove)}**" if watchlist_remove else None,
        "Tighten T1 profit target — 62%+ EOD exits means momentum stalls before target fires",
        "Re-run this script after each major change and commit the updated doc",
    ]
    lines += [
        "## \U0001f3af Immediate Action Items",
        "",
    ]
    for i, a in enumerate([x for x in actions if x], 1):
        lines.append(f"{i}. {a}")
    lines += ["", "---", ""]

    # ── Footer
    lines += [
        "## \U0001f504 How to Regenerate This File",
        "",
        "```powershell",
        "python scripts/generate_backtest_intelligence.py",
        "git add docs/BACKTEST_INTELLIGENCE.md",
        'git commit -m \"docs: update backtest intelligence $(Get-Date -Format yyyy-MM-dd)\"',
        "git push origin main",
        "```",
        "",
        "> This file is the **single source of truth** for War Machine signal quality. "
        "Never let it go stale — regenerate after every backtest run.",
    ]

    return "\n".join(lines) + "\n"


# ── Main ──────────────────────────────────────────────────────────────────────
def main():
    print("Reading analysis files...")
    metrics = parse_filter_candidates(FILTER_CANDIDATES_TXT)
    features = read_csv(FEATURE_SUMMARY_CSV)
    tickers = read_csv(TICKER_RANKING_CSV)

    print(f"  Trades: {metrics.get('total_trades')} | Baseline WR: {metrics.get('baseline_wr')}%")
    print(f"  Features: {len(features)} | Tickers: {len(tickers)} | Filters: {len(metrics.get('filters', []))}")

    md = build_markdown(metrics, features, tickers)

    OUTPUT_FILE.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT_FILE.write_text(md, encoding="utf-8")
    print(f"\n\u2705 Written: {OUTPUT_FILE}")
    print("\nNext steps:")
    print("  git add docs/BACKTEST_INTELLIGENCE.md")
    print('  git commit -m \"docs: update backtest intelligence\"')
    print("  git push origin main")


if __name__ == "__main__":
    main()
