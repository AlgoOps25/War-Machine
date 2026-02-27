#!/usr/bin/env python3
"""
Comprehensive Parameter Optimization System

Tests EVERY available EODHD data point for optimal BOS/FVG signal detection:

1. CORE EODHD DATA:
   - OHLCV (Open, High, Low, Close, Volume)
   - Intraday bars (1-minute)
   - Previous day OHLC (PDH, PDL, PDC)
   - VIX level (volatility regime)

2. DERIVED INDICATORS:
   - ATR (Average True Range)
   - Volume ratio (current/average)
   - Momentum (rate of change)
   - Gap size (open vs prev close)
   - Trend direction (HH/LL detection)
   - Relative strength (vs SPY)
   - Breakout strength (distance from structure)

3. PARAMETER GRID:
   - Volume multipliers: 1.5x, 2.0x, 2.5x, 3.0x, 4.0x
   - ATR stop multiples: 1.0, 1.5, 2.0, 2.5, 3.0
   - Risk/Reward ratios: 1.5, 2.0, 2.5, 3.0, 4.0
   - Lookback periods: 8, 10, 12, 16, 20, 24
   - Momentum filters: None, Weak (>0), Strong (>0.5%)
   - Trend filters: None, Same direction only
   - Gap filters: None, Small (>0.1%), Large (>0.5%)
   - VIX filters: None, Low (<15), Normal (15-25), High (>25)
   - Time filters: All day, Morning (9:30-11), Midday (11-15), Power (15-16)
   - PDH/PDL: Ignore, Require breakout, Filter against

Usage:
    python comprehensive_optimization.py

Outputs:
    - comprehensive_results.csv (all parameter combinations)
    - top_20_configs.json (best performing setups)
    - optimization_report.txt (detailed analysis)
"""
import sys
from datetime import datetime, timedelta, time as dtime
from zoneinfo import ZoneInfo
from typing import List, Dict, Optional, Tuple
import pandas as pd
import numpy as np
import json
from itertools import product
import time as time_module

from data_manager import DataManager
from db_connection import get_conn, ph, dict_cursor

ET = ZoneInfo("America/New_York")

# Test with liquid tickers
TICKERS = [
    "SPY", "QQQ", "AAPL", "MSFT", "NVDA", "TSLA", "META", "AMD",
    "GOOGL", "AMZN", "NFLX", "INTC", "PLTR", "COIN", "SOFI"
]


class ComprehensiveOptimizer:
    """Test all EODHD data points for optimal parameters."""
    
    def __init__(self, db_path: str = "market_memory.db", days: int = 10):
        self.db_path = db_path
        self.data_manager = DataManager(db_path)
        
        now_et = datetime.now(ET)
        self.end_date = now_et.date()
        self.start_date = (now_et - timedelta(days=days)).date()
        
        print(f"\n{'='*70}")
        print("COMPREHENSIVE PARAMETER OPTIMIZATION")
        print(f"{'='*70}")
        print(f"Period: {self.start_date} to {self.end_date}")
        print(f"Tickers: {len(TICKERS)}")
        print(f"{'='*70}\n")
        
        # Load all bars into memory
        print("⏳ Loading bars into memory...")
        self.bars_cache = {}
        for ticker in TICKERS:
            bars = self._load_bars(ticker)
            if bars:
                self.bars_cache[ticker] = bars
                print(f"  ✅ {ticker}: {len(bars):,} bars")
        
        total_bars = sum(len(b) for b in self.bars_cache.values())
        print(f"\n✅ Cached {len(self.bars_cache)} tickers with {total_bars:,} total bars\n")
        
        # Load previous day data for PDH/PDL testing
        print("⏳ Loading previous day OHLC data...")
        self.prev_day_cache = {}
        for ticker in TICKERS:
            prev_day = self.data_manager.get_previous_day_ohlc(ticker)
            if prev_day:
                self.prev_day_cache[ticker] = prev_day
                print(f"  ✅ {ticker} PDH: ${prev_day['high']:.2f} PDL: ${prev_day['low']:.2f}")
        print()
        
        # Get VIX level for volatility regime
        self.vix_level = self.data_manager.get_vix_level()
        if self.vix_level:
            regime = "Low" if self.vix_level < 15 else "High" if self.vix_level > 25 else "Normal"
            print(f"📉 Current VIX: {self.vix_level:.2f} ({regime} volatility)\n")
    
    def _load_bars(self, ticker: str) -> List[Dict]:
        """Load intraday bars from database."""
        try:
            conn = get_conn(self.db_path)
            cur = dict_cursor(conn)
            
            query = f"""
            SELECT datetime, open, high, low, close, volume
            FROM intraday_bars
            WHERE ticker = {ph()}
              AND datetime >= {ph()}
              AND datetime <= {ph()}
            ORDER BY datetime
            """
            
            cur.execute(query, (ticker, self.start_date, self.end_date))
            rows = cur.fetchall()
            conn.close()
            
            if not rows:
                return []
            
            bars = []
            for row in rows:
                dt = row["datetime"]
                if isinstance(dt, str):
                    dt = datetime.fromisoformat(dt)
                if hasattr(dt, "tzinfo") and dt.tzinfo is not None:
                    dt = dt.replace(tzinfo=None)
                
                bars.append({
                    "datetime": dt,
                    "open": float(row["open"]),
                    "high": float(row["high"]),
                    "low": float(row["low"]),
                    "close": float(row["close"]),
                    "volume": int(row["volume"])
                })
            
            return bars
        except Exception as e:
            print(f"Error loading {ticker}: {e}")
            return []
    
    # ==================== INDICATOR CALCULATIONS ====================
    
    def _calculate_atr(self, bars: List[Dict], period: int = 14) -> float:
        """Calculate Average True Range."""
        if len(bars) < period + 1:
            return 0
        
        tr_values = []
        for i in range(1, len(bars)):
            high = bars[i]['high']
            low = bars[i]['low']
            prev_close = bars[i-1]['close']
            
            tr = max(
                high - low,
                abs(high - prev_close),
                abs(low - prev_close)
            )
            tr_values.append(tr)
        
        return np.mean(tr_values[-period:]) if tr_values else 0
    
    def _calculate_avg_volume(self, bars: List[Dict], period: int = 20) -> float:
        """Calculate average volume over period."""
        if len(bars) < period:
            return 0
        
        volumes = [b['volume'] for b in bars[-period:]]
        return np.mean(volumes)
    
    def _calculate_momentum(self, bars: List[Dict], period: int = 5) -> float:
        """Calculate momentum (ROC - Rate of Change)."""
        if len(bars) < period:
            return 0
        
        current_close = bars[-1]['close']
        past_close = bars[-period]['close']
        return (current_close - past_close) / past_close
    
    def _calculate_gap_size(self, current_bar: Dict, prev_bar: Dict) -> float:
        """Calculate gap percentage between bars."""
        if prev_bar['close'] == 0:
            return 0
        return abs(current_bar['open'] - prev_bar['close']) / prev_bar['close']
    
    def _detect_trend(self, bars: List[Dict], lookback: int) -> Tuple[bool, str]:
        """Detect trend direction (higher highs or lower lows)."""
        if len(bars) < lookback:
            return False, 'none'
        
        recent_bars = bars[-lookback:]
        highs = [b['high'] for b in recent_bars]
        lows = [b['low'] for b in recent_bars]
        
        # Uptrend: Higher highs
        higher_highs = highs[-1] > max(highs[:-1]) if len(highs) > 1 else False
        # Downtrend: Lower lows
        lower_lows = lows[-1] < min(lows[:-1]) if len(lows) > 1 else False
        
        if higher_highs:
            return True, 'up'
        elif lower_lows:
            return True, 'down'
        return False, 'none'
    
    def _calculate_relative_strength(self, ticker: str, bars: List[Dict]) -> float:
        """Calculate relative strength vs SPY."""
        if ticker == 'SPY' or 'SPY' not in self.bars_cache:
            return 0
        
        if len(bars) < 20 or len(self.bars_cache['SPY']) < 20:
            return 0
        
        # Compare recent performance
        ticker_change = (bars[-1]['close'] - bars[-20]['close']) / bars[-20]['close']
        spy_bars = self.bars_cache['SPY']
        spy_change = (spy_bars[-1]['close'] - spy_bars[-20]['close']) / spy_bars[-20]['close']
        
        return ticker_change - spy_change
    
    def _calculate_breakout_strength(self, price: float, level: float) -> float:
        """Calculate breakout strength (% above/below level)."""
        if level == 0:
            return 0
        return abs(price - level) / level
    
    def _check_pdh_pdl(self, ticker: str, price: float, direction: str) -> Tuple[bool, str]:
        """Check if price is breaking PDH/PDL."""
        if ticker not in self.prev_day_cache:
            return False, 'none'
        
        prev_day = self.prev_day_cache[ticker]
        pdh = prev_day['high']
        pdl = prev_day['low']
        
        if direction == 'long' and price > pdh:
            return True, 'above_pdh'
        elif direction == 'short' and price < pdl:
            return True, 'below_pdl'
        
        return False, 'none'
    
    def _check_vix_filter(self, vix_filter: str) -> bool:
        """Check if current VIX matches filter criteria."""
        if not self.vix_level or vix_filter == 'none':
            return True
        
        if vix_filter == 'low' and self.vix_level < 15:
            return True
        elif vix_filter == 'normal' and 15 <= self.vix_level <= 25:
            return True
        elif vix_filter == 'high' and self.vix_level > 25:
            return True
        
        return False
    
    def _check_time_filter(self, dt: datetime, time_filter: str) -> bool:
        """Check if time matches filter criteria."""
        if time_filter == 'all':
            return True
        
        current_time = dt.time()
        
        if time_filter == 'morning':
            return dtime(9, 30) <= current_time <= dtime(11, 0)
        elif time_filter == 'midday':
            return dtime(11, 0) < current_time <= dtime(15, 0)
        elif time_filter == 'power':
            return dtime(15, 0) < current_time <= dtime(16, 0)
        
        return True
    
    # ==================== SIGNAL DETECTION ====================
    
    def detect_signal(self, ticker: str, bars: List[Dict], params: Dict) -> Optional[Dict]:
        """Detect breakout signal with comprehensive parameter testing."""
        if len(bars) < params['lookback'] + 20:  # Need extra for indicators
            return None
        
        current = bars[-1]
        prev = bars[-2]
        
        # Calculate all indicators
        atr = self._calculate_atr(bars)
        avg_volume = self._calculate_avg_volume(bars)
        momentum = self._calculate_momentum(bars, period=5)
        gap_pct = self._calculate_gap_size(current, prev)
        is_trending, trend_dir = self._detect_trend(bars, params['lookback'])
        rel_strength = self._calculate_relative_strength(ticker, bars)
        
        if atr == 0 or avg_volume == 0:
            return None
        
        # FILTER 1: Volume confirmation
        volume_ratio = current['volume'] / avg_volume
        if volume_ratio < params['volume_mult']:
            return None
        
        # FILTER 2: Time-of-day
        if not self._check_time_filter(current['datetime'], params['time_filter']):
            return None
        
        # FILTER 3: VIX regime
        if not self._check_vix_filter(params['vix_filter']):
            return None
        
        # Find structure levels (support/resistance)
        lookback_bars = bars[-params['lookback']-1:-1]
        highs = [b['high'] for b in lookback_bars]
        lows = [b['low'] for b in lookback_bars]
        
        resistance = max(highs)
        support = min(lows)
        
        signal = None
        
        # ==================== BULLISH BREAKOUT ====================
        if current['close'] > resistance:
            breakout_strength = self._calculate_breakout_strength(current['close'], resistance)
            
            # FILTER 4: Momentum
            if params['momentum_filter'] == 'strong' and momentum <= 0.005:
                return None
            elif params['momentum_filter'] == 'weak' and momentum <= 0:
                return None
            
            # FILTER 5: Trend alignment
            if params['trend_filter'] and not (is_trending and trend_dir == 'up'):
                return None
            
            # FILTER 6: Gap size
            if params['gap_filter'] == 'small' and gap_pct < 0.001:
                return None
            elif params['gap_filter'] == 'large' and gap_pct < 0.005:
                return None
            
            # FILTER 7: PDH/PDL
            pdh_break, pdh_status = self._check_pdh_pdl(ticker, current['close'], 'long')
            if params['pdh_filter'] == 'require' and not pdh_break:
                return None
            elif params['pdh_filter'] == 'against' and pdh_break:
                return None
            
            # FILTER 8: Relative strength
            if params['rs_filter'] and rel_strength < 0:
                return None
            
            # Calculate entry, stop, target
            entry = current['close']
            stop = entry - (atr * params['atr_stop_mult'])
            risk_amount = atr * params['atr_stop_mult']
            target = entry + (risk_amount * params['risk_reward'])
            
            signal = {
                'ticker': ticker,
                'direction': 'long',
                'entry': entry,
                'stop': stop,
                'target': target,
                'datetime': current['datetime'],
                'indicators': {
                    'volume_ratio': volume_ratio,
                    'momentum': momentum,
                    'gap_pct': gap_pct,
                    'trend': trend_dir,
                    'breakout_strength': breakout_strength,
                    'rel_strength': rel_strength,
                    'pdh_status': pdh_status
                }
            }
        
        # ==================== BEARISH BREAKOUT ====================
        elif current['close'] < support:
            breakout_strength = self._calculate_breakout_strength(current['close'], support)
            
            # FILTER 4: Momentum
            if params['momentum_filter'] == 'strong' and momentum >= -0.005:
                return None
            elif params['momentum_filter'] == 'weak' and momentum >= 0:
                return None
            
            # FILTER 5: Trend alignment
            if params['trend_filter'] and not (is_trending and trend_dir == 'down'):
                return None
            
            # FILTER 6: Gap size
            if params['gap_filter'] == 'small' and gap_pct < 0.001:
                return None
            elif params['gap_filter'] == 'large' and gap_pct < 0.005:
                return None
            
            # FILTER 7: PDH/PDL
            pdh_break, pdh_status = self._check_pdh_pdl(ticker, current['close'], 'short')
            if params['pdh_filter'] == 'require' and not pdh_break:
                return None
            elif params['pdh_filter'] == 'against' and pdh_break:
                return None
            
            # FILTER 8: Relative strength
            if params['rs_filter'] and rel_strength > 0:
                return None
            
            # Calculate entry, stop, target
            entry = current['close']
            stop = entry + (atr * params['atr_stop_mult'])
            risk_amount = atr * params['atr_stop_mult']
            target = entry - (risk_amount * params['risk_reward'])
            
            signal = {
                'ticker': ticker,
                'direction': 'short',
                'entry': entry,
                'stop': stop,
                'target': target,
                'datetime': current['datetime'],
                'indicators': {
                    'volume_ratio': volume_ratio,
                    'momentum': momentum,
                    'gap_pct': gap_pct,
                    'trend': trend_dir,
                    'breakout_strength': breakout_strength,
                    'rel_strength': rel_strength,
                    'pdh_status': pdh_status
                }
            }
        
        return signal
    
    # ==================== TRADE SIMULATION ====================
    
    def simulate_trade(self, signal: Dict, bars: List[Dict]) -> Optional[Dict]:
        """Simulate trade from entry to exit."""
        entry_idx = next((i for i, b in enumerate(bars) 
                         if b["datetime"] == signal["datetime"]), None)
        
        if entry_idx is None or entry_idx >= len(bars) - 1:
            return None
        
        entry = signal['entry']
        stop = signal['stop']
        target = signal['target']
        direction = signal['direction']
        
        # Simulate forward (max 30 bars = 30 minutes)
        for i in range(entry_idx + 1, min(entry_idx + 30, len(bars))):
            bar = bars[i]
            
            if direction == 'long':
                if bar['low'] <= stop:
                    return {
                        'exit_price': stop,
                        'exit_reason': 'stop',
                        'pnl': stop - entry,
                        'bars_held': i - entry_idx,
                        'exit_time': bar['datetime']
                    }
                if bar['high'] >= target:
                    return {
                        'exit_price': target,
                        'exit_reason': 'target',
                        'pnl': target - entry,
                        'bars_held': i - entry_idx,
                        'exit_time': bar['datetime']
                    }
            else:  # short
                if bar['high'] >= stop:
                    return {
                        'exit_price': stop,
                        'exit_reason': 'stop',
                        'pnl': entry - stop,
                        'bars_held': i - entry_idx,
                        'exit_time': bar['datetime']
                    }
                if bar['low'] <= target:
                    return {
                        'exit_price': target,
                        'exit_reason': 'target',
                        'pnl': entry - target,
                        'bars_held': i - entry_idx,
                        'exit_time': bar['datetime']
                    }
        
        # Timeout - close at current price
        last_bar = bars[min(entry_idx + 30, len(bars) - 1)]
        exit_price = last_bar['close']
        
        if direction == 'long':
            pnl = exit_price - entry
        else:
            pnl = entry - exit_price
        
        return {
            'exit_price': exit_price,
            'exit_reason': 'timeout',
            'pnl': pnl,
            'bars_held': min(30, len(bars) - entry_idx - 1),
            'exit_time': last_bar['datetime']
        }
    
    # ==================== PARAMETER TESTING ====================
    
    def test_parameters(self, params: Dict) -> Dict:
        """Test single parameter combination across all tickers."""
        trades = []
        
        for ticker, bars in self.bars_cache.items():
            # Scan through bars looking for signals
            i = params['lookback'] + 20
            while i < len(bars):
                bars_slice = bars[:i+1]
                signal = self.detect_signal(ticker, bars_slice, params)
                
                if signal:
                    result = self.simulate_trade(signal, bars)
                    
                    if result:
                        trade = {
                            'ticker': ticker,
                            'entry_time': signal['datetime'],
                            'exit_time': result['exit_time'],
                            'direction': signal['direction'],
                            'entry': signal['entry'],
                            'exit': result['exit_price'],
                            'stop': signal['stop'],
                            'target': signal['target'],
                            'pnl': result['pnl'],
                            'pnl_pct': (result['pnl'] / signal['entry']) * 100,
                            'exit_reason': result['exit_reason'],
                            'bars_held': result['bars_held']
                        }
                        trades.append(trade)
                        
                        # Skip forward to avoid overlapping signals
                        i += 15
                        continue
                
                i += 1
        
        # Calculate performance metrics
        if not trades:
            return {
                'params': params,
                'total_trades': 0,
                'winners': 0,
                'losers': 0,
                'win_rate': 0,
                'profit_factor': 0,
                'total_pnl': 0,
                'avg_pnl': 0,
                'avg_win': 0,
                'avg_loss': 0,
                'max_win': 0,
                'max_loss': 0,
                'avg_bars_held': 0
            }
        
        winners = [t for t in trades if t['pnl'] > 0]
        losers = [t for t in trades if t['pnl'] <= 0]
        
        total_trades = len(trades)
        win_count = len(winners)
        loss_count = len(losers)
        win_rate = (win_count / total_trades) * 100
        total_pnl = sum(t['pnl'] for t in trades)
        avg_pnl = total_pnl / total_trades
        
        avg_win = np.mean([t['pnl'] for t in winners]) if winners else 0
        avg_loss = np.mean([t['pnl'] for t in losers]) if losers else 0
        max_win = max([t['pnl'] for t in winners]) if winners else 0
        max_loss = min([t['pnl'] for t in losers]) if losers else 0
        
        if loss_count > 0 and avg_loss != 0:
            profit_factor = abs((win_count * avg_win) / (loss_count * avg_loss))
        elif win_count > 0:
            profit_factor = float('inf')
        else:
            profit_factor = 0
        
        avg_bars_held = np.mean([t['bars_held'] for t in trades])
        
        return {
            'params': params,
            'total_trades': total_trades,
            'winners': win_count,
            'losers': loss_count,
            'win_rate': win_rate,
            'profit_factor': profit_factor,
            'total_pnl': total_pnl,
            'avg_pnl': avg_pnl,
            'avg_win': avg_win,
            'avg_loss': avg_loss,
            'max_win': max_win,
            'max_loss': max_loss,
            'avg_bars_held': avg_bars_held
        }
    
    # ==================== OPTIMIZATION RUNNER ====================
    
    def run_optimization(self) -> pd.DataFrame:
        """Run comprehensive parameter grid search."""
        print(f"{'='*70}")
        print("BUILDING PARAMETER GRID")
        print(f"{'='*70}\n")
        
        # Define comprehensive parameter grid
        param_grid = {
            # Core parameters
            'volume_mult': [2.0, 2.5, 3.0],
            'atr_stop_mult': [1.5, 2.0, 2.5],
            'risk_reward': [2.0, 2.5, 3.0],
            'lookback': [12, 16, 20],
            
            # Filters
            'momentum_filter': ['none', 'weak'],
            'trend_filter': [False, True],
            'gap_filter': ['none'],
            'vix_filter': ['none'],
            'time_filter': ['all', 'morning', 'power'],
            'pdh_filter': ['none'],
            'rs_filter': [False]
        }
        
        # Generate all combinations
        keys = param_grid.keys()
        values = param_grid.values()
        combinations = [dict(zip(keys, v)) for v in product(*values)]
        
        total = len(combinations)
        print(f"✅ Generated {total:,} parameter combinations\n")
        print(f"{'='*70}")
        print("TESTING PARAMETERS")
        print(f"{'='*70}\n")
        
        results = []
        start_time = time_module.time()
        
        for idx, params in enumerate(combinations, 1):
            test_start = time_module.time()
            
            result = self.test_parameters(params)
            results.append(result)
            
            test_duration = time_module.time() - test_start
            elapsed = time_module.time() - start_time
            avg_time = elapsed / idx
            remaining = (total - idx) * avg_time
            
            if result['total_trades'] > 0:
                print(
                    f"[{idx}/{total}] "
                    f"Vol={params['volume_mult']:.1f}x "
                    f"ATR={params['atr_stop_mult']:.1f} "
                    f"RR={params['risk_reward']:.1f} "
                    f"LB={params['lookback']} | "
                    f"Trades: {result['total_trades']} "
                    f"WR: {result['win_rate']:.1f}% "
                    f"PF: {result['profit_factor']:.2f} "
                    f"P&L: ${result['total_pnl']:.2f} | "
                    f"{test_duration:.1f}s | "
                    f"ETA: {remaining/60:.1f}m"
                )
        
        print(f"\n{'='*70}")
        print("✅ OPTIMIZATION COMPLETE")
        print(f"{'='*70}\n")
        
        return pd.DataFrame(results)


def main():
    """Run comprehensive optimization and save results."""
    optimizer = ComprehensiveOptimizer(days=10)
    results_df = optimizer.run_optimization()
    
    # Save all results
    results_df.to_csv("comprehensive_results.csv", index=False)
    print("💾 Saved comprehensive_results.csv\n")
    
    # Filter to meaningful configs (minimum 20 trades)
    meaningful = results_df[results_df['total_trades'] >= 20]
    
    if len(meaningful) == 0:
        print("⚠️ No configurations with 20+ trades found!\n")
        top_20 = results_df.nlargest(20, 'total_pnl')
    else:
        # Sort by total P&L
        profitable = meaningful[meaningful['total_pnl'] > 0]
        
        if len(profitable) == 0:
            print("⚠️ No profitable configurations found!\n")
            top_20 = meaningful.nlargest(20, 'total_pnl')
        else:
            print(f"✅ Found {len(profitable)} profitable configurations!\n")
            top_20 = profitable.nlargest(20, 'total_pnl')
    
    # Print top 20
    print(f"{'='*70}")
    print("TOP 20 PARAMETER COMBINATIONS")
    print(f"{'='*70}\n")
    
    for idx, row in enumerate(top_20.iterrows(), 1):
        result = row[1]
        params = result['params']
        
        print(f"#{idx}")
        print(f"  Volume: {params['volume_mult']:.1f}x | "
              f"ATR Stop: {params['atr_stop_mult']:.1f} | "
              f"R:R: {params['risk_reward']:.1f}:1 | "
              f"Lookback: {params['lookback']}")
        print(f"  Momentum: {params['momentum_filter']} | "
              f"Trend: {'Yes' if params['trend_filter'] else 'No'} | "
              f"Time: {params['time_filter']}")
        print(f"  ---")
        print(f"  Trades: {result['total_trades']} "
              f"({result['winners']}W / {result['losers']}L)")
        print(f"  Win Rate: {result['win_rate']:.1f}%")
        print(f"  Profit Factor: {result['profit_factor']:.2f}")
        print(f"  Total P&L: ${result['total_pnl']:.2f}")
        print(f"  Avg Win: ${result['avg_win']:.2f} | "
              f"Avg Loss: ${result['avg_loss']:.2f}")
        print(f"  Avg Hold: {result['avg_bars_held']:.1f} bars\n")
    
    # Save top configs
    top_configs = []
    for idx, row in enumerate(top_20.iterrows(), 1):
        result = row[1]
        top_configs.append({
            'rank': idx,
            'params': result['params'],
            'metrics': {
                'total_trades': int(result['total_trades']),
                'win_rate': float(result['win_rate']),
                'profit_factor': float(result['profit_factor']),
                'total_pnl': float(result['total_pnl']),
                'avg_win': float(result['avg_win']),
                'avg_loss': float(result['avg_loss'])
            }
        })
    
    with open('top_20_configs.json', 'w') as f:
        json.dump(top_configs, f, indent=2, default=str)
    
    print("💾 Saved top_20_configs.json")
    
    # Create optimization report
    with open('optimization_report.txt', 'w') as f:
        f.write("COMPREHENSIVE PARAMETER OPTIMIZATION REPORT\n")
        f.write("="*70 + "\n\n")
        f.write(f"Total Configurations Tested: {len(results_df)}\n")
        f.write(f"Configurations with 20+ Trades: {len(meaningful)}\n")
        if len(profitable) > 0:
            f.write(f"Profitable Configurations: {len(profitable)}\n")
        f.write(f"\nBest Configuration:\n")
        if len(top_20) > 0:
            best = top_20.iloc[0]
            f.write(f"  Total P&L: ${best['total_pnl']:.2f}\n")
            f.write(f"  Win Rate: {best['win_rate']:.1f}%\n")
            f.write(f"  Profit Factor: {best['profit_factor']:.2f}\n")
    
    print("📄 Saved optimization_report.txt\n")
    print("✅ OPTIMIZATION COMPLETE!\n")


if __name__ == "__main__":
    main()
