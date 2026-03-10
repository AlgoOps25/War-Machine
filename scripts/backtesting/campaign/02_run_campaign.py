#!/usr/bin/env python3
"""
02_run_campaign.py  —  Full Backtest Campaign Engine
=====================================================
Exhaustively tests every meaningful combination of indicators against
the 90-day cached bar data in market_memory.db.

Indicator axes tested
---------------------
  bos_strength    : 0.10, 0.15, 0.18, 0.22, 0.30  (% break above swing)
  tf_confirm      : 1m, 3m, 5m, 5m+3m, 5m+3m+1m   (timeframe confirmation tier)
  vwap_zone       : above_1sd, above_vwap, none
  rvol_min        : 2.0, 3.0, 4.0, 5.0
  mfi_min         : 50, 55, 60, none
  obv_bars        : 3, 5, none
  session         : or_only, early, all_day
  direction       : call_only, put_only, both

Total combinations : ~97,200
Expected runtime   : 10-25 minutes on cached data

Output
------
  scripts/backtesting/campaign/campaign_results.db   (SQLite)

Usage
------
  python scripts/backtesting/campaign/02_run_campaign.py
  python scripts/backtesting/campaign/02_run_campaign.py --tickers AAPL,NVDA,TSLA
  python scripts/backtesting/campaign/02_run_campaign.py --days 60 --min-trades 10
"""

import sys
import os
import argparse
import sqlite3
import json
import time
from datetime import datetime, timedelta, date
from zoneinfo import ZoneInfo
from itertools import product
from typing import Dict, List, Optional, Tuple

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '../../..')))

ET = ZoneInfo('America/New_York')

# ═══════════════════════════════════════════════════════════════════════════
# PARAMETER GRID
# ═══════════════════════════════════════════════════════════════════════════

GRID = {
    'bos_strength': [0.0010, 0.0015, 0.0018, 0.0022, 0.0030],  # as decimal
    'tf_confirm'  : ['1m', '3m', '5m', '5m_3m', '5m_3m_1m'],
    'vwap_zone'   : ['above_1sd', 'above_vwap', 'none'],
    'rvol_min'    : [2.0, 3.0, 4.0, 5.0],
    'mfi_min'     : [50, 55, 60, 0],        # 0 = disabled
    'obv_bars'    : [3, 5, 0],              # 0 = disabled
    'session'     : ['or_only', 'early', 'all_day'],
    'direction'   : ['call_only', 'put_only', 'both'],
}

# ═══════════════════════════════════════════════════════════════════════════
# DATABASE HELPERS
# ═══════════════════════════════════════════════════════════════════════════

def open_source_db(db_path: str = 'market_memory.db') -> sqlite3.Connection:
    if not os.path.exists(db_path):
        alt = os.path.join(os.path.dirname(__file__), '../../../market_memory.db')
        if os.path.exists(alt):
            db_path = alt
        else:
            raise FileNotFoundError(
                f'market_memory.db not found. Run the main scanner first.'
            )
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    return conn


def open_results_db(out_path: str) -> sqlite3.Connection:
    conn = sqlite3.connect(out_path)
    conn.execute('PRAGMA journal_mode=WAL')
    conn.execute('PRAGMA synchronous=NORMAL')
    conn.execute("""
        CREATE TABLE IF NOT EXISTS results (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            combo_key       TEXT NOT NULL,
            bos_strength    REAL,
            tf_confirm      TEXT,
            vwap_zone       TEXT,
            rvol_min        REAL,
            mfi_min         INTEGER,
            obv_bars        INTEGER,
            session         TEXT,
            direction       TEXT,
            total_trades    INTEGER,
            wins            INTEGER,
            losses          INTEGER,
            win_rate        REAL,
            avg_r           REAL,
            total_r         REAL,
            score           REAL,
            tickers_used    TEXT,
            created_at      TEXT
        )
    """)
    conn.execute("CREATE INDEX IF NOT EXISTS idx_score ON results(score DESC)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_win_rate ON results(win_rate DESC)")
    conn.commit()
    return conn


def load_all_bars(src_conn: sqlite3.Connection, days_back: int = 90) -> Dict[str, List[Dict]]:
    """Load all cached bars into memory once — grouped by ticker."""
    cutoff = (datetime.now(ET) - timedelta(days=days_back)).strftime('%Y-%m-%d')

    # detect bar table
    cur = src_conn.cursor()
    cur.execute("SELECT name FROM sqlite_master WHERE type='table'")
    tables = {r[0] for r in cur.fetchall()}
    bar_table = next((t for t in ('intraday_bars','bars','candles','ohlcv') if t in tables), None)
    if not bar_table:
        raise RuntimeError('No bar table found in market_memory.db')

    cur.execute(f"""
        SELECT ticker, datetime, open, high, low, close, volume
        FROM {bar_table}
        WHERE datetime >= ?
        ORDER BY ticker, datetime
    """, (cutoff,))

    ticker_bars: Dict[str, List[Dict]] = {}
    for row in cur.fetchall():
        t = row[0]
        dt_raw = row[1]
        if isinstance(dt_raw, str):
            try:
                dt = datetime.fromisoformat(dt_raw).replace(tzinfo=None)
            except Exception:
                continue
        else:
            dt = dt_raw

        bar = {
            'dt'    : dt,
            'open'  : float(row[2]),
            'high'  : float(row[3]),
            'low'   : float(row[4]),
            'close' : float(row[5]),
            'volume': int(row[6]),
        }
        ticker_bars.setdefault(t, []).append(bar)

    print(f'  Loaded {sum(len(v) for v in ticker_bars.values()):,} bars '
          f'across {len(ticker_bars)} tickers (since {cutoff})')
    return ticker_bars


# ═══════════════════════════════════════════════════════════════════════════
# INDICATOR CALCULATIONS
# ═══════════════════════════════════════════════════════════════════════════

def calc_vwap_bands(bars: List[Dict]) -> Tuple[float, float, float]:
    """Returns (vwap, upper_1sd, lower_1sd) for the session bars provided."""
    if not bars:
        return 0.0, 0.0, 0.0
    tp_vol  = sum(((b['high']+b['low']+b['close'])/3) * b['volume'] for b in bars)
    tot_vol = sum(b['volume'] for b in bars)
    vwap    = tp_vol / tot_vol if tot_vol else bars[-1]['close']

    variance = sum(
        (((b['high']+b['low']+b['close'])/3) - vwap)**2 * b['volume']
        for b in bars
    ) / tot_vol if tot_vol else 0
    sd = variance**0.5
    return vwap, vwap + sd, vwap - sd


def calc_mfi(bars: List[Dict], period: int = 14) -> float:
    if len(bars) < period + 1:
        return 50.0
    recent = bars[-(period+1):]
    tps    = [(b['high']+b['low']+b['close'])/3 for b in recent]
    mfs    = [tps[i]*recent[i]['volume'] for i in range(len(recent))]
    pos    = sum(mfs[i] for i in range(1, len(mfs)) if tps[i] > tps[i-1])
    neg    = sum(mfs[i] for i in range(1, len(mfs)) if tps[i] < tps[i-1])
    if neg == 0:
        return 100.0
    return 100 - (100 / (1 + pos/neg))


def calc_obv_trend(bars: List[Dict], lookback: int = 5) -> float:
    """Returns slope of OBV over last `lookback` bars. Positive = rising."""
    if len(bars) < lookback + 1:
        return 0.0
    recent = bars[-(lookback+1):]
    obv = 0.0
    obvs = []
    for i in range(1, len(recent)):
        if recent[i]['close'] > recent[i-1]['close']:
            obv += recent[i]['volume']
        elif recent[i]['close'] < recent[i-1]['close']:
            obv -= recent[i]['volume']
        obvs.append(obv)
    if len(obvs) < 2:
        return 0.0
    return obvs[-1] - obvs[0]   # positive = rising OBV


def calc_rvol(bars: List[Dict], lookback: int = 20) -> float:
    if len(bars) < lookback + 1:
        return 1.0
    avg = sum(b['volume'] for b in bars[-(lookback+1):-1]) / lookback
    if avg == 0:
        return 1.0
    return bars[-1]['volume'] / avg


def calc_atr(bars: List[Dict], period: int = 14) -> float:
    if len(bars) < period + 1:
        return bars[-1]['close'] * 0.01 if bars else 1.0
    trs = [
        max(bars[i]['high'] - bars[i]['low'],
            abs(bars[i]['high'] - bars[i-1]['close']),
            abs(bars[i]['low']  - bars[i-1]['close']))
        for i in range(1, len(bars))
    ]
    return sum(trs[-period:]) / period


# ═══════════════════════════════════════════════════════════════════════════
# SIGNAL DETECTION
# ═══════════════════════════════════════════════════════════════════════════

def is_or_session(dt: datetime) -> bool:
    """True if bar is within Opening Range (9:30–10:00 ET)."""
    return dt.hour == 9 and 30 <= dt.minute < 60


def is_early_session(dt: datetime) -> bool:
    """True if bar is 9:30–11:00 ET."""
    return (dt.hour == 9 and dt.minute >= 30) or dt.hour == 10


def is_rth(dt: datetime) -> bool:
    """Regular trading hours 9:30–16:00 ET."""
    if dt.hour < 9 or (dt.hour == 9 and dt.minute < 30):
        return False
    if dt.hour >= 16:
        return False
    return True


def compress_to_tf(bars_1m: List[Dict], tf_minutes: int) -> List[Dict]:
    """Compress 1-minute bars into N-minute bars."""
    if tf_minutes == 1:
        return bars_1m
    compressed = []
    bucket: List[Dict] = []
    for b in bars_1m:
        bucket.append(b)
        if len(bucket) >= tf_minutes:
            compressed.append({
                'dt'    : bucket[0]['dt'],
                'open'  : bucket[0]['open'],
                'high'  : max(x['high']  for x in bucket),
                'low'   : min(x['low']   for x in bucket),
                'close' : bucket[-1]['close'],
                'volume': sum(x['volume'] for x in bucket),
            })
            bucket = []
    return compressed


def detect_bos(bars: List[Dict], idx: int, strength_threshold: float,
               lookback: int = 20) -> Optional[str]:
    """
    Returns 'bull', 'bear', or None.
    BOS = close breaks beyond recent swing high/low by >= strength_threshold.
    """
    if idx < lookback or idx >= len(bars):
        return None
    window = bars[idx-lookback:idx]
    swing_high = max(b['high']  for b in window)
    swing_low  = min(b['low']   for b in window)
    c = bars[idx]['close']

    if c > swing_high:
        if (c - swing_high) / swing_high >= strength_threshold:
            return 'bull'
    elif c < swing_low:
        if (swing_low - c) / swing_low >= strength_threshold:
            return 'bear'
    return None


def detect_fvg(bars: List[Dict], idx: int) -> Optional[str]:
    """
    Returns 'bull', 'bear', or None.
    Bullish FVG : bars[idx-2].high < bars[idx].low  (gap up)
    Bearish FVG : bars[idx-2].low  > bars[idx].high (gap down)
    """
    if idx < 2 or idx >= len(bars):
        return None
    if bars[idx-2]['high'] < bars[idx]['low']:
        return 'bull'
    if bars[idx-2]['low']  > bars[idx]['high']:
        return 'bear'
    return None


# ═══════════════════════════════════════════════════════════════════════════
# COMBO FILTER APPLICATION
# ═══════════════════════════════════════════════════════════════════════════

def signal_passes_combo(
    raw_dir   : str,          # 'bull' or 'bear'
    idx       : int,
    bars_1m   : List[Dict],
    session_bars: List[Dict], # bars since 9:30 this day
    params    : Dict,
) -> bool:
    """
    Apply the parameter combo filters.
    Returns True if the signal should be taken.
    """
    direction = params['direction']
    if direction == 'call_only' and raw_dir != 'bull':
        return False
    if direction == 'put_only'  and raw_dir != 'bear':
        return False

    # Session filter
    dt = bars_1m[idx]['dt']
    sess = params['session']
    if sess == 'or_only'  and not is_or_session(dt):
        return False
    if sess == 'early'    and not is_early_session(dt):
        return False

    bars_so_far = bars_1m[:idx+1]

    # RVOL
    if calc_rvol(bars_so_far) < params['rvol_min']:
        return False

    # MFI
    if params['mfi_min'] > 0:
        mfi = calc_mfi(bars_so_far)
        if raw_dir == 'bull' and mfi < params['mfi_min']:
            return False
        if raw_dir == 'bear' and mfi > (100 - params['mfi_min']):
            return False

    # OBV trend
    if params['obv_bars'] > 0:
        slope = calc_obv_trend(bars_so_far, params['obv_bars'])
        if raw_dir == 'bull' and slope <= 0:
            return False
        if raw_dir == 'bear' and slope >= 0:
            return False

    # VWAP zone
    vzone = params['vwap_zone']
    if vzone != 'none' and session_bars:
        vwap, upper_1sd, lower_1sd = calc_vwap_bands(session_bars)
        price = bars_1m[idx]['close']
        if vzone == 'above_vwap':
            if raw_dir == 'bull' and price <= vwap:
                return False
            if raw_dir == 'bear' and price >= vwap:
                return False
        elif vzone == 'above_1sd':
            if raw_dir == 'bull' and price <= upper_1sd:
                return False
            if raw_dir == 'bear' and price >= lower_1sd:
                return False

    # Timeframe confirmation
    # We simulate multi-TF by requiring agreement on compressed bars
    tf = params['tf_confirm']
    if tf != '1m':
        required_tfs = {
            '3m'       : [3],
            '5m'       : [5],
            '5m_3m'    : [5, 3],
            '5m_3m_1m' : [5, 3, 1],
        }.get(tf, [])

        # Use enough bars to build 2 compressed bars minimum
        window = bars_1m[max(0, idx-100):idx+1]
        for tf_min in required_tfs:
            if tf_min == 1:
                continue
            compressed = compress_to_tf(window, tf_min)
            if len(compressed) < 3:
                return False
            # Check BOS direction agrees on compressed TF
            compressed_dir = detect_bos(compressed, len(compressed)-1,
                                        params['bos_strength'], lookback=min(10, len(compressed)-1))
            if compressed_dir is None:
                # No BOS on higher TF — use FVG as fallback
                fvg_dir = detect_fvg(compressed, len(compressed)-1)
                if fvg_dir != raw_dir:
                    return False
            elif compressed_dir != raw_dir:
                return False

    return True


# ═══════════════════════════════════════════════════════════════════════════
# TRADE SIMULATION
# ═══════════════════════════════════════════════════════════════════════════

def simulate_outcome(bars: List[Dict], entry_idx: int, direction: str,
                     atr_mult: float = 1.5, max_bars: int = 30) -> float:
    """
    Returns R-multiple of the trade.
    Stop = 1.5 ATR, T1 = 1R, T2 = 2R (exits at T2 if hit, else T1, else stop, else EOD).
    Using T1=1R, T2=2R aligns with the tiered target preference.
    """
    entry_price = bars[entry_idx]['close']
    atr = calc_atr(bars[:entry_idx+1])
    risk = atr * atr_mult
    if risk <= 0:
        return 0.0

    if direction == 'bull':
        stop   = entry_price - risk
        t1     = entry_price + risk
        t2     = entry_price + risk * 2
    else:
        stop   = entry_price + risk
        t1     = entry_price - risk
        t2     = entry_price - risk * 2

    future = bars[entry_idx+1 : entry_idx+1+max_bars]
    for bar in future:
        h, l = bar['high'], bar['low']
        if direction == 'bull':
            if l <= stop:
                return -1.0
            if h >= t2:
                return 2.0
            if h >= t1:
                return 1.0
        else:
            if h >= stop:
                return -1.0
            if l <= t2:
                return 2.0
            if l <= t1:
                return 1.0

    # EOD exit — use last close
    last = future[-1]['close'] if future else entry_price
    if direction == 'bull':
        return (last - entry_price) / risk
    else:
        return (entry_price - last) / risk


# ═══════════════════════════════════════════════════════════════════════════
# SINGLE COMBO EVALUATION
# ═══════════════════════════════════════════════════════════════════════════

def evaluate_combo(
    params         : Dict,
    ticker_bars    : Dict[str, List[Dict]],
    tickers        : List[str],
    min_trades     : int = 15,
) -> Optional[Dict]:
    """
    Run one parameter combo across all tickers.
    Returns a result dict or None if insufficient trades.
    """
    all_rs: List[float] = []
    used_tickers: List[str] = []

    for ticker in tickers:
        bars = ticker_bars.get(ticker, [])
        if len(bars) < 100:
            continue

        # Group by trading day
        day_buckets: Dict[date, List[Dict]] = {}
        for b in bars:
            d = b['dt'].date()
            day_buckets.setdefault(d, []).append(b)

        ticker_rs: List[float] = []

        for day_bars in day_buckets.values():
            # Only RTH bars, sorted
            rth = sorted([b for b in day_bars if is_rth(b['dt'])], key=lambda x: x['dt'])
            if len(rth) < 30:
                continue

            # Build session bars (VWAP calculated from market open)
            for idx in range(20, len(rth) - 5):
                session_bars = rth[:idx+1]

                # BOS detection
                bos_dir = detect_bos(rth, idx, params['bos_strength'])
                fvg_dir = detect_fvg(rth, idx)

                # Use BOS+FVG agreement as the base signal
                signal_dir = None
                if bos_dir and fvg_dir and bos_dir == fvg_dir:
                    signal_dir = bos_dir
                elif bos_dir:
                    signal_dir = bos_dir  # BOS alone is OK

                if signal_dir is None:
                    continue

                # Apply combo filters
                if not signal_passes_combo(signal_dir, idx, rth, session_bars, params):
                    continue

                # Simulate trade
                r = simulate_outcome(rth, idx, signal_dir)
                ticker_rs.append(r)

        if ticker_rs:
            all_rs.extend(ticker_rs)
            used_tickers.append(ticker)

    if len(all_rs) < min_trades:
        return None

    wins       = sum(1 for r in all_rs if r > 0)
    win_rate   = wins / len(all_rs)
    avg_r      = sum(all_rs) / len(all_rs)
    total_r    = sum(all_rs)
    # Score = win_rate * avg_r (rewards both accuracy AND profit per trade)
    score      = win_rate * max(avg_r, 0)

    return {
        'total_trades': len(all_rs),
        'wins'        : wins,
        'losses'      : len(all_rs) - wins,
        'win_rate'    : round(win_rate, 4),
        'avg_r'       : round(avg_r, 4),
        'total_r'     : round(total_r, 4),
        'score'       : round(score, 4),
        'tickers_used': ','.join(used_tickers),
    }


# ═══════════════════════════════════════════════════════════════════════════
# CAMPAIGN RUNNER
# ═══════════════════════════════════════════════════════════════════════════

def run_campaign(
    tickers    : List[str],
    days_back  : int = 90,
    min_trades : int = 15,
    out_path   : str = None,
):
    if out_path is None:
        out_path = os.path.join(os.path.dirname(__file__), 'campaign_results.db')

    print('='*72)
    print('WAR MACHINE — FULL BACKTEST CAMPAIGN')
    print('='*72)
    print(f'Tickers  : {len(tickers)}')
    print(f'Days back: {days_back}')
    print(f'Min trades per combo: {min_trades}')
    print(f'Results DB: {out_path}')
    print()

    # ── Load data ───────────────────────────────────────────────────────
    print('[1/3] Loading cached bar data...')
    src_conn = open_source_db()
    ticker_bars = load_all_bars(src_conn, days_back)
    src_conn.close()

    # Filter to requested tickers that actually have data
    available = [t for t in tickers if t in ticker_bars]
    if not available:
        print('❌  None of the requested tickers have cached bar data.')
        print('    Run 01_fetch_candles.py to see what is available.')
        return
    print(f'  Using {len(available)} tickers: {available}')
    print()

    # ── Build combo list ────────────────────────────────────────────────
    keys   = list(GRID.keys())
    values = [GRID[k] for k in keys]
    combos = list(product(*values))
    total  = len(combos)
    print(f'[2/3] Running {total:,} parameter combinations...')
    print()

    # ── Open results DB ─────────────────────────────────────────────────
    res_conn = open_results_db(out_path)

    start_time   = time.time()
    saved        = 0
    skipped      = 0
    batch        : List[Tuple] = []
    BATCH_SIZE   = 500

    for i, combo_vals in enumerate(combos):
        params = dict(zip(keys, combo_vals))
        combo_key = '|'.join(f'{k}={v}' for k,v in params.items())

        result = evaluate_combo(params, ticker_bars, available, min_trades)

        if result:
            batch.append((
                combo_key,
                params['bos_strength'],
                params['tf_confirm'],
                params['vwap_zone'],
                params['rvol_min'],
                params['mfi_min'],
                params['obv_bars'],
                params['session'],
                params['direction'],
                result['total_trades'],
                result['wins'],
                result['losses'],
                result['win_rate'],
                result['avg_r'],
                result['total_r'],
                result['score'],
                result['tickers_used'],
                datetime.now(ET).isoformat(),
            ))
            saved += 1
        else:
            skipped += 1

        # Flush batch
        if len(batch) >= BATCH_SIZE:
            res_conn.executemany("""
                INSERT INTO results (
                    combo_key, bos_strength, tf_confirm, vwap_zone,
                    rvol_min, mfi_min, obv_bars, session, direction,
                    total_trades, wins, losses, win_rate, avg_r,
                    total_r, score, tickers_used, created_at
                ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            """, batch)
            res_conn.commit()
            batch = []

        # Progress update every 500 combos
        if (i + 1) % 500 == 0:
            elapsed = time.time() - start_time
            rate    = (i + 1) / elapsed
            eta_s   = (total - i - 1) / rate if rate > 0 else 0
            pct     = (i + 1) / total * 100
            print(f'  {pct:5.1f}%  {i+1:>7}/{total:>7}  '
                  f'saved={saved:<6} skipped={skipped:<6}  '
                  f'ETA {int(eta_s//60)}m{int(eta_s%60):02d}s')

    # Flush remaining
    if batch:
        res_conn.executemany("""
            INSERT INTO results (
                combo_key, bos_strength, tf_confirm, vwap_zone,
                rvol_min, mfi_min, obv_bars, session, direction,
                total_trades, wins, losses, win_rate, avg_r,
                total_r, score, tickers_used, created_at
            ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
        """, batch)
        res_conn.commit()

    elapsed = time.time() - start_time
    print()
    print(f'[3/3] Campaign complete!')
    print(f'  Elapsed    : {int(elapsed//60)}m {int(elapsed%60):02d}s')
    print(f'  Total combos: {total:,}')
    print(f'  Saved       : {saved:,}  (had >= {min_trades} trades)')
    print(f'  Skipped     : {skipped:,} (too few trades)')
    print(f'  Results DB  : {out_path}')
    print()
    print('✅  Run 03_analyze_results.py to see the leaderboard.')
    res_conn.close()


# ═══════════════════════════════════════════════════════════════════════════
# CLI ENTRY POINT
# ═══════════════════════════════════════════════════════════════════════════

if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='War Machine Full Backtest Campaign')
    parser.add_argument('--tickers',    type=str,  default=None,
                        help='Comma-separated tickers. Default: read usable_tickers.txt')
    parser.add_argument('--days',       type=int,  default=90,
                        help='Days of history to use (default: 90)')
    parser.add_argument('--min-trades', type=int,  default=15,
                        help='Min trades per combo to be saved (default: 15)')
    parser.add_argument('--out',        type=str,  default=None,
                        help='Path for campaign_results.db')
    args = parser.parse_args()

    # Resolve tickers
    if args.tickers:
        tickers = [t.strip().upper() for t in args.tickers.split(',') if t.strip()]
    else:
        txt_path = os.path.join(os.path.dirname(__file__), 'usable_tickers.txt')
        if os.path.exists(txt_path):
            with open(txt_path) as f:
                tickers = [l.strip() for l in f if l.strip()]
            print(f'Loaded {len(tickers)} tickers from usable_tickers.txt')
        else:
            # Hardcoded fallback — common high-volume tickers
            tickers = [
                'AAPL','NVDA','TSLA','SPY','QQQ','AMZN','MSFT','META',
                'GOOGL','AMD','MRVL','HIMS','VRT','AVGO','ORCL',
            ]
            print(f'usable_tickers.txt not found — using {len(tickers)} default tickers')

    run_campaign(
        tickers    = tickers,
        days_back  = args.days,
        min_trades = args.min_trades,
        out_path   = args.out,
    )
