#!/usr/bin/env python3
"""
SMC Engine — app.mtf.smc_engine
=================================
Implements the 5 missing/partial Smart Money Concepts:

  1. CHoCH Detection       — distinguishes trend reversal from continuation BOS
  2. Inducement Detection  — identifies liquidity grabs before real moves
  3. Order Block Detection — last opposing candle before impulsive move
  4. OB Retest Entry       — price returning to OB for institutional entry
  5. Trend Phase Class.    — Accumulation / Markup / Distribution / Markdown

Design:
  - ADDITIVE ONLY. Never blocks signals — enriches signal_data with SMC context.
  - sniper.py calls enrich_signal_with_smc(ticker, bars, signal_data) after
    BOS+FVG fires. Confidence boosts are applied here; no hard rejections.
  - All DB persistence is non-fatal (wrapped in try/except).

Public API:
    enrich_signal_with_smc(ticker, bars, signal_data) -> signal_data
"""

from __future__ import annotations
from datetime  import datetime
from zoneinfo  import ZoneInfo
from typing    import Dict, List, Optional, Tuple

_ET = ZoneInfo("America/New_York")

# ══════════════════════════════════════════════════════════════════════════════
# CONSTANTS
# ══════════════════════════════════════════════════════════════════════════════

# Inducement: how far beyond a swing high/low qualifies as a sweep (not a BOS)
INDUCEMENT_MAX_PCT   = 0.003   # ≤ 0.3% beyond swing = probable sweep
# Order Block: minimum body size as % of range to qualify
OB_MIN_BODY_PCT      = 0.30
# Order Block: max candles to look back for origin candle
OB_LOOKBACK          = 20
# CHoCH: confidence boost when a CHoCH reversal is detected
CHOCH_BOOST          = 0.04
# OB Retest: confidence boost when price returns to a valid OB zone
OB_RETEST_BOOST      = 0.03
# Trend Phase alignment boost
PHASE_ALIGN_BOOST    = 0.02
# Inducement penalty (signal fired into a sweep — reduce confidence)
INDUCEMENT_PENALTY   = -0.03


# ══════════════════════════════════════════════════════════════════════════════
# 1. TREND PHASE CLASSIFICATION
# ══════════════════════════════════════════════════════════════════════════════

def classify_trend_phase(bars: List[Dict]) -> Dict:
    """
    Classify the current market phase using Higher High / Higher Low
    (HH/HL) and Lower High / Lower Low (LH/LL) structure.

    Phases:
        ACCUMULATION  — sideways after downtrend; no clear HH or LL pattern
        MARKUP        — series of HH + HL = uptrend in progress
        DISTRIBUTION  — sideways after uptrend; HH failing, HL failing
        MARKDOWN      — series of LH + LL = downtrend in progress

    Uses last 30 bars (or all available). Needs at least 10 bars.
    Returns:
        {
            'phase':        'MARKUP' | 'MARKDOWN' | 'ACCUMULATION' | 'DISTRIBUTION' | 'UNKNOWN',
            'hh_count':     int,
            'hl_count':     int,
            'lh_count':     int,
            'll_count':     int,
            'trend_bias':   'bull' | 'bear' | 'neutral',
            'description':  str
        }
    """
    if len(bars) < 10:
        return {
            'phase': 'UNKNOWN', 'hh_count': 0, 'hl_count': 0,
            'lh_count': 0, 'll_count': 0,
            'trend_bias': 'neutral', 'description': 'Insufficient bars'
        }

    sample = bars[-30:] if len(bars) >= 30 else bars

    # Extract pivot highs and lows using simple 3-bar pivots
    pivot_highs = []
    pivot_lows  = []
    for i in range(1, len(sample) - 1):
        if sample[i]['high'] >= sample[i-1]['high'] and sample[i]['high'] >= sample[i+1]['high']:
            pivot_highs.append(sample[i]['high'])
        if sample[i]['low'] <= sample[i-1]['low'] and sample[i]['low'] <= sample[i+1]['low']:
            pivot_lows.append(sample[i]['low'])

    hh_count = lh_count = hl_count = ll_count = 0

    for i in range(1, len(pivot_highs)):
        if pivot_highs[i] > pivot_highs[i-1]:
            hh_count += 1
        else:
            lh_count += 1

    for i in range(1, len(pivot_lows)):
        if pivot_lows[i] > pivot_lows[i-1]:
            hl_count += 1
        else:
            ll_count += 1

    bull_score = hh_count + hl_count
    bear_score = lh_count + ll_count
    total      = bull_score + bear_score

    if total == 0:
        phase      = 'UNKNOWN'
        trend_bias = 'neutral'
    elif bull_score > bear_score * 1.5:
        phase      = 'MARKUP'
        trend_bias = 'bull'
    elif bear_score > bull_score * 1.5:
        phase      = 'MARKDOWN'
        trend_bias = 'bear'
    elif bull_score > 0 and bear_score > 0:
        # Determine if accumulation (recovering from markdown) or distribution (topping out)
        last_bias = 'bull' if (pivot_highs and pivot_lows and
                                pivot_highs[-1] > pivot_highs[0]) else 'bear'
        phase      = 'DISTRIBUTION' if last_bias == 'bull' else 'ACCUMULATION'
        trend_bias = 'neutral'
    else:
        phase      = 'UNKNOWN'
        trend_bias = 'neutral'

    descriptions = {
        'MARKUP':        f'Uptrend: {hh_count} HH + {hl_count} HL',
        'MARKDOWN':      f'Downtrend: {lh_count} LH + {ll_count} LL',
        'ACCUMULATION':  f'Sideways base: mixed structure (HH={hh_count} HL={hl_count} LH={lh_count} LL={ll_count})',
        'DISTRIBUTION':  f'Topping structure: failing highs (HH={hh_count} LH={lh_count})',
        'UNKNOWN':       'Insufficient pivot data',
    }

    return {
        'phase':      phase,
        'hh_count':   hh_count,
        'hl_count':   hl_count,
        'lh_count':   lh_count,
        'll_count':   ll_count,
        'trend_bias': trend_bias,
        'description': descriptions[phase]
    }


# ══════════════════════════════════════════════════════════════════════════════
# 2. CHoCH DETECTION
# ══════════════════════════════════════════════════════════════════════════════

def detect_choch(bars: List[Dict], bos_direction: str) -> Dict:
    """
    Detect whether the current BOS is a Change of Character (CHoCH)
    — the first BOS against the prevailing trend — vs a continuation BOS.

    Logic:
        1. Classify the trend phase using the bars BEFORE the BOS bar.
        2. If the BOS direction OPPOSES the current phase trend_bias
           → this is a CHoCH (reversal signal — highest probability)
        3. If the BOS direction MATCHES the phase trend_bias
           → this is a continuation BOS (lower probability, trend already extended)
        4. If phase is ACCUMULATION/DISTRIBUTION/UNKNOWN
           → treat as CHoCH (breakout from range = character change)

    Returns:
        {
            'is_choch':     bool,
            'choch_type':   'REVERSAL' | 'CONTINUATION' | 'BREAKOUT',
            'phase':        phase dict,
            'confidence_delta': float  (+CHOCH_BOOST or 0)
        }
    """
    if len(bars) < 15:
        return {
            'is_choch': False, 'choch_type': 'UNKNOWN',
            'phase': {}, 'confidence_delta': 0.0
        }

    # Use all bars except the last 2 (the BOS bar and confirmation bar)
    phase = classify_trend_phase(bars[:-2])
    trend_bias = phase['trend_bias']

    if trend_bias == 'neutral' or phase['phase'] in ('ACCUMULATION', 'DISTRIBUTION', 'UNKNOWN'):
        # BOS out of a range = CHoCH (breakout of character)
        return {
            'is_choch':         True,
            'choch_type':       'BREAKOUT',
            'phase':            phase,
            'confidence_delta': CHOCH_BOOST
        }

    if (bos_direction == 'bull' and trend_bias == 'bear') or \
       (bos_direction == 'bear' and trend_bias == 'bull'):
        # BOS opposes prevailing trend = first reversal signal
        return {
            'is_choch':         True,
            'choch_type':       'REVERSAL',
            'phase':            phase,
            'confidence_delta': CHOCH_BOOST
        }

    # BOS aligns with existing trend = continuation (already extended)
    return {
        'is_choch':         False,
        'choch_type':       'CONTINUATION',
        'phase':            phase,
        'confidence_delta': 0.0
    }


# ══════════════════════════════════════════════════════════════════════════════
# 3. INDUCEMENT DETECTION
# ══════════════════════════════════════════════════════════════════════════════

def detect_inducement(bars: List[Dict], bos_direction: str,
                      swing_level: float) -> Dict:
    """
    Detect if the BOS bar is an inducement (liquidity sweep) rather than
    a genuine structural break.

    An inducement is characterized by:
        - Close breaks beyond the swing level by ≤ INDUCEMENT_MAX_PCT
        - The bar's wick extends beyond but the close barely clears the level
        - i.e., the move is a stop-hunt, not a conviction break

    A genuine BOS breaks cleanly beyond the swing level with conviction.

    Returns:
        {
            'is_inducement':    bool,
            'sweep_pct':        float  (how far beyond swing the close went)
            'confidence_delta': float  (0 or INDUCEMENT_PENALTY)
            'description':      str
        }
    """
    if not bars or swing_level <= 0:
        return {'is_inducement': False, 'sweep_pct': 0.0,
                'confidence_delta': 0.0, 'description': 'No swing level'}

    bos_bar   = bars[-1]
    bos_close = bos_bar['close']
    bos_high  = bos_bar['high']
    bos_low   = bos_bar['low']

    if bos_direction == 'bull':
        # How far did the CLOSE break above swing high?
        sweep_pct = (bos_close - swing_level) / swing_level
        # Wick extended far but close barely cleared = inducement
        wick_extension = (bos_high - swing_level) / swing_level
        is_inducement  = (
            0 < sweep_pct <= INDUCEMENT_MAX_PCT and
            wick_extension > sweep_pct * 2  # wick >> close extension
        )
    else:  # bear
        sweep_pct = (swing_level - bos_close) / swing_level
        wick_extension = (swing_level - bos_low) / swing_level
        is_inducement  = (
            0 < sweep_pct <= INDUCEMENT_MAX_PCT and
            wick_extension > sweep_pct * 2
        )

    if is_inducement:
        desc = (
            f"⚠️ Inducement sweep detected: close broke {sweep_pct*100:.3f}% beyond "
            f"swing — wick extension {wick_extension*100:.3f}% suggests stop-hunt"
        )
    else:
        desc = f"Clean BOS: {sweep_pct*100:.3f}% beyond swing level"

    return {
        'is_inducement':    is_inducement,
        'sweep_pct':        round(sweep_pct * 100, 4),
        'wick_extension':   round(wick_extension * 100, 4),
        'confidence_delta': INDUCEMENT_PENALTY if is_inducement else 0.0,
        'description':      desc
    }


# ══════════════════════════════════════════════════════════════════════════════
# 4. ORDER BLOCK DETECTION
# ══════════════════════════════════════════════════════════════════════════════

def find_order_block(bars: List[Dict], bos_direction: str,
                     bos_idx: int) -> Optional[Dict]:
    """
    Find the Order Block — the last opposing candle before the impulsive
    move that caused the BOS.

    SMC definition:
        BULL OB: last BEARISH (red) candle before the impulsive upward move
                 that created the BOS. Price is expected to return to this zone.
        BEAR OB: last BULLISH (green) candle before the impulsive downward move.

    The OB zone = [OB candle low, OB candle high] (full candle body + wicks).
    A mitigated OB (price has already traded back through it) is marked stale.

    Returns OB dict or None.
    """
    if bos_idx is None or bos_idx < 3:
        return None

    # Search backward from BOS candle for the last opposing candle
    lookback_start = max(0, bos_idx - OB_LOOKBACK)
    search_bars    = bars[lookback_start:bos_idx]

    ob_bar     = None
    ob_bar_idx = None

    for i in range(len(search_bars) - 1, -1, -1):
        bar        = search_bars[i]
        body       = abs(bar['close'] - bar['open'])
        bar_range  = bar['high'] - bar['low']

        if bar_range == 0:
            continue

        body_pct = body / bar_range

        # Must have meaningful body (not a doji)
        if body_pct < OB_MIN_BODY_PCT:
            continue

        is_bearish = bar['close'] < bar['open']
        is_bullish = bar['close'] > bar['open']

        if bos_direction == 'bull' and is_bearish:
            ob_bar     = bar
            ob_bar_idx = lookback_start + i
            break  # Last bearish candle before bull impulse

        if bos_direction == 'bear' and is_bullish:
            ob_bar     = bar
            ob_bar_idx = lookback_start + i
            break  # Last bullish candle before bear impulse

    if ob_bar is None:
        return None

    # Check if OB has already been mitigated (price traded back through it)
    ob_high = ob_bar['high']
    ob_low  = ob_bar['low']
    ob_mid  = (ob_high + ob_low) / 2

    mitigated = False
    if ob_bar_idx is not None:
        post_ob_bars = bars[ob_bar_idx + 1:]
        for b in post_ob_bars:
            if bos_direction == 'bull' and b['low'] < ob_mid:
                mitigated = True
                break
            if bos_direction == 'bear' and b['high'] > ob_mid:
                mitigated = True
                break

    body_high = max(ob_bar['open'], ob_bar['close'])
    body_low  = min(ob_bar['open'], ob_bar['close'])

    return {
        'ob_high':        ob_high,
        'ob_low':         ob_low,
        'ob_mid':         round(ob_mid, 4),
        'body_high':      body_high,
        'body_low':       body_low,
        'ob_bar_idx':     ob_bar_idx,
        'ob_direction':   bos_direction,
        'mitigated':      mitigated,
        'ob_datetime':    ob_bar.get('datetime'),
        'description':    (
            f"{'🟢 BULL' if bos_direction == 'bull' else '🔴 BEAR'} OB "
            f"@ {ob_low:.2f}–{ob_high:.2f} "
            f"{'[MITIGATED]' if mitigated else '[FRESH]'}"
        )
    }


def check_ob_retest(bars: List[Dict], ob: Dict) -> Dict:
    """
    Check if the current bar (bars[-1]) is retesting the Order Block.

    A valid OB retest:
        - Price's low (bull) or high (bear) touches the OB zone
        - Close stays within or above/below the OB zone (not blown through)
        - OB must be fresh (not mitigated)

    Returns:
        {
            'is_retest':        bool,
            'retest_quality':   'BODY' | 'WICK' | 'NONE',
            'confidence_delta': float
        }
    """
    if not ob or ob.get('mitigated', True) or len(bars) < 2:
        return {'is_retest': False, 'retest_quality': 'NONE', 'confidence_delta': 0.0}

    current = bars[-1]
    ob_high = ob['ob_high']
    ob_low  = ob['ob_low']
    direction = ob['ob_direction']

    if direction == 'bull':
        touched = current['low'] <= ob_high and current['low'] >= ob_low * 0.995
        if not touched:
            return {'is_retest': False, 'retest_quality': 'NONE', 'confidence_delta': 0.0}
        # Body retest (open or close within OB) = higher quality
        body_in_ob = (min(current['open'], current['close']) >= ob_low and
                      min(current['open'], current['close']) <= ob_high)
        quality = 'BODY' if body_in_ob else 'WICK'

    else:  # bear
        touched = current['high'] >= ob_low and current['high'] <= ob_high * 1.005
        if not touched:
            return {'is_retest': False, 'retest_quality': 'NONE', 'confidence_delta': 0.0}
        body_in_ob = (max(current['open'], current['close']) >= ob_low and
                      max(current['open'], current['close']) <= ob_high)
        quality = 'BODY' if body_in_ob else 'WICK'

    boost = OB_RETEST_BOOST if quality == 'BODY' else OB_RETEST_BOOST * 0.5
    return {
        'is_retest':        True,
        'retest_quality':   quality,
        'confidence_delta': boost,
        'description':      f"{quality} retest of {ob['description']}"
    }


# ══════════════════════════════════════════════════════════════════════════════
# DB PERSISTENCE
# ══════════════════════════════════════════════════════════════════════════════

def _ensure_smc_table():
    try:
        from app.data.db_connection import get_conn, serial_pk, return_conn
        conn = get_conn()
        try:
            cursor = conn.cursor()
            cursor.execute(f"""
                CREATE TABLE IF NOT EXISTS smc_signal_context (
                    id {serial_pk()},
                    ticker          TEXT NOT NULL,
                    signal_type     TEXT NOT NULL,
                    direction       TEXT NOT NULL,
                    is_choch        BOOLEAN DEFAULT FALSE,
                    choch_type      TEXT,
                    trend_phase     TEXT,
                    trend_bias      TEXT,
                    is_inducement   BOOLEAN DEFAULT FALSE,
                    inducement_pct  REAL,
                    ob_zone_low     REAL,
                    ob_zone_high    REAL,
                    ob_mitigated    BOOLEAN,
                    ob_retest       BOOLEAN DEFAULT FALSE,
                    ob_retest_qual  TEXT,
                    confidence_delta REAL DEFAULT 0.0,
                    session_date    DATE,
                    ts              TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)
            conn.commit()
        finally:
            return_conn(conn)
    except Exception as e:
        print(f"[SMC-ENGINE] DB init error (non-fatal): {e}")


_ensure_smc_table()


def _persist_smc_context(ticker: str, smc: Dict):
    try:
        from app.data.db_connection import get_conn, ph as _ph, return_conn
        conn = get_conn()
        now  = datetime.now(_ET)
        ob   = smc.get('order_block') or {}
        obr  = smc.get('ob_retest')   or {}
        choch = smc.get('choch')      or {}
        ind   = smc.get('inducement') or {}
        phase = choch.get('phase')    or {}
        try:
            cursor = conn.cursor()
            p = _ph()
            cursor.execute(
                f"INSERT INTO smc_signal_context "
                f"(ticker, signal_type, direction, is_choch, choch_type, "
                f" trend_phase, trend_bias, is_inducement, inducement_pct, "
                f" ob_zone_low, ob_zone_high, ob_mitigated, ob_retest, "
                f" ob_retest_qual, confidence_delta, session_date, ts) "
                f"VALUES ({p},{p},{p},{p},{p},{p},{p},{p},{p},{p},{p},{p},{p},{p},{p},{p},{p})",
                (
                    ticker,
                    smc.get('signal_type', 'BOS+FVG'),
                    smc.get('direction', ''),
                    choch.get('is_choch', False),
                    choch.get('choch_type'),
                    phase.get('phase'),
                    phase.get('trend_bias'),
                    ind.get('is_inducement', False),
                    ind.get('sweep_pct'),
                    ob.get('ob_low'),
                    ob.get('ob_high'),
                    ob.get('mitigated'),
                    obr.get('is_retest', False),
                    obr.get('retest_quality'),
                    smc.get('total_confidence_delta', 0.0),
                    now.date(),
                    now,
                )
            )
            conn.commit()
        finally:
            return_conn(conn)
    except Exception as e:
        print(f"[SMC-ENGINE] Persist error (non-fatal): {e}")


# ══════════════════════════════════════════════════════════════════════════════
# PUBLIC API — enrich_signal_with_smc()
# ══════════════════════════════════════════════════════════════════════════════

def enrich_signal_with_smc(
    ticker:      str,
    bars:        List[Dict],
    signal_data: Dict,
) -> Dict:
    """
    Main entry point. Called from sniper.py after BOS+FVG fires.

    Enriches signal_data with SMC context and adjusts confidence:
        signal_data['smc'] = {
            'choch':              {...},
            'inducement':         {...},
            'order_block':        {...} | None,
            'ob_retest':          {...},
            'trend_phase':        {...},
            'total_confidence_delta': float,
            'smc_summary':        str
        }

    NEVER raises. All failures are non-fatal.
    Returns signal_data unchanged on any error.
    """
    try:
        direction = signal_data.get('direction', 'bull')
        bos_idx   = signal_data.get('bos_idx')
        bos_price = signal_data.get('bos_price', 0.0)

        # ── 1. Trend Phase ───────────────────────────────────────────
        phase = classify_trend_phase(bars)

        # ── 2. CHoCH ─────────────────────────────────────────────────
        choch = detect_choch(bars, direction)

        # ── 3. Inducement ─────────────────────────────────────────────
        inducement = detect_inducement(bars, direction, bos_price)

        # ── 4. Order Block ────────────────────────────────────────────
        ob = find_order_block(bars, direction, bos_idx)

        # ── 5. OB Retest ──────────────────────────────────────────────
        ob_retest = check_ob_retest(bars, ob) if ob else \
            {'is_retest': False, 'retest_quality': 'NONE', 'confidence_delta': 0.0}

        # ── Phase alignment boost ─────────────────────────────────────
        phase_delta = 0.0
        if (direction == 'bull' and phase.get('trend_bias') == 'bull') or \
           (direction == 'bear' and phase.get('trend_bias') == 'bear'):
            phase_delta = PHASE_ALIGN_BOOST

        # ── Total delta (cap at +0.10 / floor at -0.05) ───────────────
        total_delta = (
            choch.get('confidence_delta', 0.0) +
            inducement.get('confidence_delta', 0.0) +
            ob_retest.get('confidence_delta', 0.0) +
            phase_delta
        )
        total_delta = max(-0.05, min(0.10, total_delta))

        # ── Summary string for logs / Discord ─────────────────────────
        smc_tags = []
        if choch.get('is_choch'):
            smc_tags.append(f"CHoCH:{choch['choch_type']}")
        if inducement.get('is_inducement'):
            smc_tags.append("⚠️INDUCEMENT")
        if ob and not ob.get('mitigated'):
            smc_tags.append(f"OB@{ob['ob_low']:.2f}-{ob['ob_high']:.2f}")
        if ob_retest.get('is_retest'):
            smc_tags.append(f"OB_RETEST:{ob_retest['retest_quality']}")
        smc_tags.append(f"PHASE:{phase['phase']}")

        smc_summary = ' | '.join(smc_tags) if smc_tags else 'SMC:NO_CONTEXT'

        smc_context = {
            'choch':                 choch,
            'inducement':            inducement,
            'order_block':           ob,
            'ob_retest':             ob_retest,
            'trend_phase':           phase,
            'total_confidence_delta': total_delta,
            'smc_summary':           smc_summary,
            'direction':             direction,
            'signal_type':           signal_data.get('entry_type', 'BOS+FVG'),
        }

        signal_data['smc'] = smc_context

        # Log
        delta_str = f"+{total_delta*100:.1f}%" if total_delta >= 0 else f"{total_delta*100:.1f}%"
        print(
            f"[SMC] {ticker} {direction.upper()} | {smc_summary} | "
            f"conf_delta={delta_str}"
        )

        # Persist (non-fatal)
        _persist_smc_context(ticker, smc_context)

    except Exception as e:
        print(f"[SMC-ENGINE] enrich error for {ticker} (non-fatal): {e}")

    return signal_data


print("[SMC-ENGINE] ✅ SMC engine initialized — CHoCH, Inducement, OB, Phase active")
