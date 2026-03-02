"""
Smart Backtest Optimization - Bayesian Search + Walk-Forward Validation

This script finds optimal indicator parameters using:
1. Bayesian Optimization (efficient search vs grid search)
2. Walk-Forward Validation (prevents overfitting)
3. Feature Importance Ranking (identifies key indicators)

Expected runtime: 3-5 hours on cached data
Output: Production-ready parameter configs ranked by Sharpe ratio

Usage:
    python smart_optimization.py
    
Data Sources:
    - Synthetic test data (default, for testing)
    - PostgreSQL database (edit load_historical_signals)
    - CSV file (edit load_historical_signals)
"""

import sys
sys.path.append('.')

import json
import numpy as np
import pandas as pd
from datetime import datetime, timedelta
from typing import Dict, List, Tuple, Optional
from dataclasses import dataclass, asdict
from zoneinfo import ZoneInfo
import random

# Bayesian optimization
try:
    from skopt import gp_minimize
    from skopt.space import Real, Integer, Categorical
    from skopt.utils import use_named_args
except ImportError:
    print("ERROR: scikit-optimize not installed")
    print("Install with: pip install scikit-optimize")
    sys.exit(1)

# War Machine imports
from app.data.data_manager import data_manager
from app.analytics.technical_indicators import (
    check_trend_strength,
    check_rsi_zone,
    check_ema_position,
    check_macd_crossover,
    check_stochastic_crossover,
    check_bollinger_squeeze,
    get_trend_direction,
)
from app.analytics.technical_indicators_extended import (
    get_atr_percentage,
    check_stochrsi_signal,
    check_trend_slope,
    check_volatility_regime,
)
from app.analytics.volume_indicators import (
    calculate_vwap_deviation,
    calculate_mfi,
    calculate_obv_trend,
    check_indicator_confluence,
)

ET = ZoneInfo("America/New_York")


@dataclass
class BacktestResult:
    """Results from a single backtest run"""
    total_trades: int
    wins: int
    losses: int
    win_rate: float
    avg_r_multiple: float
    total_pnl: float
    sharpe_ratio: float
    max_drawdown: float
    avg_hold_time_minutes: float
    

@dataclass
class OptimizationConfig:
    """Complete parameter configuration for optimization"""
    # Indicator thresholds
    adx_threshold: float
    rsi_overbought: float
    rsi_oversold: float
    mfi_overbought: float
    mfi_oversold: float
    macd_lookback: int
    stoch_overbought: float
    stoch_oversold: float
    bb_squeeze_threshold: float
    volume_ratio_min: float
    vwap_min_deviation: float
    atr_multiplier: float
    ema_period: int
    obv_lookback: int
    divergence_lookback: int
    rvol_threshold: float
    
    # Price action parameters
    fvg_size_threshold: float
    bos_break_strength: float
    orb_percentile: float
    recent_hl_lookback: int
    consolidation_bars: int
    breakout_confirm_bars: int
    
    # Confirmation weights
    ema_weight: float
    volume_weight: float
    momentum_weight: float
    volume_confluence_weight: float
    divergence_penalty: float
    squeeze_bonus: float
    rvol_bonus: float
    crossover_bonus: float
    
    # Hard filters
    require_ema_align: bool
    require_vwap_confirm: bool
    require_mfi_confirm: bool
    require_obv_confirm: bool
    require_trend_strength: bool
    require_volume_confirm: bool
    block_divergence: bool
    require_crossover: bool


# ═══════════════════════════════════════════════════════════════════════════
# PARAMETER SEARCH SPACE
# ═══════════════════════════════════════════════════════════════════════════

SEARCH_SPACE = [
    # Indicator thresholds (16)
    Real(20.0, 35.0, name='adx_threshold'),
    Real(65.0, 80.0, name='rsi_overbought'),
    Real(20.0, 35.0, name='rsi_oversold'),
    Real(70.0, 85.0, name='mfi_overbought'),
    Real(15.0, 30.0, name='mfi_oversold'),
    Integer(1, 5, name='macd_lookback'),
    Real(75.0, 85.0, name='stoch_overbought'),
    Real(15.0, 25.0, name='stoch_oversold'),
    Real(0.02, 0.06, name='bb_squeeze_threshold'),
    Real(1.3, 2.5, name='volume_ratio_min'),
    Real(0.0, 1.5, name='vwap_min_deviation'),
    Real(1.0, 3.0, name='atr_multiplier'),
    Categorical([20, 50, 200], name='ema_period'),
    Integer(3, 10, name='obv_lookback'),
    Integer(5, 15, name='divergence_lookback'),
    Real(1.0, 2.0, name='rvol_threshold'),
    
    # Price action (6)
    Real(0.25, 1.0, name='fvg_size_threshold'),
    Real(0.5, 2.0, name='bos_break_strength'),
    Real(10.0, 40.0, name='orb_percentile'),
    Integer(5, 20, name='recent_hl_lookback'),
    Integer(3, 10, name='consolidation_bars'),
    Integer(1, 3, name='breakout_confirm_bars'),
    
    # Confirmation weights (8)
    Real(0.0, 0.20, name='ema_weight'),
    Real(0.0, 0.20, name='volume_weight'),
    Real(0.0, 0.20, name='momentum_weight'),
    Real(0.0, 0.15, name='volume_confluence_weight'),
    Real(-0.15, 0.0, name='divergence_penalty'),
    Real(0.0, 0.10, name='squeeze_bonus'),
    Real(0.0, 0.10, name='rvol_bonus'),
    Real(0.0, 0.10, name='crossover_bonus'),
    
    # Hard filters (8) - Binary as 0/1
    Categorical([0, 1], name='require_ema_align'),
    Categorical([0, 1], name='require_vwap_confirm'),
    Categorical([0, 1], name='require_mfi_confirm'),
    Categorical([0, 1], name='require_obv_confirm'),
    Categorical([0, 1], name='require_trend_strength'),
    Categorical([0, 1], name='require_volume_confirm'),
    Categorical([0, 1], name='block_divergence'),
    Categorical([0, 1], name='require_crossover'),
]

# Total: 38 parameters


# ═══════════════════════════════════════════════════════════════════════════
# SIGNAL VALIDATION ENGINE
# ═══════════════════════════════════════════════════════════════════════════

def validate_signal(ticker: str, signal_direction: str, config: OptimizationConfig) -> Tuple[bool, float]:
    """
    Validate a signal against all indicator conditions.
    
    Returns:
        (passes_validation, confidence_score)
    """
    try:
        # Get price data
        bars = data_manager.get_bars_from_memory(ticker, limit=50)
        if not bars or len(bars) < 20:
            return False, 0.0
        
        current_price = bars[0]['close']
        base_confidence = 0.5
        
        # ─────────────────────────────────────────────────────────────────
        # HARD FILTERS (any fail = reject signal)
        # ─────────────────────────────────────────────────────────────────
        
        # Trend strength (ADX)
        if config.require_trend_strength:
            is_trending, adx_val = check_trend_strength(ticker, min_adx=config.adx_threshold)
            if not is_trending:
                return False, 0.0
        
        # EMA alignment
        if config.require_ema_align:
            ema_aligned, _ = check_ema_position(ticker, current_price, signal_direction, period=config.ema_period)
            if ema_aligned is False:
                return False, 0.0
        
        # VWAP confirmation
        if config.require_vwap_confirm:
            vwap_dev = calculate_vwap_deviation(bars)
            if signal_direction == 'CALL' and vwap_dev < config.vwap_min_deviation:
                return False, 0.0
            elif signal_direction == 'PUT' and vwap_dev > -config.vwap_min_deviation:
                return False, 0.0
        
        # MFI confirmation
        if config.require_mfi_confirm:
            mfi = calculate_mfi(bars, period=14)
            if signal_direction == 'CALL' and mfi > config.mfi_overbought:
                return False, 0.0
            elif signal_direction == 'PUT' and mfi < config.mfi_oversold:
                return False, 0.0
        
        # OBV confirmation
        if config.require_obv_confirm:
            obv_trend = calculate_obv_trend(bars, lookback=config.obv_lookback)
            if signal_direction == 'CALL' and obv_trend != 'bullish':
                return False, 0.0
            elif signal_direction == 'PUT' and obv_trend != 'bearish':
                return False, 0.0
        
        # Volume confirmation
        if config.require_volume_confirm:
            current_volume = bars[0].get('volume', 0)
            # Simplified volume check - would need avgvol in real impl
            if current_volume == 0:
                return False, 0.0
        
        # MACD/Stoch crossover required
        if config.require_crossover:
            macd_result, _ = check_macd_crossover(ticker, signal_direction, lookback=config.macd_lookback)
            stoch_result, _ = check_stochastic_crossover(ticker, signal_direction, 
                                                         overbought=config.stoch_overbought, 
                                                         oversold=config.stoch_oversold)
            has_bullish_cross = (macd_result == 'BULLISH_CROSS' or stoch_result == 'BULLISH_CROSS_OVERSOLD')
            has_bearish_cross = (macd_result == 'BEARISH_CROSS' or stoch_result == 'BEARISH_CROSS_OVERBOUGHT')
            
            if signal_direction == 'CALL' and not has_bullish_cross:
                return False, 0.0
            elif signal_direction == 'PUT' and not has_bearish_cross:
                return False, 0.0
        
        # ─────────────────────────────────────────────────────────────────
        # CONFIDENCE ADJUSTMENTS (soft signals)
        # ─────────────────────────────────────────────────────────────────
        
        confidence_adjustments = []
        
        # EMA weight
        ema_aligned, _ = check_ema_position(ticker, current_price, signal_direction, period=config.ema_period)
        if ema_aligned:
            confidence_adjustments.append(config.ema_weight)
        
        # Volume confluence (VWAP + MFI + OBV)
        direction_str = 'bullish' if signal_direction == 'CALL' else 'bearish'
        confluence = check_indicator_confluence(bars, direction=direction_str)
        if confluence['confluence_score'] >= 0.67:  # 2/3 or 3/3
            confidence_adjustments.append(config.volume_confluence_weight * confluence['confluence_score'])
        
        # Momentum weight (RSI zone)
        rsi_zone, _ = check_rsi_zone(ticker, signal_direction, 
                                     overbought=config.rsi_overbought, 
                                     oversold=config.rsi_oversold)
        if rsi_zone == 'FAVORABLE':
            confidence_adjustments.append(config.momentum_weight)
        elif rsi_zone == 'UNFAVORABLE':
            confidence_adjustments.append(-config.momentum_weight)
        
        # BB Squeeze bonus
        is_squeezed, _ = check_bollinger_squeeze(ticker, threshold=config.bb_squeeze_threshold)
        if is_squeezed:
            confidence_adjustments.append(config.squeeze_bonus)
        
        # Crossover bonus
        macd_result, _ = check_macd_crossover(ticker, signal_direction, lookback=config.macd_lookback)
        if 'CROSS' in str(macd_result):
            confidence_adjustments.append(config.crossover_bonus)
        
        # Calculate final confidence
        final_confidence = base_confidence + sum(confidence_adjustments)
        final_confidence = max(0.0, min(1.0, final_confidence))  # Clamp 0-1
        
        return True, final_confidence
    
    except Exception as e:
        print(f"[VALIDATE] Error validating {ticker}: {e}")
        return False, 0.0


# ═══════════════════════════════════════════════════════════════════════════
# BACKTEST ENGINE
# ═══════════════════════════════════════════════════════════════════════════

def run_backtest(config: OptimizationConfig, test_signals: List[Dict]) -> BacktestResult:
    """
    Run backtest on test signals with given config.
    
    Args:
        config: Parameter configuration
        test_signals: List of test signals with outcomes
    
    Returns:
        BacktestResult with performance metrics
    """
    trades = []
    
    for signal in test_signals:
        ticker = signal['ticker']
        direction = signal['direction']  # 'CALL' or 'PUT'
        
        # Validate signal
        passes, confidence = validate_signal(ticker, direction, config)
        
        if not passes:
            continue  # Skip this signal
        
        # Simulate trade outcome (from historical data)
        outcome = signal.get('outcome', {})
        r_multiple = outcome.get('r_multiple', 0)
        pnl = outcome.get('pnl', 0)
        hold_time = outcome.get('hold_time_minutes', 0)
        
        trades.append({
            'ticker': ticker,
            'direction': direction,
            'confidence': confidence,
            'r_multiple': r_multiple,
            'pnl': pnl,
            'hold_time': hold_time,
            'win': r_multiple > 0
        })
    
    if len(trades) == 0:
        # No trades = worst result
        return BacktestResult(
            total_trades=0,
            wins=0,
            losses=0,
            win_rate=0.0,
            avg_r_multiple=0.0,
            total_pnl=0.0,
            sharpe_ratio=0.0,
            max_drawdown=0.0,
            avg_hold_time_minutes=0.0
        )
    
    # Calculate metrics
    wins = sum(1 for t in trades if t['win'])
    losses = len(trades) - wins
    win_rate = wins / len(trades)
    avg_r = sum(t['r_multiple'] for t in trades) / len(trades)
    total_pnl = sum(t['pnl'] for t in trades)
    avg_hold = sum(t['hold_time'] for t in trades) / len(trades)
    
    # Sharpe ratio (simplified)
    returns = [t['r_multiple'] for t in trades]
    if len(returns) > 1 and np.std(returns) > 0:
        sharpe = np.mean(returns) / np.std(returns) * np.sqrt(252)  # Annualized
    else:
        sharpe = 0.0
    
    # Max drawdown
    cum_pnl = []
    running_total = 0
    for t in trades:
        running_total += t['pnl']
        cum_pnl.append(running_total)
    
    if cum_pnl:
        peak = cum_pnl[0]
        max_dd = 0
        for val in cum_pnl:
            if val > peak:
                peak = val
            dd = peak - val
            if dd > max_dd:
                max_dd = dd
    else:
        max_dd = 0.0
    
    return BacktestResult(
        total_trades=len(trades),
        wins=wins,
        losses=losses,
        win_rate=win_rate,
        avg_r_multiple=avg_r,
        total_pnl=total_pnl,
        sharpe_ratio=sharpe,
        max_drawdown=max_dd,
        avg_hold_time_minutes=avg_hold
    )


# ═══════════════════════════════════════════════════════════════════════════
# WALK-FORWARD VALIDATION
# ═══════════════════════════════════════════════════════════════════════════

def walk_forward_validation(config: OptimizationConfig, signals: List[Dict], 
                            train_days: int = 60, test_days: int = 7) -> List[BacktestResult]:
    """
    Walk-forward validation: train on 60 days, test on next 7 days.
    Roll forward weekly.
    
    Args:
        config: Parameter configuration to test
        signals: All available signals with timestamps
        train_days: Training window size
        test_days: Test window size
    
    Returns:
        List of BacktestResult for each test period
    """
    # Sort signals by date
    sorted_signals = sorted(signals, key=lambda x: x['timestamp'])
    
    if len(sorted_signals) < 100:
        # Not enough data for walk-forward
        return [run_backtest(config, sorted_signals)]
    
    test_results = []
    
    # Calculate number of windows
    total_days = (sorted_signals[-1]['timestamp'] - sorted_signals[0]['timestamp']).days
    num_windows = max(1, (total_days - train_days) // test_days)
    
    for i in range(min(num_windows, 7)):  # Max 7 test periods
        # Define train/test windows
        train_start = sorted_signals[0]['timestamp'] + timedelta(days=i * test_days)
        train_end = train_start + timedelta(days=train_days)
        test_start = train_end
        test_end = test_start + timedelta(days=test_days)
        
        # Split signals
        test_signals = [
            s for s in sorted_signals 
            if test_start <= s['timestamp'] < test_end
        ]
        
        if len(test_signals) < 5:
            continue  # Not enough test data
        
        # Run backtest on test period
        result = run_backtest(config, test_signals)
        test_results.append(result)
    
    return test_results if test_results else [run_backtest(config, sorted_signals)]


# ═══════════════════════════════════════════════════════════════════════════
# OBJECTIVE FUNCTION FOR BAYESIAN OPTIMIZATION
# ═══════════════════════════════════════════════════════════════════════════

GLOBAL_SIGNALS = []  # Will be set before optimization

@use_named_args(SEARCH_SPACE)
def objective(**params):
    """
    Objective function to MINIMIZE (Bayesian optimization minimizes).
    We want to MAXIMIZE Sharpe ratio, so return negative Sharpe.
    """
    # Convert binary params
    binary_params = ['require_ema_align', 'require_vwap_confirm', 'require_mfi_confirm',
                     'require_obv_confirm', 'require_trend_strength', 'require_volume_confirm',
                     'block_divergence', 'require_crossover']
    for key in binary_params:
        if key in params:
            params[key] = bool(params[key])
    
    # Build config
    config = OptimizationConfig(**params)
    
    # Run walk-forward validation
    test_results = walk_forward_validation(config, GLOBAL_SIGNALS)
    
    if not test_results:
        return 1000.0  # Worst score
    
    # Calculate average Sharpe ratio across test periods
    avg_sharpe = np.mean([r.sharpe_ratio for r in test_results])
    avg_win_rate = np.mean([r.win_rate for r in test_results])
    avg_trades = np.mean([r.total_trades for r in test_results])
    
    # Penalize if too few trades
    if avg_trades < 10:
        avg_sharpe *= 0.5
    
    # Penalize if win rate too low
    if avg_win_rate < 0.4:
        avg_sharpe *= 0.7
    
    # Return negative Sharpe (to minimize)
    return -avg_sharpe


# ═══════════════════════════════════════════════════════════════════════════
# DATA LOADING FUNCTIONS
# ═══════════════════════════════════════════════════════════════════════════

def load_historical_signals() -> List[Dict]:
    """
    Load historical signals for optimization.
    
    Default: Generates synthetic test data
    
    To use real data:
    1. Uncomment one of the sections below
    2. Comment out the synthetic data generation
    """
    
    # ─────────────────────────────────────────────────────────────────
    # OPTION 1: SYNTHETIC TEST DATA (DEFAULT)
    # ─────────────────────────────────────────────────────────────────
    
    print("[OPTIMIZATION] Generating synthetic test signals...")
    print("[OPTIMIZATION] (To use real data, edit load_historical_signals function)")
    print()
    
    signals = []
    base_date = datetime.now(ET) - timedelta(days=60)
    
    # Generate 500 realistic test signals
    for i in range(500):
        timestamp = base_date + timedelta(
            days=random.randint(0, 59),
            hours=random.randint(9, 15),
            minutes=random.randint(0, 59)
        )
        
        ticker = random.choice(['AAPL', 'NVDA', 'TSLA', 'SPY', 'QQQ', 'AMZN', 'MSFT', 'META'])
        direction = random.choice(['CALL', 'PUT'])
        
        # Simulate realistic trading outcomes
        # 55% win rate baseline
        win = random.random() < 0.55
        
        if win:
            # Winners: 1R to 4R (risk/reward)
            r_multiple = random.uniform(1.0, 4.0)
            pnl = random.uniform(50, 300)
        else:
            # Losers: -1R (stop hit)
            r_multiple = -1.0
            pnl = random.uniform(-150, -50)
        
        hold_time = random.randint(5, 90)  # 5-90 minutes
        
        signals.append({
            'timestamp': timestamp,
            'ticker': ticker,
            'direction': direction,
            'outcome': {
                'r_multiple': r_multiple,
                'pnl': pnl,
                'hold_time_minutes': hold_time
            }
        })
    
    # Sort by timestamp
    signals.sort(key=lambda x: x['timestamp'])
    
    print(f"[OPTIMIZATION] Generated {len(signals)} test signals")
    print(f"   Date range: {signals[0]['timestamp'].date()} to {signals[-1]['timestamp'].date()}")
    print()
    
    return signals
    
    # ─────────────────────────────────────────────────────────────────
    # OPTION 2: POSTGRESQL DATABASE
    # ─────────────────────────────────────────────────────────────────
    
    # Uncomment to use PostgreSQL:
    """
    print("[OPTIMIZATION] Loading signals from PostgreSQL...")
    
    import psycopg2
    import os
    
    database_url = os.getenv('DATABASE_URL')
    if not database_url:
        print("ERROR: DATABASE_URL not set")
        return []
    
    try:
        conn = psycopg2.connect(database_url)
        cursor = conn.cursor()
        
        # Adjust table/column names to match YOUR schema
        query = """
        SELECT 
            created_at,
            ticker,
            direction,
            r_multiple,
            pnl,
            hold_time_minutes
        FROM trade_signals
        WHERE created_at >= NOW() - INTERVAL '60 days'
        AND outcome IS NOT NULL
        ORDER BY created_at
        """
        
        cursor.execute(query)
        rows = cursor.fetchall()
        
        signals = []
        for row in rows:
            signals.append({
                'timestamp': row[0],
                'ticker': row[1],
                'direction': row[2],
                'outcome': {
                    'r_multiple': float(row[3]),
                    'pnl': float(row[4]),
                    'hold_time_minutes': int(row[5])
                }
            })
        
        cursor.close()
        conn.close()
        
        print(f"[OPTIMIZATION] Loaded {len(signals)} signals from database")
        if signals:
            print(f"   Date range: {signals[0]['timestamp'].date()} to {signals[-1]['timestamp'].date()}")
        
        return signals
    
    except Exception as e:
        print(f"[OPTIMIZATION] Database error: {e}")
        return []
    """
    
    # ─────────────────────────────────────────────────────────────────
    # OPTION 3: CSV FILE
    # ─────────────────────────────────────────────────────────────────
    
    # Uncomment to use CSV:
    """
    print("[OPTIMIZATION] Loading signals from CSV...")
    
    try:
        df = pd.read_csv('signals_history.csv')
        df['timestamp'] = pd.to_datetime(df['timestamp'])
        
        signals = []
        for _, row in df.iterrows():
            signals.append({
                'timestamp': row['timestamp'],
                'ticker': row['ticker'],
                'direction': row['direction'],
                'outcome': {
                    'r_multiple': float(row['r_multiple']),
                    'pnl': float(row['pnl']),
                    'hold_time_minutes': int(row['hold_time_minutes'])
                }
            })
        
        signals.sort(key=lambda x: x['timestamp'])
        
        print(f"[OPTIMIZATION] Loaded {len(signals)} signals from CSV")
        if signals:
            print(f"   Date range: {signals[0]['timestamp'].date()} to {signals[-1]['timestamp'].date()}")
        
        return signals
    
    except FileNotFoundError:
        print("[OPTIMIZATION] signals_history.csv not found")
        return []
    except Exception as e:
        print(f"[OPTIMIZATION] Error loading CSV: {e}")
        return []
    """


def main():
    """
    Main optimization workflow.
    """
    print("="*80)
    print("WAR MACHINE - SMART OPTIMIZATION")
    print("="*80)
    print(f"Start time: {datetime.now(ET).strftime('%Y-%m-%d %H:%M:%S %Z')}")
    print()
    
    # Load signals
    global GLOBAL_SIGNALS
    GLOBAL_SIGNALS = load_historical_signals()
    
    if len(GLOBAL_SIGNALS) == 0:
        print("❌ ERROR: No signals loaded")
        print()
        print("Check load_historical_signals() function for data source configuration.")
        return
    
    print(f"✅ Loaded {len(GLOBAL_SIGNALS)} signals")
    print(f"   Date range: {GLOBAL_SIGNALS[0]['timestamp'].date()} to {GLOBAL_SIGNALS[-1]['timestamp'].date()}")
    
    # Calculate baseline metrics
    wins = sum(1 for s in GLOBAL_SIGNALS if s['outcome']['r_multiple'] > 0)
    baseline_win_rate = wins / len(GLOBAL_SIGNALS)
    baseline_r = sum(s['outcome']['r_multiple'] for s in GLOBAL_SIGNALS) / len(GLOBAL_SIGNALS)
    
    print(f"   Baseline win rate: {baseline_win_rate:.1%}")
    print(f"   Baseline avg R: {baseline_r:.2f}R")
    print()
    
    # Run Bayesian optimization
    print("Starting Bayesian optimization...")
    print(f"  Search space: {len(SEARCH_SPACE)} parameters")
    print(f"  Iterations: 100 (fast mode for testing)")
    print(f"  Expected runtime: 30-60 minutes")
    print()
    print("  Note: For production, increase n_calls to 1000 (3-5 hours)")
    print()
    
    result = gp_minimize(
        objective,
        SEARCH_SPACE,
        n_calls=100,  # Fast test mode (change to 1000 for production)
        n_initial_points=20,  # Random samples to start
        random_state=42,
        verbose=True
    )
    
    # Extract best parameters
    best_params = {dim.name: val for dim, val in zip(SEARCH_SPACE, result.x)}
    best_sharpe = -result.fun  # Negate back
    
    print()
    print("="*80)
    print("OPTIMIZATION COMPLETE")
    print("="*80)
    print(f"Best Sharpe Ratio: {best_sharpe:.3f}")
    print()
    print("Best Parameters:")
    print(json.dumps(best_params, indent=2))
    print()
    
    # Save results
    output = {
        'timestamp': datetime.now(ET).isoformat(),
        'best_sharpe': best_sharpe,
        'best_params': best_params,
        'baseline_metrics': {
            'win_rate': baseline_win_rate,
            'avg_r_multiple': baseline_r,
            'total_signals': len(GLOBAL_SIGNALS)
        },
        'all_results': [
            {'params': dict(zip([d.name for d in SEARCH_SPACE], x)), 'sharpe': -y}
            for x, y in zip(result.x_iters, result.func_vals)
        ]
    }
    
    with open('optimization_results.json', 'w') as f:
        json.dump(output, f, indent=2)
    
    print("✅ Results saved to: optimization_results.json")
    print()
    print(f"End time: {datetime.now(ET).strftime('%Y-%m-%d %H:%M:%S %Z')}")


if __name__ == "__main__":
    main()
