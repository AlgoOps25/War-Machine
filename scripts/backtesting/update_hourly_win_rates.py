#!/usr/bin/env python3
"""
Update HOURLY_WIN_RATES in entry_timing.py from real backtest output.

47.P4-2 (Apr 02 2026):
  Phase 4.C-10 zeroed out all HOURLY_WIN_RATES (sample_size=0) because the
  original values were fabricated. This script reads the hourly_win_rates
  dict produced by unified_production_backtest.py (--save flag) and patches
  the real computed rates back into app/validation/entry_timing.py.

Workflow:
  1. Run the backtest with --batch --save to generate JSON files:
       python scripts/backtesting/unified_production_backtest.py \\
           --batch --days 90 --save --output-dir backtests/results

  2. Run this script to aggregate and patch:
       python scripts/backtesting/update_hourly_win_rates.py \\
           --results-dir backtests/results

  3. Review the diff, commit.

Aggregation:
  - Loads all *.json files from the results dir.
  - Skips files that are JSON arrays (summary files) or lack hourly_win_rates.
  - Pools all trades across all tickers per hour bucket.
  - Computes win_rate = wins / total for each hour.
  - Only writes a rate if total trades >= MIN_SAMPLE (default 10).
  - Hours below MIN_SAMPLE keep (0.50, 0) so gating stays disabled
    for that hour until more data accumulates.

Patch strategy:
  - Reads entry_timing.py as text.
  - Finds the HOURLY_WIN_RATES block with a regex.
  - Replaces it with the newly computed block.
  - Writes back in-place (original backed up as entry_timing.py.bak).
"""

import sys
import re
import json
import shutil
import logging
import argparse
from pathlib import Path
from collections import defaultdict
from typing import Dict, Tuple

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)

# Minimum trades in a bucket before we trust the win rate.
# Below this, keep (0.50, 0) so MIN_SAMPLE_SIZE gate stays active.
MIN_SAMPLE = 10

# Path to the file we patch (relative to repo root).
ENTRY_TIMING_PATH = Path("app/validation/entry_timing.py")

# Regex that matches the entire HOURLY_WIN_RATES dict block.
# Anchored on the class-level assignment; stops at the closing brace.
HOURLY_BLOCK_RE = re.compile(
    r"(    HOURLY_WIN_RATES\s*=\s*\{)[^}]*(\})",
    re.DOTALL,
)


def load_results(results_dir: Path) -> Dict[int, Dict]:
    """
    Load all JSON result files and pool hourly win-rate data across tickers.

    Each qualifying file must be a JSON object (dict) containing a
    'hourly_win_rates' key mapping str(hour) -> {'wins': int, 'total': int}.

    Files that are JSON arrays (e.g. summary files) or lack the key are
    skipped with a warning.

    Returns pooled {hour: {'wins': int, 'total': int}} across all files.
    """
    pooled: Dict[int, Dict] = defaultdict(lambda: {"wins": 0, "total": 0})
    files = list(results_dir.glob("*.json"))

    if not files:
        logger.error(f"No JSON files found in {results_dir}")
        sys.exit(1)

    loaded = 0
    for fpath in files:
        try:
            data = json.loads(fpath.read_text())
        except Exception as e:
            logger.warning(f"Skipping {fpath.name}: parse error \u2014 {e}")
            continue

        # Skip JSON arrays (summary files, batch output, etc.)
        if not isinstance(data, dict):
            logger.debug(f"Skipping {fpath.name}: not a JSON object (type={type(data).__name__})")
            continue

        hourly = data.get("hourly_win_rates")
        if not hourly:
            logger.warning(f"Skipping {fpath.name}: no 'hourly_win_rates' key")
            continue

        ticker = data.get("ticker", fpath.stem)
        for hour_str, hdata in hourly.items():
            h = int(hour_str)
            pooled[h]["wins"]  += hdata.get("wins",  0)
            pooled[h]["total"] += hdata.get("total", 0)

        logger.info(
            f"  Loaded {fpath.name} ({ticker}): "
            f"{data.get('total_trades', '?')} trades"
        )
        loaded += 1

    if loaded == 0:
        logger.error(
            "No qualifying result files found. Ensure the backtest was run with "
            "--save and that each output file is a JSON object with 'hourly_win_rates'."
        )
        sys.exit(1)

    logger.info(f"Loaded {loaded} result file(s) from {results_dir} (skipped {len(files) - loaded})")
    return dict(pooled)


def compute_rates(
    pooled: Dict[int, Dict],
    min_sample: int,
) -> Dict[int, Tuple[float, int]]:
    """
    Convert pooled wins/totals into (win_rate, sample_size) tuples.

    Hours with total < min_sample get (0.50, 0) to keep gating disabled.
    """
    rates: Dict[int, Tuple[float, int]] = {}
    # Standard RTH hours 9-15
    for h in range(9, 16):
        d = pooled.get(h, {"wins": 0, "total": 0})
        total = d["total"]
        wins  = d["wins"]
        if total >= min_sample:
            wr = round(wins / total, 2)
            rates[h] = (wr, total)
            flag = "\u2705" if wr >= 0.65 else "\u26a0\ufe0f" if wr < 0.50 else "\U0001f7e1"
            logger.info(
                f"  Hour {h:02d}:xx  {wr:.0%}  "
                f"({wins}/{total} trades)  {flag}"
            )
        else:
            rates[h] = (0.50, 0)
            logger.info(
                f"  Hour {h:02d}:xx  insufficient data "
                f"({total} trades < {min_sample} min) \u2014 keeping (0.50, 0)"
            )
    return rates


def build_block(rates: Dict[int, Tuple[float, int]], min_sample: int) -> str:
    """
    Render the new HOURLY_WIN_RATES dict block as Python source.
    """
    hour_labels = {
        9:  "9:30-10:00",
        10: "10:00-11:00",
        11: "11:00-12:00",
        12: "12:00-13:00",
        13: "13:00-14:00",
        14: "14:00-15:00",
        15: "15:00-16:00",
    }
    lines = ["    HOURLY_WIN_RATES = {"]
    for h in range(9, 16):
        wr, n = rates[h]
        label = hour_labels.get(h, f"{h}:xx")
        if n == 0:
            comment = f"# {label}  - insufficient data (n<{min_sample})"
        else:
            pct = f"{wr:.0%}"
            comment = f"# {label}  - {pct} WR  ({n} trades)"
        lines.append(f"        {h}: ({wr:.2f}, {n}),  {comment}")
    lines.append("    }")
    return "\n".join(lines)


def patch_file(new_block: str, dry_run: bool = False) -> bool:
    """
    Replace the HOURLY_WIN_RATES block in entry_timing.py.
    Backs up the original to .bak before writing.
    Returns True if patched, False if pattern not found.
    """
    # Resolve relative to repo root (two levels up from this script)
    repo_root = Path(__file__).parent.parent.parent
    target = repo_root / ENTRY_TIMING_PATH

    if not target.exists():
        logger.error(f"Target file not found: {target}")
        return False

    original = target.read_text(encoding="utf-8")

    match = HOURLY_BLOCK_RE.search(original)
    if not match:
        logger.error(
            "Could not find HOURLY_WIN_RATES block in entry_timing.py. "
            "Pattern may have changed \u2014 update HOURLY_BLOCK_RE."
        )
        return False

    patched = HOURLY_BLOCK_RE.sub(new_block, original, count=1)

    if patched == original:
        logger.info("No change \u2014 HOURLY_WIN_RATES already matches computed rates.")
        return True

    if dry_run:
        logger.info("[DRY RUN] Would write the following block:")
        logger.info(new_block)
        return True

    bak = target.with_suffix(".py.bak")
    shutil.copy2(target, bak)
    logger.info(f"Backup written: {bak}")

    target.write_text(patched, encoding="utf-8")
    logger.info(f"Patched: {target}")
    return True


def main():
    parser = argparse.ArgumentParser(
        description="47.P4-2: Patch HOURLY_WIN_RATES in entry_timing.py "
                    "from real backtest JSON results."
    )
    parser.add_argument(
        "--results-dir",
        default="backtests/results",
        help="Directory containing backtest JSON files (default: backtests/results)",
    )
    parser.add_argument(
        "--min-sample",
        type=int,
        default=MIN_SAMPLE,
        help=f"Minimum trades per hour bucket before trusting the rate (default: {MIN_SAMPLE})",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print the new block without writing to disk",
    )
    args = parser.parse_args()

    # Use the parsed value as a plain local — no global mutation needed.
    min_sample = args.min_sample

    results_dir = Path(args.results_dir)
    if not results_dir.exists():
        logger.error(f"Results directory not found: {results_dir}")
        sys.exit(1)

    logger.info(f"Loading backtest results from: {results_dir}")
    pooled = load_results(results_dir)

    logger.info("Computing hourly win rates:")
    rates = compute_rates(pooled, min_sample)

    new_block = build_block(rates, min_sample)
    logger.info(f"New HOURLY_WIN_RATES block:\n{new_block}")

    ok = patch_file(new_block, dry_run=args.dry_run)
    if not ok:
        sys.exit(1)

    if not args.dry_run:
        logger.info("\nDone. Next steps:")
        logger.info("  1. Review the diff: git diff app/validation/entry_timing.py")
        logger.info("  2. Run tests:       python -m pytest tests/ -q")
        logger.info("  3. Commit:          git add app/validation/entry_timing.py && git commit -m '47.P4-2: wire real HOURLY_WIN_RATES from backtest'")
        logger.info("  4. Update registry: mark 47.P4-2 \u2705 in docs/AUDIT_REGISTRY.md")


if __name__ == "__main__":
    main()
