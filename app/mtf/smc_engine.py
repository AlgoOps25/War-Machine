#!/usr/bin/env python3
"""
SMC Engine  —  app.mtf.smc_engine
===================================
Implements the 5 SMC principles previously missing or partial in War Machine:

  1. CHoCH (Change of Character)  — first opposing BOS = reversal signal
  2. Inducement detection         — liquidity sweep trap before real move
  3. Order Block detection        — last opposing candle before impulse move
  4. Order Block retest entry     — price returning to OB zone
  5. Trend Phase classification   — accumulation / markup / distribution / markdown

Design principles:
  - Non-breaking: every function returns None or a safe default on failure
  - Integrated into bos_fvg_engine.scan_bos_fvg() via enrich_signal_with_smc()
  - Standalone: can be called independently for analysis / Discord alerts
  - Zero new dependencies beyond stdlib + existing app.data path

Output dict injected into signal by enrich_signal_with_smc():
  {
    'choch':         CHoCH dict or None,
    'inducement':    Inducement dict or None,
    'order_block':   OrderBlock dict or None,
    'trend_phase':   str ('ACCUMULATION'|'MARKUP'|'DISTRIBUTION'|'MARKDOWN'|'UNKNOWN'),
    'smc_score':     float  0.0 – 1.0  (confidence bonus)
    'smc_filter':    bool   True = signal passes SMC filter
    'smc_notes':     list[str]
  }
"""

from __future__ import annotations
from typing import Dict, List, Optional, Tuple
from datetime import datetime
from zoneinfo import ZoneInfo

_ET = ZoneInfo("America/New_York")

# ─────────────────────────────────────────────────────────────────────────────
# CONSTANTS
# ─────────────────────────────────────────────────────────────────────────────

# Minimum body-to-range ratio for an "impulsive" candle (used in OB detection)
_IMPULSE_BODY_RATIO   = 0.55

# Inducement: a swing break is a trap if price reverses within this many bars
_INDUCEMENT_REVERSAL_BARS = 5

# Minimum % move to qualify an inducement sweep as meaningful
_INDUCEMENT_MIN_PCT   = 0.001   # 0.1%

# OB zone: last N candles before impulse to search for the order block
_OB_LOOKBACK          = 5

# SMC score weights
_W_CHOCH      = 0.30
_W_INDUCEMENT = 0.15
_W_OB         = 0.30
_W_PHASE      = 0.25


# ─────────────────────────────────────────────────────────────────────────────
# HELPERS
# ─────────────────────────────────────────────────────────────────────────────

def _swing_high(bars: List[Dict], lookback: int = 10) -> Tuple[Optional[float], Optional[int]]:
    """Return (price, index) of the most recent swing high."""
    if len(bars) < lookback * 2:
        return None, None
    recent = bars[-(lookback * 3):]
    best_price, best_idx = None, None
    half = lookback // 2
    for i in range(half, len(recent) - half):
        window = recent[i - half: i + half + 1]
        if recent[i]['high'] == max(b['high'] for b in window):
            if best_price is None or recent[i]['high'] > best_price:
                best_price = recent[i]['high']
                best_idx   = i
    return best_price, best_idx


def _swing_low(bars: List[Dict], lookback: int = 10) -> Tuple[Optional[float], Optional[int]]:
    """Return (price, index) of the most recent swing low."""
    if len(bars) < lookback * 2:
        return None, None
    recent = bars[-(lookback * 3):]
    best_price, best_idx = None, None
    half = lookback // 2
    for i in range(half, len(recent) - half):
        window = recent[i - half: i + half + 1]
        if recent[i]['low'] == min(b['low'] for b in window):
            if best_price is None or recent[i]['low'] < best_price:
                best_price = recent[i]['low']
                best_idx   = i
    return best_price, best_idx


def _is_impulsive(bar: Dict) -> bool:
    """True if candle has a strong body (institutional participation)."""
    bar_range = bar['high'] - bar['low']
    if bar_range == 0:
        return False
    body = abs(bar['close'] - bar['open'])
    return (body / bar_range) >= _IMPULSE_BODY_RATIO


def _bar_direction(bar: Dict) -> str:
    """'bull' if green candle, 'bear' if red."""
    return 'bull' if bar['close'] >= bar['open'] else 'bear'


# ─────────────────────────────────────────────────────────────────────────────
# 1. CHoCH — CHANGE OF CHARACTER
# ─────────────────────────────────────────────────────────────────────────────

def detect_choch(bars: List[Dict], signal_direction: str) -> Optional[Dict]:
    """
    Detect Change of Character (CHoCH).

    CHoCH = the FIRST break of structure in the OPPOSITE direction to the
    prevailing trend. It signals a potential trend reversal BEFORE it is
    fully confirmed, providing earlier and higher-probability entries.

    Logic:
      - For a BULL signal: prior trend must have been bearish (series of
        lower highs). A CHoCH occurs when close breaks ABOVE the most recent
        swing high in a downtrend → first sign of reversal.
      - For a BEAR signal: prior trend bullish (series of higher lows).
        CHoCH when close breaks BELOW the most recent swing low in an uptrend.

    Distinction from BOS:
      - BOS = structure break in the direction of the existing trend (continuation)
      - CHoCH = structure break AGAINST the trend (reversal)
      A bull signal preceded by a CHoCH is much higher probability than one
      that is simply a BOS continuation.

    Returns CHoCH dict or None.
    """
    if len(bars) < 30:
        return None

    try:
        # Determine prior trend using last 20 bars (excluding most recent 5)
        lookback_bars = bars[-25:-5]
        if len(lookback_bars) < 15:
            return None

        highs  = [b['high']  for b in lookback_bars]
        lows   = [b['low']   for b in lookback_bars]
        closes = [b['close'] for b in lookback_bars]

        # Simple trend: compare first half vs second half of lookback
        mid = len(closes) // 2
        first_half_avg  = sum(closes[:mid]) / mid
        second_half_avg = sum(closes[mid:]) / (len(closes) - mid)

        prior_trend_bull = second_half_avg > first_half_avg
        prior_trend_bear = second_half_avg < first_half_avg

        latest_bar = bars[-1]
        prev_bars  = bars[:-1]

        swing_h, _ = _swing_high(prev_bars)
        swing_l, _ = _swing_low(prev_bars)

        if signal_direction == 'bull' and prior_trend_bear:
            # Bullish CHoCH: first break of swing high in a downtrend
            if swing_h and latest_bar['close'] > swing_h:
                strength = (latest_bar['close'] - swing_h) / swing_h
                return {
                    'type':          'CHoCH',
                    'direction':     'bull',
                    'prior_trend':   'bear',
                    'break_level':   swing_h,
                    'break_price':   latest_bar['close'],
                    'strength':      round(strength * 100, 3),
                    'is_reversal':   True,
                    'quality':       'HIGH',   # reversal CHoCH = high quality
                }

        elif signal_direction == 'bear' and prior_trend_bull:
            # Bearish CHoCH: first break of swing low in an uptrend
            if swing_l and latest_bar['close'] < swing_l:
                strength = (swing_l - latest_bar['close']) / swing_l
                return {
                    'type':          'CHoCH',
                    'direction':     'bear',
                    'prior_trend':   'bull',
                    'break_level':   swing_l,
                    'break_price':   latest_bar['close'],
                    'strength':      round(strength * 100, 3),
                    'is_reversal':   True,
                    'quality':       'HIGH',
                }

        # BOS in direction of trend (continuation, not CHoCH)
        # Still return a record so caller knows it's a BOS, not CHoCH
        if signal_direction == 'bull' and prior_trend_bull and swing_h:
            if latest_bar['close'] > swing_h:
                return {
                    'type':        'BOS',
                    'direction':   'bull',
                    'prior_trend': 'bull',
                    'break_level': swing_h,
                    'break_price': latest_bar['close'],
                    'strength':    round((latest_bar['close'] - swing_h) / swing_h * 100, 3),
                    'is_reversal': False,
                    'quality':     'MEDIUM',  # continuation BOS
                }

        if signal_direction == 'bear' and prior_trend_bear and swing_l:
            if latest_bar['close'] < swing_l:
                return {
                    'type':        'BOS',
                    'direction':   'bear',
                    'prior_trend': 'bear',
                    'break_level': swing_l,
                    'break_price': latest_bar['close'],
                    'strength':    round((swing_l - latest_bar['close']) / swing_l * 100, 3),
                    'is_reversal': False,
                    'quality':     'MEDIUM',
                }

    except Exception as e:
        print(f"[SMC-ENGINE] CHoCH error (non-fatal): {e}")

    return None


# ─────────────────────────────────────────────────────────────────────────────
# 2. INDUCEMENT DETECTION
# ─────────────────────────────────────────────────────────────────────────────

def detect_inducement(bars: List[Dict], signal_direction: str) -> Optional[Dict]:
    """
    Detect Inducement (liquidity sweep / stop hunt before real move).

    Inducement = price briefly breaks a swing level (clearing retail stop
    orders / triggering breakout traders) then immediately reverses.
    Institutions use this to build positions at better prices.

    Logic:
      For a BULL signal:
        1. Find a recent swing LOW.
        2. Did price wick BELOW it (inducement sweep)?
        3. Did price then CLOSE BACK ABOVE it within N bars?
        → Classic bear trap / stop hunt before the real bull move.

      For a BEAR signal:
        1. Find a recent swing HIGH.
        2. Did price wick ABOVE it?
        3. Did price then close BACK BELOW it?
        → Classic bull trap / stop hunt before the real bear move.

    If inducement is detected immediately BEFORE the current BOS signal,
    the signal is significantly higher probability (institutions cleared
    the liquidity and are now running price in their direction).

    Returns inducement dict or None.
    """
    if len(bars) < 20:
        return None

    try:
        # Scan the last 15 bars (excluding most recent)
        scan_window = bars[-16:-1]
        if len(scan_window) < 10:
            return None

        swing_h, _ = _swing_high(scan_window)
        swing_l, _ = _swing_low(scan_window)

        if signal_direction == 'bull' and swing_l:
            # Look for a wick below swing_low followed by close above it
            for i in range(len(scan_window) - 1):
                bar      = scan_window[i]
                next_bar = scan_window[i + 1]
                sweep_depth = swing_l - bar['low']
                if (bar['low'] < swing_l
                        and sweep_depth / swing_l >= _INDUCEMENT_MIN_PCT
                        and next_bar['close'] > swing_l):
                    return {
                        'type':          'INDUCEMENT',
                        'direction':     'bull',
                        'sweep_level':   swing_l,
                        'sweep_low':     bar['low'],
                        'recovery_bar':  i + 1,
                        'sweep_depth':   round(sweep_depth, 4),
                        'sweep_pct':     round(sweep_depth / swing_l * 100, 3),
                        'confirmed':     True,
                        'note':          'Bear trap: price swept below swing low then recovered — bulls in control',
                    }

        if signal_direction == 'bear' and swing_h:
            # Look for a wick above swing_high followed by close below it
            for i in range(len(scan_window) - 1):
                bar      = scan_window[i]
                next_bar = scan_window[i + 1]
                sweep_height = bar['high'] - swing_h
                if (bar['high'] > swing_h
                        and sweep_height / swing_h >= _INDUCEMENT_MIN_PCT
                        and next_bar['close'] < swing_h):
                    return {
                        'type':          'INDUCEMENT',
                        'direction':     'bear',
                        'sweep_level':   swing_h,
                        'sweep_high':    bar['high'],
                        'recovery_bar':  i + 1,
                        'sweep_height':  round(sweep_height, 4),
                        'sweep_pct':     round(sweep_height / swing_h * 100, 3),
                        'confirmed':     True,
                        'note':          'Bull trap: price swept above swing high then rejected — bears in control',
                    }

    except Exception as e:
        print(f"[SMC-ENGINE] Inducement error (non-fatal): {e}")

    return None


# ─────────────────────────────────────────────────────────────────────────────
# 3. ORDER BLOCK DETECTION
# ─────────────────────────────────────────────────────────────────────────────

def detect_order_block(bars: List[Dict], signal_direction: str) -> Optional[Dict]:
    """
    Detect the most recent Order Block (OB) relevant to the signal direction.

    Order Block = the LAST opposing candle before a strong impulsive move.
    Institutions accumulate/distribute in this candle. Price frequently
    returns to the OB zone for liquidity before continuing the move.

    Logic:
      For a BULL signal:
        - Find the most recent strong BULLISH impulse (series of green candles
          or single large green candle with impulse body ratio).
        - The OB is the last RED (bearish) candle BEFORE that impulse started.
        - OB zone = that candle's high (top) to low (bottom).

      For a BEAR signal:
        - Find the most recent strong BEARISH impulse.
        - The OB is the last GREEN (bullish) candle before that impulse.
        - OB zone = that candle's high to low.

    The OB is a high-probability entry zone when price returns to it after
    the initial impulse (retrace to OB = institutional reloading).

    Returns OB dict or None.
    """
    if len(bars) < 15:
        return None

    try:
        # Scan last 20 bars (excluding latest) for impulse origin
        scan_bars = bars[-21:-1]
        if len(scan_bars) < 10:
            return None

        if signal_direction == 'bull':
            # Find the most recent bullish impulse candle
            for i in range(len(scan_bars) - 1, 0, -1):
                bar = scan_bars[i]
                if _bar_direction(bar) == 'bull' and _is_impulsive(bar):
                    # Found impulse candle. Look back for last opposing (bear) candle
                    for j in range(i - 1, max(i - _OB_LOOKBACK - 1, -1), -1):
                        candidate = scan_bars[j]
                        if _bar_direction(candidate) == 'bear':
                            ob_zone_high = candidate['high']
                            ob_zone_low  = candidate['low']
                            ob_size      = ob_zone_high - ob_zone_low
                            ob_mid       = (ob_zone_high + ob_zone_low) / 2
                            return {
                                'type':        'ORDER_BLOCK',
                                'direction':   'bull',
                                'ob_high':     round(ob_zone_high, 4),
                                'ob_low':      round(ob_zone_low,  4),
                                'ob_mid':      round(ob_mid,       4),
                                'ob_size':     round(ob_size,      4),
                                'impulse_idx': i,
                                'ob_idx':      j,
                                'valid':       True,
                                'note':        'Last bearish candle before bullish impulse — institutional demand zone',
                            }

        elif signal_direction == 'bear':
            # Find the most recent bearish impulse candle
            for i in range(len(scan_bars) - 1, 0, -1):
                bar = scan_bars[i]
                if _bar_direction(bar) == 'bear' and _is_impulsive(bar):
                    # Found impulse candle. Look back for last opposing (bull) candle
                    for j in range(i - 1, max(i - _OB_LOOKBACK - 1, -1), -1):
                        candidate = scan_bars[j]
                        if _bar_direction(candidate) == 'bull':
                            ob_zone_high = candidate['high']
                            ob_zone_low  = candidate['low']
                            ob_size      = ob_zone_high - ob_zone_low
                            ob_mid       = (ob_zone_high + ob_zone_low) / 2
                            return {
                                'type':        'ORDER_BLOCK',
                                'direction':   'bear',
                                'ob_high':     round(ob_zone_high, 4),
                                'ob_low':      round(ob_zone_low,  4),
                                'ob_mid':      round(ob_mid,       4),
                                'ob_size':     round(ob_size,      4),
                                'impulse_idx': i,
                                'ob_idx':      j,
                                'valid':       True,
                                'note':        'Last bullish candle before bearish impulse — institutional supply zone',
                            }

    except Exception as e:
        print(f"[SMC-ENGINE] OrderBlock error (non-fatal): {e}")

    return None


# ─────────────────────────────────────────────────────────────────────────────
# 4. ORDER BLOCK RETEST CHECK
# ─────────────────────────────────────────────────────────────────────────────

def check_ob_retest(bars: List[Dict], order_block: Optional[Dict]) -> Optional[Dict]:
    """
    Check if current price is retesting the Order Block zone.

    A retest of the OB zone is the HIGHEST probability entry in SMC:
    - Price moved away from the OB (impulse confirmed institutions were there)
    - Price pulled back INTO the OB zone (institutions reloading)
    - Entry: on touch of OB zone with confirmation candle
    - Stop: just beyond the far side of OB

    For a bull OB: current price retesting the OB = low of current bar
    touches between ob_low and ob_high.
    For a bear OB: current high touches between ob_low and ob_high.

    Returns retest dict (with entry zone) or None.
    """
    if order_block is None or len(bars) < 2:
        return None

    try:
        current_bar = bars[-1]
        ob_high = order_block['ob_high']
        ob_low  = order_block['ob_low']
        ob_mid  = order_block['ob_mid']
        direction = order_block['direction']

        if direction == 'bull':
            # Price low touching OB zone and closing above mid (confirming demand)
            if current_bar['low'] <= ob_high and current_bar['close'] >= ob_mid:
                return {
                    'retest':        True,
                    'retest_type':   'OB_DEMAND_ZONE',
                    'entry_zone_hi': ob_high,
                    'entry_zone_lo': ob_low,
                    'stop_below':    round(ob_low * 0.998, 4),  # 0.2% below OB low
                    'quality':       'HIGH' if current_bar['close'] > ob_mid else 'MEDIUM',
                    'note':          'Price retesting demand OB — institutional buy zone active',
                }

        elif direction == 'bear':
            # Price high touching OB zone and closing below mid (confirming supply)
            if current_bar['high'] >= ob_low and current_bar['close'] <= ob_mid:
                return {
                    'retest':        True,
                    'retest_type':   'OB_SUPPLY_ZONE',
                    'entry_zone_hi': ob_high,
                    'entry_zone_lo': ob_low,
                    'stop_above':    round(ob_high * 1.002, 4),  # 0.2% above OB high
                    'quality':       'HIGH' if current_bar['close'] < ob_mid else 'MEDIUM',
                    'note':          'Price retesting supply OB — institutional sell zone active',
                }

    except Exception as e:
        print(f"[SMC-ENGINE] OB retest error (non-fatal): {e}")

    return None


# ─────────────────────────────────────────────────────────────────────────────
# 5. TREND PHASE CLASSIFICATION
# ─────────────────────────────────────────────────────────────────────────────

def classify_trend_phase(bars: List[Dict]) -> str:
    """
    Classify the current market structure phase:

      ACCUMULATION  — sideways range after a downtrend (smart money building longs)
      MARKUP        — active uptrend: higher highs + higher lows
      DISTRIBUTION  — sideways range after an uptrend (smart money distributing)
      MARKDOWN      — active downtrend: lower highs + lower lows
      UNKNOWN       — insufficient data or no clear pattern

    Method: Wyckoff-inspired swing structure on last 30 bars.
      - Extract swing highs and lows
      - Determine HH/HL (markup) or LH/LL (markdown) pattern
      - Range-bound after trend = distribution/accumulation
    """
    if len(bars) < 30:
        return 'UNKNOWN'

    try:
        window = bars[-30:]
        closes = [b['close'] for b in window]
        highs  = [b['high']  for b in window]
        lows   = [b['low']   for b in window]

        # Split into 3 thirds: early, mid, late
        third = len(closes) // 3
        early_hi  = max(highs[:third])
        early_lo  = min(lows[:third])
        mid_hi    = max(highs[third:2*third])
        mid_lo    = min(lows[third:2*third])
        late_hi   = max(highs[2*third:])
        late_lo   = min(lows[2*third:])

        # MARKUP: each third makes higher highs AND higher lows
        if late_hi > mid_hi > early_hi and late_lo > mid_lo > early_lo:
            return 'MARKUP'

        # MARKDOWN: each third makes lower highs AND lower lows
        if late_hi < mid_hi < early_hi and late_lo < mid_lo < early_lo:
            return 'MARKDOWN'

        # Range-bound detection: price oscillates within a band
        total_range = max(highs) - min(lows)
        if total_range == 0:
            return 'UNKNOWN'

        # Measure price displacement from start to end vs total range
        net_move  = abs(closes[-1] - closes[0])
        range_use = net_move / total_range

        if range_use < 0.35:  # Less than 35% net displacement = range-bound
            # Prior trend determines if it’s accumulation or distribution
            early_avg = sum(closes[:third]) / third
            late_avg  = sum(closes[2*third:]) / (len(closes) - 2*third)
            if early_avg < late_avg:
                return 'DISTRIBUTION'  # Range after uptrend
            else:
                return 'ACCUMULATION'  # Range after downtrend

        # Mixed: HH but not HL, etc.
        if late_hi > early_hi and late_lo > early_lo:
            return 'MARKUP'
        if late_hi < early_hi and late_lo < early_lo:
            return 'MARKDOWN'

    except Exception as e:
        print(f"[SMC-ENGINE] TrendPhase error (non-fatal): {e}")

    return 'UNKNOWN'


# ─────────────────────────────────────────────────────────────────────────────
# SCORING & FILTER
# ─────────────────────────────────────────────────────────────────────────────

def _compute_smc_score(
    choch:       Optional[Dict],
    inducement:  Optional[Dict],
    order_block: Optional[Dict],
    ob_retest:   Optional[Dict],
    trend_phase: str,
    direction:   str,
) -> Tuple[float, bool, List[str]]:
    """
    Compute a composite SMC score (0.0 – 1.0) and filter decision.

    Score components:
      CHoCH:       +0.30 if CHoCH (reversal), +0.15 if BOS (continuation)
      Inducement:  +0.15 if confirmed
      Order Block: +0.25 if detected, +0.05 bonus if retest confirmed
      Trend Phase: +0.25 if phase aligns with signal direction
                   +0.10 if accumulation/distribution (neutral)
                    0.00 if directly opposing phase

    smc_filter: True = signal passes (safe to trade)
      - HARD BLOCK: BOS in direction of current trend DURING DISTRIBUTION
        (bull signal in distribution = almost certainly inducement/trap)
      - HARD BLOCK: bear signal during ACCUMULATION
      - WARNING: signal during UNKNOWN phase (score penalized, not blocked)
    """
    score = 0.0
    notes = []
    smc_filter = True

    # CHoCH / BOS quality
    if choch:
        if choch.get('is_reversal') and choch.get('type') == 'CHoCH':
            score += _W_CHOCH
            notes.append(f"CHoCH reversal detected (prior_trend={choch['prior_trend']}) +{_W_CHOCH:.0%}")
        elif choch.get('type') == 'BOS':
            score += _W_CHOCH * 0.5
            notes.append(f"BOS continuation (trend-aligned) +{_W_CHOCH*0.5:.0%}")
    else:
        notes.append('No CHoCH/BOS context — neutral')

    # Inducement
    if inducement and inducement.get('confirmed'):
        score += _W_INDUCEMENT
        notes.append(f"Inducement sweep confirmed +{_W_INDUCEMENT:.0%}")
    else:
        notes.append('No inducement sweep detected')

    # Order Block
    if order_block and order_block.get('valid'):
        score += _W_OB * 0.85
        notes.append(f"Order Block identified ({order_block['direction'].upper()}) +{_W_OB*0.85:.0%}")
        if ob_retest and ob_retest.get('retest'):
            score += _W_OB * 0.15
            notes.append(f"OB retest active ({ob_retest['retest_type']}) +{_W_OB*0.15:.0%}")
    else:
        notes.append('No Order Block found')

    # Trend Phase alignment
    phase_aligned = {
        'bull': ['MARKUP', 'ACCUMULATION'],
        'bear': ['MARKDOWN', 'DISTRIBUTION'],
    }
    phase_opposing = {
        'bull': ['DISTRIBUTION', 'MARKDOWN'],
        'bear': ['ACCUMULATION', 'MARKUP'],
    }

    if trend_phase in phase_aligned.get(direction, []):
        score += _W_PHASE
        notes.append(f"Trend phase aligned ({trend_phase}) +{_W_PHASE:.0%}")
    elif trend_phase in ['UNKNOWN']:
        score += _W_PHASE * 0.4
        notes.append(f"Trend phase unknown — partial credit +{_W_PHASE*0.4:.0%}")
    else:  # Opposing phase
        score += 0.0
        notes.append(f"Trend phase OPPOSING ({trend_phase}) — no credit")

        # Hard blocks: signal directly opposing institutional phase
        if trend_phase == 'DISTRIBUTION' and direction == 'bull':
            smc_filter = False
            notes.append('SMC FILTER BLOCK: bull signal during DISTRIBUTION — likely inducement trap')
        elif trend_phase == 'ACCUMULATION' and direction == 'bear':
            smc_filter = False
            notes.append('SMC FILTER BLOCK: bear signal during ACCUMULATION — likely inducement trap')

    score = round(min(score, 1.0), 4)
    return score, smc_filter, notes


# ─────────────────────────────────────────────────────────────────────────────
# PUBLIC API — enrich_signal_with_smc()
# ─────────────────────────────────────────────────────────────────────────────

def enrich_signal_with_smc(
    ticker:    str,
    direction: str,
    bars:      List[Dict],
    signal:    Dict,
) -> Dict:
    """
    Main entry point. Called from bos_fvg_engine.scan_bos_fvg() after
    a signal is produced, and from mtf_integration.enhance_signal_with_mtf().

    Runs all 5 SMC detection functions and injects results into signal dict.
    Never raises — all errors are caught internally.

    Returns the enriched signal dict.
    """
    try:
        # 1. CHoCH
        choch = detect_choch(bars, direction)

        # 2. Inducement
        inducement = detect_inducement(bars, direction)

        # 3. Order Block
        order_block = detect_order_block(bars, direction)

        # 4. OB Retest
        ob_retest = check_ob_retest(bars, order_block)

        # 5. Trend Phase
        trend_phase = classify_trend_phase(bars)

        # Score + filter
        smc_score, smc_filter, smc_notes = _compute_smc_score(
            choch, inducement, order_block, ob_retest, trend_phase, direction
        )

        # Inject into signal
        signal['smc'] = {
            'choch':       choch,
            'inducement':  inducement,
            'order_block': order_block,
            'ob_retest':   ob_retest,
            'trend_phase': trend_phase,
            'smc_score':   smc_score,
            'smc_filter':  smc_filter,
            'smc_notes':   smc_notes,
        }

        # Log summary
        choch_label = (
            f"✅ {choch['type']} ({choch['prior_trend']}→{choch['direction']})" if choch
            else '—'
        )
        ind_label = (
            f"✅ {inducement['sweep_pct']:.2f}% sweep" if inducement
            else '—'
        )
        ob_label = (
            f"✅ {order_block['ob_low']:.2f}–{order_block['ob_high']:.2f}"
            + (f" RETEST" if ob_retest else "")
            if order_block else '—'
        )
        filter_label = '✅ PASS' if smc_filter else '❌ BLOCK'

        print(
            f"[SMC] {ticker} {direction.upper()} | "
            f"CHoCH:{choch_label} | Inducement:{ind_label} | "
            f"OB:{ob_label} | Phase:{trend_phase} | "
            f"Score:{smc_score:.2f} | Filter:{filter_label}"
        )
        for note in smc_notes:
            print(f"  └ {note}")

    except Exception as e:
        print(f"[SMC-ENGINE] enrich_signal_with_smc error (non-fatal): {e}")
        signal.setdefault('smc', {
            'choch': None, 'inducement': None, 'order_block': None,
            'ob_retest': None, 'trend_phase': 'UNKNOWN',
            'smc_score': 0.0, 'smc_filter': True, 'smc_notes': ['SMC error — filter bypassed'],
        })

    return signal


print("[SMC-ENGINE] ✅ Loaded — CHoCH + Inducement + OrderBlock + TrendPhase active")
