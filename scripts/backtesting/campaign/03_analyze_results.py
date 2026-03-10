#!/usr/bin/env python3
"""
03_analyze_results.py  —  Campaign Results Analyzer
====================================================
Reads campaign_results.db and produces:

  1. Top-20 leaderboard (ranked by score = win_rate x avg_r)
  2. Dimension heatmaps (which single-param values win most)
  3. Best combo per direction (call_only / put_only / both)
  4. Minimum-overfitting check (trade count filter)
  5. Ready-to-paste config dict for config.py

Usage:
    python scripts/backtesting/campaign/03_analyze_results.py
    python scripts/backtesting/campaign/03_analyze_results.py --top 30 --min-trades 20
    python scripts/backtesting/campaign/03_analyze_results.py --min-wr 0.70
"""

import sys
import os
import argparse
import sqlite3
from datetime import datetime
from collections import defaultdict
from typing import Dict, List

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '../../..')))

DB_DEFAULT = os.path.join(os.path.dirname(__file__), 'campaign_results.db')


def open_db(path: str) -> sqlite3.Connection:
    if not os.path.exists(path):
        print(f'❌  campaign_results.db not found at: {path}')
        print('    Run 02_run_campaign.py first.')
        sys.exit(1)
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    return conn


def fetch_results(conn: sqlite3.Connection, min_trades: int, min_wr: float) -> List[sqlite3.Row]:
    cur = conn.cursor()
    cur.execute("""
        SELECT *
        FROM results
        WHERE total_trades >= ?
          AND win_rate     >= ?
        ORDER BY score DESC, win_rate DESC, avg_r DESC
    """, (min_trades, min_wr))
    return cur.fetchall()


def print_leaderboard(rows: List[sqlite3.Row], top_n: int):
    print()
    print('='*100)
    print(f'  TOP {top_n} COMBOS  (ranked by score = win_rate × avg_r)')
    print('='*100)
    print(
        f"{'#':>3}  {'WR':>6}  {'AvgR':>6}  {'Score':>6}  {'Trades':>6}  "
        f"{'BOS%':>5}  {'TF':<10}  {'VWAP':<12}  {'RVOL':>5}  "
        f"{'MFI':>4}  {'OBV':>4}  {'Session':<10}  {'Dir':<10}"
    )
    print('-'*100)

    for rank, r in enumerate(rows[:top_n], 1):
        bos_pct = f"{r['bos_strength']*100:.2f}%"
        print(
            f"{rank:>3}  {r['win_rate']:>6.1%}  {r['avg_r']:>+6.2f}  "
            f"{r['score']:>6.4f}  {r['total_trades']:>6}  "
            f"{bos_pct:>5}  {r['tf_confirm']:<10}  {r['vwap_zone']:<12}  "
            f"{r['rvol_min']:>5.1f}  {r['mfi_min']:>4}  {r['obv_bars']:>4}  "
            f"{r['session']:<10}  {r['direction']:<10}"
        )


def dimension_heatmap(rows: List[sqlite3.Row]):
    """For each parameter axis, show the average score per value."""
    dims = [
        'bos_strength','tf_confirm','vwap_zone','rvol_min',
        'mfi_min','obv_bars','session','direction',
    ]
    print()
    print('='*72)
    print('  DIMENSION HEATMAP  (avg score per parameter value)')
    print('='*72)

    for dim in dims:
        bucket: Dict[str, List[float]] = defaultdict(list)
        for r in rows:
            key = str(r[dim])
            bucket[key].append(r['score'])

        sorted_vals = sorted(bucket.items(), key=lambda x: -sum(x[1])/len(x[1]))
        print(f'\n  {dim}')
        print(f"  {'Value':<14} {'AvgScore':>9}  {'AvgWR':>7}  {'Count':>6}")
        for val, scores in sorted_vals:
            avg_score = sum(scores) / len(scores)
            # Also grab avg win_rate for this dim value
            wrs = [r['win_rate'] for r in rows if str(r[dim]) == val]
            avg_wr = sum(wrs) / len(wrs) if wrs else 0
            bar_len = int(avg_score * 100)
            bar = '█' * min(bar_len, 40)
            print(f"  {val:<14} {avg_score:>9.4f}  {avg_wr:>7.1%}  {len(scores):>6}  {bar}")


def best_per_direction(rows: List[sqlite3.Row]):
    dirs = ['call_only', 'put_only', 'both']
    print()
    print('='*72)
    print('  BEST COMBO PER DIRECTION')
    print('='*72)
    for d in dirs:
        subset = [r for r in rows if r['direction'] == d]
        if not subset:
            print(f'\n  {d}: no qualifying combos')
            continue
        best = subset[0]  # already sorted by score
        print(f'\n  {d.upper()}')
        print(f"  Win Rate : {best['win_rate']:.1%}")
        print(f"  Avg R    : {best['avg_r']:+.2f}")
        print(f"  Score    : {best['score']:.4f}")
        print(f"  Trades   : {best['total_trades']}")
        print(f"  Params   : BOS={best['bos_strength']*100:.2f}%  TF={best['tf_confirm']}  "
              f"VWAP={best['vwap_zone']}  RVOL={best['rvol_min']}  "
              f"MFI={best['mfi_min']}  OBV={best['obv_bars']}  Session={best['session']}")


def generate_config_dict(best: sqlite3.Row):
    """Print a ready-to-paste config dict from the top result."""
    print()
    print('='*72)
    print('  CHAMPION CONFIG  (paste into utils/config.py)')
    print('='*72)
    print(f"""
# ── Backtest Campaign Champion  ({datetime.now().strftime('%Y-%m-%d')}) ──────────────────
# Win Rate  : {best['win_rate']:.1%}
# Avg R     : {best['avg_r']:+.2f}
# Score     : {best['score']:.4f}
# Trades    : {best['total_trades']}
# Tickers   : {best['tickers_used']}

BACKTEST_CHAMPION = {{
    'bos_strength' : {best['bos_strength']},       # min BOS % above swing
    'tf_confirm'   : '{best['tf_confirm']}',   # timeframe confirmation tier
    'vwap_zone'    : '{best['vwap_zone']}',    # VWAP zone requirement
    'rvol_min'     : {best['rvol_min']},       # minimum relative volume
    'mfi_min'      : {best['mfi_min']},        # MFI floor (0 = off)
    'obv_bars'     : {best['obv_bars']},       # OBV rising bars (0 = off)
    'session'      : '{best['session']}',      # session window
    'direction'    : '{best['direction']}',    # signal direction
}}
""")


def main():
    parser = argparse.ArgumentParser(description='Analyze backtest campaign results')
    parser.add_argument('--db',         type=str,   default=DB_DEFAULT)
    parser.add_argument('--top',        type=int,   default=20)
    parser.add_argument('--min-trades', type=int,   default=15)
    parser.add_argument('--min-wr',     type=float, default=0.0)
    args = parser.parse_args()

    conn = open_db(args.db)

    print('='*72)
    print('WAR MACHINE — CAMPAIGN RESULTS ANALYZER')
    print('='*72)

    # Summary stats
    cur = conn.cursor()
    cur.execute('SELECT COUNT(*) AS n, MAX(win_rate) AS best_wr, MAX(score) AS best_score FROM results')
    meta = cur.fetchone()
    print(f'  Total combos in DB : {meta["n"]:,}')
    print(f'  Best win rate      : {meta["best_wr"]:.1%}')
    print(f'  Best score         : {meta["best_score"]:.4f}')

    rows = fetch_results(conn, args.min_trades, args.min_wr)
    print(f'  Qualifying combos  : {len(rows):,}  '
          f'(trades>={args.min_trades}, WR>={args.min_wr:.0%})')

    if not rows:
        print('\n⚠️   No combos meet the filter criteria.')
        print('    Try lowering --min-trades or --min-wr.')
        conn.close()
        return

    print_leaderboard(rows, args.top)
    dimension_heatmap(rows)
    best_per_direction(rows)
    generate_config_dict(rows[0])

    conn.close()
    print()
    print('✅  Analysis complete.')


if __name__ == '__main__':
    main()
