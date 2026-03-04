"""
Historical Backtest - Test Optimized Parameters on Past 90 Days

This script backtests the optimized parameters from smart_optimization.py
against real historical market data to validate performance.

Process:
1. Load 90 days of cached historical data (1-min bars)
2. Scan for BOS/FVG pattern signals
3. Apply optimized filters to each signal
4. Simulate trade outcomes (entry, stop, targets)
5. Generate performance comparison report

Usage:
    python backtest_optimized_params.py
    
Output:
    - backtest_results.json (detailed results)
    - backtest_report.txt (human-readable summary)
"""

import sys
sys.path.append('.')

import json
import numpy as np
import pandas as pd
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
from typing import Dict, List, Tuple, Optional
from dataclasses import dataclass, asdict
from collections import defaultdict

# War Machine imports
from app.data.db_connection import get_conn, ph, dict_cursor

ET = ZoneInfo("America/New_York")

# Load optimized parameters
OPTIMIZED_PARAMS = {
    "adx_threshold": 33.14,
    "rsi_overbought": 70.49,
    "rsi_oversold": 20.0,
    "mfi_overbought": 80.54,
    "mfi_oversold": 30.0,
    "macd_lookback": 5,
    "stoch_overbought": 75.0,
    "stoch_oversold": 20.43,
    "bb_squeeze_threshold": 0.056,
    "volume_ratio_min": 2.5,
    "vwap_min_deviation": 0.0,
    "atr_multiplier": 3.0,
    "ema_period": 50,
    "obv_lookback": 8,
    "divergence_lookback": 15,
    "rvol_threshold": 2.0,
    "fvg_size_threshold": 1.0,
    "bos_break_strength": 0.60,
    "orb_percentile": 39.5,
    "recent_hl_lookback": 12,
    "consolidation_bars": 10,
    "breakout_confirm_bars": 1,
    "ema_weight": 0.0,
    "volume_weight": 0.0,
    "momentum_weight": 0.16,
    "volume_confluence_weight": 0.043,
    "divergence_penalty": -0.06,
    "squeeze_bonus": 0.002,
    "rvol_bonus": 0.099,
    "crossover_bonus": 0.1,
    "require_ema_align": False,
    "require_vwap_confirm": False,
    "require_mfi_confirm": True,
    "require_obv_confirm": False,
    "require_trend_strength": False,
    "require_volume_confirm": False,
    "block_divergence": True,
    "require_crossover": True,
}


@dataclass
class HistoricalSignal:
    """A signal detected in historical data"""
    timestamp: datetime
    ticker: str
    direction: str  # 'CALL' or 'PUT'
    signal_type: str  # 'BOS', 'FVG', 'ORB', etc.
    entry_price: float
    signal_strength: float
    bar_data: Dict  # The bar where signal occurred


@dataclass
class TradeResult:
    """Result of a simulated trade"""
    signal: HistoricalSignal
    passed_filter: bool
    confidence_score: float
    entry_price: float
    stop_price: float
    exit_price: float
    exit_reason: str  # 'STOP_HIT', 'TARGET_1R', 'TARGET_2R', 'TARGET_3R', 'EOD'
    r_multiple: float
    pnl_percent: float
    hold_time_minutes: int
    win: bool


# ═══════════════════════════════════════════════════════════════════════════
# DATABASE QUERIES
# ═══════════════════════════════════════════════════════════════════════════

def get_bars_for_date_range(ticker: str, start_date: datetime, end_date: datetime, db_path: str = "market_memory.db") -> List[Dict]:
    """
    Fetch all bars for a ticker within a date range from the database.
    
    Returns:
        List of bar dictionaries with keys: datetime, open, high, low, close, volume
    """
    p = ph()
    conn = get_conn(db_path)
    cursor = dict_cursor(conn)
    
    cursor.execute(f"""
        SELECT datetime, open, high, low, close, volume
        FROM intraday_bars
        WHERE ticker = {p}
          AND datetime >= {p}
          AND datetime <= {p}
        ORDER BY datetime ASC
    """, (ticker, start_date, end_date))
    
    rows = cursor.fetchall()
    conn.close()
    
    bars = []
    for row in rows:
        dt = row["datetime"]
        if isinstance(dt, str):
            dt = datetime.fromisoformat(dt)
        if hasattr(dt, "tzinfo") and dt.tzinfo is not None:
            dt = dt.replace(tzinfo=None)
        
        bars.append({
            "datetime": dt,
            "timestamp": dt,  # Alias for compatibility
            "open": float(row["open"]),
            "high": float(row["high"]),
            "low": float(row["low"]),
            "close": float(row["close"]),
            "volume": int(row["volume"])
        })
    
    return bars


# ═══════════════════════════════════════════════════════════════════════════
# SIGNAL DETECTION - Scan Historical Data for BOS/FVG Patterns
# ═══════════════════════════════════════════════════════════════════════════

def detect_bos_signal(bars: List[Dict], idx: int) -> Optional[Dict]:
    """
    Detect Break of Structure at given bar index.
    
    BOS = Price breaks above recent swing high (bullish) or below swing low (bearish)
    """
    if idx < 20 or idx >= len(bars) - 5:
        return None
    
    current_bar = bars[idx]
    lookback = bars[max(0, idx-20):idx]
    
    if len(lookback) < 10:
        return None
    
    # Find recent swing high/low (past 20 bars)
    highs = [b['high'] for b in lookback]
    lows = [b['low'] for b in lookback]
    
    swing_high = max(highs)
    swing_low = min(lows)
    
    # Bullish BOS: Close breaks above swing high
    if current_bar['close'] > swing_high:
        strength = (current_bar['close'] - swing_high) / swing_high
        return {
            'type': 'BOS',
            'direction': 'CALL',
            'strength': strength,
            'entry_price': current_bar['close']
        }
    
    # Bearish BOS: Close breaks below swing low
    if current_bar['close'] < swing_low:
        strength = (swing_low - current_bar['close']) / swing_low
        return {
            'type': 'BOS',
            'direction': 'PUT',
            'strength': strength,
            'entry_price': current_bar['close']
        }
    
    return None


def detect_fvg_signal(bars: List[Dict], idx: int) -> Optional[Dict]:
    """
    Detect Fair Value Gap at given bar index.
    
    FVG = Gap between bar[i-2] and bar[i] where bar[i-1] doesn't fill it
    """
    if idx < 3 or idx >= len(bars) - 5:
        return None
    
    bar_minus_2 = bars[idx - 2]
    bar_minus_1 = bars[idx - 1]
    current_bar = bars[idx]
    
    # Bullish FVG: Gap up (bar[-2].high < current.low)
    if bar_minus_2['high'] < current_bar['low']:
        gap_size = (current_bar['low'] - bar_minus_2['high']) / bar_minus_2['high']
        
        # Check if gap is significant
        if gap_size >= OPTIMIZED_PARAMS['fvg_size_threshold'] / 100:
            return {
                'type': 'FVG',
                'direction': 'CALL',
                'strength': gap_size,
                'entry_price': current_bar['close']
            }
    
    # Bearish FVG: Gap down (bar[-2].low > current.high)
    if bar_minus_2['low'] > current_bar['high']:
        gap_size = (bar_minus_2['low'] - current_bar['high']) / bar_minus_2['low']
        
        if gap_size >= OPTIMIZED_PARAMS['fvg_size_threshold'] / 100:
            return {
                'type': 'FVG',
                'direction': 'PUT',
                'strength': gap_size,
                'entry_price': current_bar['close']
            }
    
    return None


def scan_historical_signals(ticker: str, days_back: int = 90) -> List[HistoricalSignal]:
    """
    Scan historical data for all BOS/FVG signals in the past N days.
    """
    print(f"[SCAN] Scanning {ticker} for historical signals (past {days_back} days)...")
    
    # Calculate date range
    end_date = datetime.now(ET)
    start_date = end_date - timedelta(days=days_back)
    
    # Get historical bars from database
    bars = get_bars_for_date_range(ticker, start_date, end_date)
    
    if not bars or len(bars) < 100:
        if len(bars) == 0:
            print(f"[SCAN] No data for {ticker}")
        else:
            print(f"[SCAN] Insufficient data for {ticker} ({len(bars)} bars, need 100+)")
        return []
    
    print(f"[SCAN] Loaded {len(bars)} bars for {ticker} from {start_date.date()} to {end_date.date()}")
    
    signals = []
    
    # Scan through each bar looking for patterns
    for idx in range(50, len(bars) - 10):  # Leave buffer on both ends
        bar = bars[idx]
        timestamp = bar.get('datetime') or bar.get('timestamp')
        
        if not timestamp:
            continue
        
        # Detect BOS
        bos = detect_bos_signal(bars, idx)
        if bos:
            signals.append(HistoricalSignal(
                timestamp=timestamp,
                ticker=ticker,
                direction=bos['direction'],
                signal_type=bos['type'],
                entry_price=bos['entry_price'],
                signal_strength=bos['strength'],
                bar_data=bar
            ))
        
        # Detect FVG
        fvg = detect_fvg_signal(bars, idx)
        if fvg:
            signals.append(HistoricalSignal(
                timestamp=timestamp,
                ticker=ticker,
                direction=fvg['direction'],
                signal_type=fvg['type'],
                entry_price=fvg['entry_price'],
                signal_strength=fvg['strength'],
                bar_data=bar
            ))
    
    print(f"[SCAN] Found {len(signals)} signals for {ticker}")
    return signals


# ═══════════════════════════════════════════════════════════════════════════
# FILTER VALIDATION - Apply Optimized Parameters
# ═══════════════════════════════════════════════════════════════════════════

def calculate_rsi(bars: List[Dict], period: int = 14) -> float:
    """Calculate RSI from bars"""
    if len(bars) < period + 1:
        return 50.0
    
    closes = [b['close'] for b in bars[-period-1:]]
    deltas = [closes[i+1] - closes[i] for i in range(len(closes)-1)]
    
    gains = [d if d > 0 else 0 for d in deltas]
    losses = [-d if d < 0 else 0 for d in deltas]
    
    avg_gain = np.mean(gains) if gains else 0
    avg_loss = np.mean(losses) if losses else 0
    
    if avg_loss == 0:
        return 100.0
    
    rs = avg_gain / avg_loss
    rsi = 100 - (100 / (1 + rs))
    
    return rsi


def calculate_mfi(bars: List[Dict], period: int = 14) -> float:
    """Calculate Money Flow Index"""
    if len(bars) < period + 1:
        return 50.0
    
    recent = bars[-period-1:]
    typical_prices = [(b['high'] + b['low'] + b['close']) / 3 for b in recent]
    money_flows = [typical_prices[i] * recent[i]['volume'] for i in range(len(recent))]
    
    positive_flow = sum(money_flows[i] for i in range(1, len(money_flows)) if typical_prices[i] > typical_prices[i-1])
    negative_flow = sum(money_flows[i] for i in range(1, len(money_flows)) if typical_prices[i] < typical_prices[i-1])
    
    if negative_flow == 0:
        return 100.0
    
    money_ratio = positive_flow / negative_flow
    mfi = 100 - (100 / (1 + money_ratio))
    
    return mfi


def validate_signal_simple(signal: HistoricalSignal, bars: List[Dict]) -> Tuple[bool, float]:
    """
    Simplified filter validation using basic technical indicators.
    
    Since we don't have full War Machine context at signal time,
    we'll use simplified versions of the key filters.
    
    Returns:
        (passes_validation, confidence_score)
    """
    try:
        direction = signal.direction
        params = OPTIMIZED_PARAMS
        base_confidence = 0.5
        
        if len(bars) < 50:
            return False, 0.0
        
        # Get recent bars at signal time
        recent_bars = bars[-50:]
        
        # ─────────────────────────────────────────────────────────────────
        # HARD FILTER 1: MFI confirmation (REQUIRED)
        # ─────────────────────────────────────────────────────────────────
        if params['require_mfi_confirm']:
            mfi = calculate_mfi(recent_bars)
            if direction == 'CALL' and mfi > params['mfi_overbought']:
                return False, 0.0
            elif direction == 'PUT' and mfi < params['mfi_oversold']:
                return False, 0.0
        
        # ─────────────────────────────────────────────────────────────────
        # HARD FILTER 2: Volume requirement
        # ─────────────────────────────────────────────────────────────────
        current_volume = recent_bars[-1]['volume']
        avg_volume = np.mean([b['volume'] for b in recent_bars[-20:]])
        
        if avg_volume > 0:
            volume_ratio = current_volume / avg_volume
            if volume_ratio < params['volume_ratio_min']:
                return False, 0.0
        
        # ─────────────────────────────────────────────────────────────────
        # CONFIDENCE ADJUSTMENTS (soft signals)
        # ─────────────────────────────────────────────────────────────────
        confidence_adjustments = []
        
        # Momentum weight (RSI zone)
        rsi = calculate_rsi(recent_bars)
        if direction == 'CALL' and rsi < params['rsi_oversold']:
            confidence_adjustments.append(params['momentum_weight'])
        elif direction == 'PUT' and rsi > params['rsi_overbought']:
            confidence_adjustments.append(params['momentum_weight'])
        elif (direction == 'CALL' and rsi > params['rsi_overbought']) or \
             (direction == 'PUT' and rsi < params['rsi_oversold']):
            confidence_adjustments.append(-params['momentum_weight'])
        
        # Volume bonus
        if volume_ratio >= params['rvol_threshold']:
            confidence_adjustments.append(params['rvol_bonus'])
        
        # Calculate final confidence
        final_confidence = base_confidence + sum(confidence_adjustments)
        final_confidence = max(0.0, min(1.0, final_confidence))
        
        return True, final_confidence
    
    except Exception as e:
        print(f"[VALIDATE] Error validating {signal.ticker} at {signal.timestamp}: {e}")
        return False, 0.0


# ═══════════════════════════════════════════════════════════════════════════
# TRADE SIMULATION - Calculate Outcomes
# ═══════════════════════════════════════════════════════════════════════════

def calculate_atr(bars: List[Dict], period: int = 14) -> float:
    """Calculate Average True Range"""
    if len(bars) < period + 1:
        return 0.0
    
    true_ranges = []
    for i in range(1, len(bars)):
        high = bars[i]['high']
        low = bars[i]['low']
        prev_close = bars[i-1]['close']
        
        tr = max(
            high - low,
            abs(high - prev_close),
            abs(low - prev_close)
        )
        true_ranges.append(tr)
    
    if len(true_ranges) < period:
        return 0.0
    
    return np.mean(true_ranges[-period:])


def simulate_trade_outcome(signal: HistoricalSignal, passed_filter: bool, confidence: float, all_bars: List[Dict]) -> TradeResult:
    """
    Simulate what would have happened if we took this trade.
    
    Logic:
    - Entry: Signal bar close
    - Stop: 3.0 x ATR below entry (or above for PUTs)
    - Targets: 1R, 2R, 3R
    - Exit: First target hit or stop or EOD
    """
    ticker = signal.ticker
    entry_price = signal.entry_price
    entry_time = signal.timestamp
    
    # Find signal bar index
    signal_idx = None
    for i, bar in enumerate(all_bars):
        bar_time = bar.get('datetime') or bar.get('timestamp')
        if bar_time == entry_time:
            signal_idx = i
            break
    
    if signal_idx is None or signal_idx >= len(all_bars) - 5:
        # Can't simulate - no follow-up data
        return TradeResult(
            signal=signal,
            passed_filter=passed_filter,
            confidence_score=confidence,
            entry_price=entry_price,
            stop_price=entry_price,
            exit_price=entry_price,
            exit_reason='NO_DATA',
            r_multiple=0.0,
            pnl_percent=0.0,
            hold_time_minutes=0,
            win=False
        )
    
    # Calculate ATR for stop placement
    atr_bars = all_bars[max(0, signal_idx-50):signal_idx+1]
    atr = calculate_atr(atr_bars)
    
    if atr == 0:
        atr = entry_price * 0.01  # Fallback: 1% ATR
    
    # Set stop and targets
    atr_multiplier = OPTIMIZED_PARAMS['atr_multiplier']
    
    if signal.direction == 'CALL':
        stop_price = entry_price - (atr * atr_multiplier)
        target_1r = entry_price + (atr * atr_multiplier * 1)
        target_2r = entry_price + (atr * atr_multiplier * 2)
        target_3r = entry_price + (atr * atr_multiplier * 3)
    else:  # PUT
        stop_price = entry_price + (atr * atr_multiplier)
        target_1r = entry_price - (atr * atr_multiplier * 1)
        target_2r = entry_price - (atr * atr_multiplier * 2)
        target_3r = entry_price - (atr * atr_multiplier * 3)
    
    # Simulate through subsequent bars
    exit_price = entry_price
    exit_reason = 'EOD'
    hold_time = 0
    
    future_bars = all_bars[signal_idx+1:min(signal_idx+391, len(all_bars))]  # Max 1 trading day (390 mins)
    
    for i, bar in enumerate(future_bars):
        hold_time = i + 1
        high = bar['high']
        low = bar['low']
        close = bar['close']
        
        if signal.direction == 'CALL':
            # Check if stop hit
            if low <= stop_price:
                exit_price = stop_price
                exit_reason = 'STOP_HIT'
                break
            # Check targets (prioritize best exits)
            if high >= target_3r:
                exit_price = target_3r
                exit_reason = 'TARGET_3R'
                break
            elif high >= target_2r:
                exit_price = target_2r
                exit_reason = 'TARGET_2R'
                break
            elif high >= target_1r:
                exit_price = target_1r
                exit_reason = 'TARGET_1R'
                break
        else:  # PUT
            # Check if stop hit
            if high >= stop_price:
                exit_price = stop_price
                exit_reason = 'STOP_HIT'
                break
            # Check targets
            if low <= target_3r:
                exit_price = target_3r
                exit_reason = 'TARGET_3R'
                break
            elif low <= target_2r:
                exit_price = target_2r
                exit_reason = 'TARGET_2R'
                break
            elif low <= target_1r:
                exit_price = target_1r
                exit_reason = 'TARGET_1R'
                break
        
        # EOD exit (if reached end of day)
        if i == len(future_bars) - 1:
            exit_price = close
            exit_reason = 'EOD'
    
    # Calculate results
    if signal.direction == 'CALL':
        pnl_percent = ((exit_price - entry_price) / entry_price) * 100
        r_multiple = (exit_price - entry_price) / (atr * atr_multiplier)
    else:  # PUT
        pnl_percent = ((entry_price - exit_price) / entry_price) * 100
        r_multiple = (entry_price - exit_price) / (atr * atr_multiplier)
    
    win = r_multiple > 0
    
    return TradeResult(
        signal=signal,
        passed_filter=passed_filter,
        confidence_score=confidence,
        entry_price=entry_price,
        stop_price=stop_price,
        exit_price=exit_price,
        exit_reason=exit_reason,
        r_multiple=r_multiple,
        pnl_percent=pnl_percent,
        hold_time_minutes=hold_time,
        win=win
    )


# ═══════════════════════════════════════════════════════════════════════════
# PERFORMANCE ANALYSIS
# ═══════════════════════════════════════════════════════════════════════════

def calculate_metrics(results: List[TradeResult]) -> Dict:
    """Calculate performance metrics"""
    if not results:
        return {
            'total_trades': 0,
            'wins': 0,
            'losses': 0,
            'win_rate': 0.0,
            'avg_r_multiple': 0.0,
            'avg_pnl_percent': 0.0,
            'total_r': 0.0,
            'sharpe_ratio': 0.0,
            'max_drawdown': 0.0,
            'avg_hold_time_minutes': 0.0,
            'best_trade_r': 0.0,
            'worst_trade_r': 0.0,
        }
    
    wins = sum(1 for r in results if r.win)
    losses = len(results) - wins
    win_rate = wins / len(results) if results else 0.0
    
    r_multiples = [r.r_multiple for r in results]
    avg_r = np.mean(r_multiples)
    total_r = sum(r_multiples)
    
    pnl_percents = [r.pnl_percent for r in results]
    avg_pnl = np.mean(pnl_percents)
    
    hold_times = [r.hold_time_minutes for r in results]
    avg_hold = np.mean(hold_times)
    
    # Sharpe ratio
    if len(r_multiples) > 1 and np.std(r_multiples) > 0:
        sharpe = (np.mean(r_multiples) / np.std(r_multiples)) * np.sqrt(252)
    else:
        sharpe = 0.0
    
    # Max drawdown
    cumulative_r = []
    running_total = 0
    for r in r_multiples:
        running_total += r
        cumulative_r.append(running_total)
    
    if cumulative_r:
        peak = cumulative_r[0]
        max_dd = 0
        for val in cumulative_r:
            if val > peak:
                peak = val
            dd = peak - val
            if dd > max_dd:
                max_dd = dd
    else:
        max_dd = 0.0
    
    return {
        'total_trades': len(results),
        'wins': wins,
        'losses': losses,
        'win_rate': win_rate,
        'avg_r_multiple': avg_r,
        'avg_pnl_percent': avg_pnl,
        'total_r': total_r,
        'sharpe_ratio': sharpe,
        'max_drawdown': max_dd,
        'avg_hold_time_minutes': avg_hold,
        'best_trade_r': max(r_multiples) if r_multiples else 0.0,
        'worst_trade_r': min(r_multiples) if r_multiples else 0.0,
    }


# ═══════════════════════════════════════════════════════════════════════════
# MAIN BACKTEST WORKFLOW
# ═══════════════════════════════════════════════════════════════════════════

def main():
    """Run complete historical backtest"""
    print("="*80)
    print("HISTORICAL BACKTEST - OPTIMIZED PARAMETERS")
    print("="*80)
    print(f"Start time: {datetime.now(ET).strftime('%Y-%m-%d %H:%M:%S %Z')}")
    print()
    
    # Define tickers to backtest (top movers from your scanner)
    test_tickers = ['AAPL', 'NVDA', 'TSLA', 'SPY', 'QQQ', 'AMZN', 'MSFT', 'META', 'GOOGL', 'AMD']
    
    print(f"Testing {len(test_tickers)} tickers: {', '.join(test_tickers)}")
    print()
    
    # Scan all tickers for historical signals
    all_signals = []
    ticker_bar_cache = {}  # Cache bars for each ticker
    
    for ticker in test_tickers:
        signals = scan_historical_signals(ticker, days_back=90)
        all_signals.extend(signals)
        
        # Cache bars for later use in validation
        if signals:
            end_date = datetime.now(ET)
            start_date = end_date - timedelta(days=90)
            ticker_bar_cache[ticker] = get_bars_for_date_range(ticker, start_date, end_date)
    
    print()
    print(f"✅ Total signals detected: {len(all_signals)}")
    print()
    
    if len(all_signals) == 0:
        print("❌ No signals found in historical data")
        print("   This likely means:")
        print("   1. Database has data but patterns weren't found, OR")
        print("   2. Pattern detection thresholds are too strict")
        print("")
        print("   Try running: python main.py")
        print("   To populate the database with fresh market data")
        return
    
    # Process each signal through filters and simulation
    print("Processing signals through optimized filters...")
    print()
    
    baseline_results = []  # All signals (no filter)
    optimized_results = []  # Only signals that pass filter
    
    for i, signal in enumerate(all_signals):
        if (i + 1) % 50 == 0:
            print(f"  Processed {i+1}/{len(all_signals)} signals...")
        
        ticker = signal.ticker
        bars = ticker_bar_cache.get(ticker, [])
        
        if not bars:
            continue
        
        # Find bars up to signal time
        signal_time = signal.timestamp
        bars_up_to_signal = [b for b in bars if (b.get('datetime') or b.get('timestamp')) <= signal_time]
        
        if len(bars_up_to_signal) < 50:
            continue
        
        # Validate signal
        passes, confidence = validate_signal_simple(signal, bars_up_to_signal)
        
        # Simulate trade outcome
        result = simulate_trade_outcome(signal, passes, confidence, bars)
        
        # Track results
        baseline_results.append(result)
        if passes:
            optimized_results.append(result)
    
    print(f"  Processed {len(all_signals)}/{len(all_signals)} signals")
    print()
    
    # Calculate metrics
    baseline_metrics = calculate_metrics(baseline_results)
    optimized_metrics = calculate_metrics(optimized_results)
    
    # Display results
    print("="*80)
    print("BACKTEST RESULTS")
    print("="*80)
    print()
    
    print("BASELINE (No Filters):")
    print(f"  Total Signals: {baseline_metrics['total_trades']}")
    print(f"  Win Rate: {baseline_metrics['win_rate']:.1%}")
    print(f"  Avg R-Multiple: {baseline_metrics['avg_r_multiple']:.2f}R")
    print(f"  Total R: {baseline_metrics['total_r']:.2f}R")
    print(f"  Sharpe Ratio: {baseline_metrics['sharpe_ratio']:.2f}")
    print(f"  Max Drawdown: {baseline_metrics['max_drawdown']:.2f}R")
    print(f"  Avg Hold Time: {baseline_metrics['avg_hold_time_minutes']:.0f} minutes")
    print()
    
    print("OPTIMIZED (With Filters):")
    print(f"  Total Signals: {optimized_metrics['total_trades']}")
    if baseline_metrics['total_trades'] > 0:
        filter_rate = (1 - optimized_metrics['total_trades']/baseline_metrics['total_trades'])*100
        print(f"  Signals Filtered Out: {baseline_metrics['total_trades'] - optimized_metrics['total_trades']} ({filter_rate:.1f}%)")
    print(f"  Win Rate: {optimized_metrics['win_rate']:.1%}")
    print(f"  Avg R-Multiple: {optimized_metrics['avg_r_multiple']:.2f}R")
    print(f"  Total R: {optimized_metrics['total_r']:.2f}R")
    print(f"  Sharpe Ratio: {optimized_metrics['sharpe_ratio']:.2f}")
    print(f"  Max Drawdown: {optimized_metrics['max_drawdown']:.2f}R")
    print(f"  Avg Hold Time: {optimized_metrics['avg_hold_time_minutes']:.0f} minutes")
    print()
    
    if baseline_metrics['total_trades'] > 0 and optimized_metrics['total_trades'] > 0:
        print("IMPROVEMENT:")
        if baseline_metrics['win_rate'] > 0:
            win_rate_improvement = ((optimized_metrics['win_rate'] - baseline_metrics['win_rate']) / baseline_metrics['win_rate']) * 100
            print(f"  Win Rate: {win_rate_improvement:+.1f}%")
        if baseline_metrics['avg_r_multiple'] != 0:
            r_improvement = ((optimized_metrics['avg_r_multiple'] - baseline_metrics['avg_r_multiple']) / abs(baseline_metrics['avg_r_multiple'])) * 100
            print(f"  Avg R-Multiple: {r_improvement:+.1f}%")
        if baseline_metrics['sharpe_ratio'] != 0:
            sharpe_improvement = ((optimized_metrics['sharpe_ratio'] - baseline_metrics['sharpe_ratio']) / abs(baseline_metrics['sharpe_ratio'])) * 100
            print(f"  Sharpe Ratio: {sharpe_improvement:+.1f}%")
        print()
    
    # Save detailed results
    output = {
        'timestamp': datetime.now(ET).isoformat(),
        'tickers_tested': test_tickers,
        'days_back': 90,
        'optimized_params': OPTIMIZED_PARAMS,
        'baseline_metrics': baseline_metrics,
        'optimized_metrics': optimized_metrics,
        'total_signals_detected': len(all_signals),
        'signals_passed_filter': len(optimized_results),
        'filter_rejection_rate': 1 - (len(optimized_results) / len(all_signals)) if all_signals else 0,
    }
    
    with open('backtest_results.json', 'w') as f:
        json.dump(output, f, indent=2, default=str)
    
    print("✅ Results saved to: backtest_results.json")
    print()
    print(f"End time: {datetime.now(ET).strftime('%Y-%m-%d %H:%M:%S %Z')}")


if __name__ == "__main__":
    main()
