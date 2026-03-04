"""
Backtest Engine - Historical Signal Replay

Core backtesting engine that:
  - Replays historical bars tick-by-tick
  - Generates signals using your strategy
  - Simulates order fills with slippage
  - Tracks positions and P&L
  - Exports trade journal

Features:
  - Realistic fill simulation (slippage + commission)
  - Multiple exit strategies (T1/T2 targets, trailing stops)
  - Intraday position management
  - Cash account mode (no PDT rules)
  - Trade-by-trade analytics

Usage:
  engine = BacktestEngine(initial_capital=10000, commission=0.50)
  results = engine.run(
      ticker='AAPL',
      start_date='2025-01-01',
      end_date='2026-01-01',
      strategy_params={'volume_threshold': 2.0, 'min_confidence': 60}
  )
  print(results.summary())
"""
from typing import Dict, List, Optional, Callable, Tuple
from datetime import datetime, timedelta
from dataclasses import dataclass, field
from collections import defaultdict
import statistics

from app.backtesting.performance_metrics import (
    calculate_sharpe_ratio,
    calculate_sortino_ratio,
    calculate_max_drawdown,
    calculate_win_rate,
    calculate_profit_factor,
    calculate_expectancy
)


@dataclass
class Trade:
    """Represents a completed trade."""
    ticker: str
    entry_time: datetime
    entry_price: float
    exit_time: datetime
    exit_price: float
    shares: int
    side: str  # 'LONG' or 'SHORT'
    pnl: float
    pnl_pct: float
    commission: float
    exit_reason: str  # 'TARGET', 'STOP', 'EOD', 'TIMEOUT'
    signal_confidence: float = 0.0
    signal_metadata: Dict = field(default_factory=dict)


@dataclass
class Position:
    """Represents an open position."""
    ticker: str
    entry_time: datetime
    entry_price: float
    shares: int
    side: str
    stop_loss: float
    target: Optional[float] = None
    t1_target: Optional[float] = None
    t2_target: Optional[float] = None
    t1_filled: bool = False
    signal_confidence: float = 0.0
    signal_metadata: Dict = field(default_factory=dict)
    bars_held: int = 0
    max_profit: float = 0.0
    max_loss: float = 0.0


class BacktestResults:
    """Container for backtest results and analytics."""
    
    def __init__(self, trades: List[Trade], initial_capital: float,
                 start_date: datetime, end_date: datetime,
                 strategy_params: Dict):
        self.trades = trades
        self.initial_capital = initial_capital
        self.start_date = start_date
        self.end_date = end_date
        self.strategy_params = strategy_params
        
        # Calculate metrics
        self.total_trades = len(trades)
        self.winning_trades = [t for t in trades if t.pnl > 0]
        self.losing_trades = [t for t in trades if t.pnl < 0]
        self.total_pnl = sum(t.pnl for t in trades)
        self.total_commission = sum(t.commission for t in trades)
        self.net_pnl = self.total_pnl - self.total_commission
        self.final_capital = initial_capital + self.net_pnl
        self.total_return_pct = (self.net_pnl / initial_capital * 100) if initial_capital > 0 else 0
        
        # Performance metrics
        returns = [t.pnl_pct for t in trades]
        self.win_rate = calculate_win_rate(trades)
        self.profit_factor = calculate_profit_factor(trades)
        self.expectancy = calculate_expectancy(trades)
        self.sharpe_ratio = calculate_sharpe_ratio(returns) if returns else 0
        self.sortino_ratio = calculate_sortino_ratio(returns) if returns else 0
        self.max_drawdown = calculate_max_drawdown([initial_capital + sum(t.pnl for t in trades[:i+1]) 
                                                     for i in range(len(trades))])
        
        # Trade distribution
        self.avg_win = statistics.mean([t.pnl for t in self.winning_trades]) if self.winning_trades else 0
        self.avg_loss = statistics.mean([t.pnl for t in self.losing_trades]) if self.losing_trades else 0
        self.largest_win = max([t.pnl for t in trades], default=0)
        self.largest_loss = min([t.pnl for t in trades], default=0)
        
        # Exit analysis
        self.exits_by_reason = defaultdict(int)
        for trade in trades:
            self.exits_by_reason[trade.exit_reason] += 1
    
    def summary(self) -> str:
        """Return formatted summary of backtest results."""
        lines = []
        lines.append("="*80)
        lines.append("BACKTEST RESULTS")
        lines.append("="*80)
        lines.append(f"Period: {self.start_date.date()} to {self.end_date.date()}")
        lines.append(f"Strategy Params: {self.strategy_params}")
        lines.append("")
        
        lines.append("CAPITAL:")
        lines.append(f"  Initial: ${self.initial_capital:,.2f}")
        lines.append(f"  Final:   ${self.final_capital:,.2f}")
        lines.append(f"  P&L:     ${self.net_pnl:,.2f} ({self.total_return_pct:+.2f}%)")
        lines.append("")
        
        lines.append("TRADES:")
        lines.append(f"  Total:   {self.total_trades}")
        lines.append(f"  Winners: {len(self.winning_trades)} ({self.win_rate:.1f}%)")
        lines.append(f"  Losers:  {len(self.losing_trades)}")
        lines.append("")
        
        lines.append("PERFORMANCE:")
        lines.append(f"  Sharpe Ratio:   {self.sharpe_ratio:.2f}")
        lines.append(f"  Sortino Ratio:  {self.sortino_ratio:.2f}")
        lines.append(f"  Profit Factor:  {self.profit_factor:.2f}")
        lines.append(f"  Expectancy:     ${self.expectancy:.2f}")
        lines.append(f"  Max Drawdown:   {self.max_drawdown:.2f}%")
        lines.append("")
        
        lines.append("TRADE DISTRIBUTION:")
        lines.append(f"  Avg Win:      ${self.avg_win:.2f}")
        lines.append(f"  Avg Loss:     ${self.avg_loss:.2f}")
        lines.append(f"  Largest Win:  ${self.largest_win:.2f}")
        lines.append(f"  Largest Loss: ${self.largest_loss:.2f}")
        lines.append("")
        
        lines.append("EXIT REASONS:")
        for reason, count in sorted(self.exits_by_reason.items(), key=lambda x: x[1], reverse=True):
            pct = (count / self.total_trades * 100) if self.total_trades > 0 else 0
            lines.append(f"  {reason:<12} {count:>3} ({pct:.1f}%)")
        
        lines.append("="*80)
        
        return "\n".join(lines)
    
    def to_dict(self) -> Dict:
        """Export results as dictionary for JSON serialization."""
        return {
            'period': {
                'start': self.start_date.isoformat(),
                'end': self.end_date.isoformat()
            },
            'strategy_params': self.strategy_params,
            'capital': {
                'initial': self.initial_capital,
                'final': self.final_capital,
                'net_pnl': self.net_pnl,
                'return_pct': self.total_return_pct
            },
            'trades': {
                'total': self.total_trades,
                'winners': len(self.winning_trades),
                'losers': len(self.losing_trades),
                'win_rate': self.win_rate
            },
            'performance': {
                'sharpe_ratio': self.sharpe_ratio,
                'sortino_ratio': self.sortino_ratio,
                'profit_factor': self.profit_factor,
                'expectancy': self.expectancy,
                'max_drawdown': self.max_drawdown
            },
            'distribution': {
                'avg_win': self.avg_win,
                'avg_loss': self.avg_loss,
                'largest_win': self.largest_win,
                'largest_loss': self.largest_loss
            },
            'exits': dict(self.exits_by_reason)
        }


class BacktestEngine:
    """Core backtesting engine with historical signal replay."""
    
    def __init__(self,
                 initial_capital: float = 10000,
                 commission_per_trade: float = 0.50,
                 slippage_pct: float = 0.05,
                 max_position_size_pct: float = 100.0,
                 risk_per_trade_pct: float = 1.0,
                 max_bars_held: int = 390,  # Full trading day
                 enable_t1_t2_exits: bool = True):
        """
        Args:
            initial_capital: Starting account balance
            commission_per_trade: Fixed commission per trade
            slippage_pct: Slippage as % of price (0.05 = 0.05%)
            max_position_size_pct: Max position size as % of capital
            risk_per_trade_pct: Risk per trade as % of capital
            max_bars_held: Max bars to hold position (390 = full day)
            enable_t1_t2_exits: Use T1/T2 split exits
        """
        self.initial_capital = initial_capital
        self.commission_per_trade = commission_per_trade
        self.slippage_pct = slippage_pct / 100  # Convert to decimal
        self.max_position_size_pct = max_position_size_pct / 100
        self.risk_per_trade_pct = risk_per_trade_pct / 100
        self.max_bars_held = max_bars_held
        self.enable_t1_t2_exits = enable_t1_t2_exits
        
        # Runtime state
        self.current_capital = initial_capital
        self.positions: List[Position] = []
        self.trades: List[Trade] = []
        self.current_bar_index = 0
        
        print(f"[BACKTEST] Engine initialized")
        print(f"  Capital: ${initial_capital:,.2f}")
        print(f"  Commission: ${commission_per_trade:.2f}")
        print(f"  Slippage: {slippage_pct:.2f}%")
        print(f"  Max hold: {max_bars_held} bars")
    
    def calculate_position_size(self, entry_price: float, stop_price: float) -> int:
        """
        Calculate position size based on risk per trade.
        
        Args:
            entry_price: Entry price
            stop_price: Stop loss price
        
        Returns:
            Number of shares
        """
        risk_per_share = abs(entry_price - stop_price)
        if risk_per_share == 0:
            return 0
        
        risk_amount = self.current_capital * self.risk_per_trade_pct
        shares = int(risk_amount / risk_per_share)
        
        # Cap at max position size
        max_shares = int((self.current_capital * self.max_position_size_pct) / entry_price)
        shares = min(shares, max_shares)
        
        return max(shares, 0)
    
    def simulate_fill(self, price: float, side: str) -> float:
        """
        Simulate order fill with slippage.
        
        Args:
            price: Limit price
            side: 'BUY' or 'SELL'
        
        Returns:
            Filled price including slippage
        """
        if side == 'BUY':
            return price * (1 + self.slippage_pct)  # Pay more
        else:
            return price * (1 - self.slippage_pct)  # Receive less
    
    def open_position(self, signal: Dict, bar: Dict) -> Optional[Position]:
        """
        Open a new position based on signal.
        
        Args:
            signal: Signal dict from strategy
            bar: Current OHLCV bar
        
        Returns:
            Position object or None if rejected
        """
        # Check if we have capital
        if self.current_capital <= 0:
            return None
        
        # Extract signal details
        ticker = signal.get('ticker', 'UNKNOWN')
        entry_price = signal.get('entry', bar['close'])
        stop_loss = signal.get('stop', entry_price * 0.98)
        target = signal.get('target')
        t1_target = signal.get('t1')
        t2_target = signal.get('t2')
        side = 'LONG' if signal.get('signal') == 'BUY' else 'SHORT'
        confidence = signal.get('confidence', 0)
        
        # Calculate position size
        shares = self.calculate_position_size(entry_price, stop_loss)
        if shares == 0:
            return None
        
        # Simulate fill
        filled_price = self.simulate_fill(entry_price, 'BUY' if side == 'LONG' else 'SELL')
        
        # Deduct commission
        self.current_capital -= self.commission_per_trade
        
        # Create position
        position = Position(
            ticker=ticker,
            entry_time=bar.get('datetime', datetime.now()),
            entry_price=filled_price,
            shares=shares,
            side=side,
            stop_loss=stop_loss,
            target=target,
            t1_target=t1_target,
            t2_target=t2_target,
            signal_confidence=confidence,
            signal_metadata=signal
        )
        
        self.positions.append(position)
        return position
    
    def close_position(self, position: Position, bar: Dict, exit_reason: str) -> Trade:
        """
        Close an open position.
        
        Args:
            position: Position to close
            bar: Current OHLCV bar
            exit_reason: Reason for exit
        
        Returns:
            Trade object
        """
        exit_price = bar['close']
        filled_price = self.simulate_fill(exit_price, 'SELL' if position.side == 'LONG' else 'BUY')
        
        # Calculate P&L
        if position.side == 'LONG':
            pnl = (filled_price - position.entry_price) * position.shares
        else:
            pnl = (position.entry_price - filled_price) * position.shares
        
        pnl_pct = (pnl / (position.entry_price * position.shares) * 100) if position.shares > 0 else 0
        
        # Deduct commission
        self.current_capital -= self.commission_per_trade
        
        # Update capital
        self.current_capital += pnl
        
        # Create trade
        trade = Trade(
            ticker=position.ticker,
            entry_time=position.entry_time,
            entry_price=position.entry_price,
            exit_time=bar.get('datetime', datetime.now()),
            exit_price=filled_price,
            shares=position.shares,
            side=position.side,
            pnl=pnl,
            pnl_pct=pnl_pct,
            commission=self.commission_per_trade * 2,  # Entry + exit
            exit_reason=exit_reason,
            signal_confidence=position.signal_confidence,
            signal_metadata=position.signal_metadata
        )
        
        self.trades.append(trade)
        self.positions.remove(position)
        
        return trade
    
    def manage_positions(self, bar: Dict):
        """
        Manage open positions (check stops, targets, timeouts).
        
        Args:
            bar: Current OHLCV bar
        """
        for position in list(self.positions):
            position.bars_held += 1
            
            current_price = bar['close']
            
            # Update max profit/loss
            if position.side == 'LONG':
                current_pnl = (current_price - position.entry_price) * position.shares
            else:
                current_pnl = (position.entry_price - current_price) * position.shares
            
            position.max_profit = max(position.max_profit, current_pnl)
            position.max_loss = min(position.max_loss, current_pnl)
            
            # Check stop loss
            if position.side == 'LONG':
                if bar['low'] <= position.stop_loss:
                    self.close_position(position, bar, 'STOP')
                    continue
            else:
                if bar['high'] >= position.stop_loss:
                    self.close_position(position, bar, 'STOP')
                    continue
            
            # Check T1 target (take 50%)
            if self.enable_t1_t2_exits and position.t1_target and not position.t1_filled:
                if position.side == 'LONG':
                    if bar['high'] >= position.t1_target:
                        # Take 50% profit at T1
                        position.shares = position.shares // 2
                        position.t1_filled = True
                        # Don't close entire position, let T2 run
                        continue
                else:
                    if bar['low'] <= position.t1_target:
                        position.shares = position.shares // 2
                        position.t1_filled = True
                        continue
            
            # Check T2 target (or regular target)
            target_price = position.t2_target if self.enable_t1_t2_exits else position.target
            if target_price:
                if position.side == 'LONG':
                    if bar['high'] >= target_price:
                        self.close_position(position, bar, 'TARGET')
                        continue
                else:
                    if bar['low'] <= target_price:
                        self.close_position(position, bar, 'TARGET')
                        continue
            
            # Check timeout (max bars held)
            if position.bars_held >= self.max_bars_held:
                self.close_position(position, bar, 'TIMEOUT')
                continue
    
    def run(self,
            ticker: str,
            bars: List[Dict],
            strategy: Callable[[List[Dict], Dict], Optional[Dict]],
            strategy_params: Dict = None) -> BacktestResults:
        """
        Run backtest on historical data.
        
        Args:
            ticker: Stock ticker
            bars: List of OHLCV bars with 'datetime' field
            strategy: Strategy function that returns signal dict or None
                      Signature: strategy(bars, params) -> Optional[Dict]
            strategy_params: Parameters to pass to strategy
        
        Returns:
            BacktestResults object
        """
        if not bars:
            raise ValueError("No bars provided")
        
        strategy_params = strategy_params or {}
        start_date = bars[0].get('datetime', datetime.now())
        end_date = bars[-1].get('datetime', datetime.now())
        
        print(f"\n[BACKTEST] Running {ticker} backtest")
        print(f"  Period: {start_date.date()} to {end_date.date()}")
        print(f"  Bars: {len(bars)}")
        print(f"  Params: {strategy_params}")
        
        # Reset state
        self.current_capital = self.initial_capital
        self.positions = []
        self.trades = []
        
        # Replay bars
        for i, bar in enumerate(bars):
            self.current_bar_index = i
            
            # Manage existing positions
            if self.positions:
                self.manage_positions(bar)
            
            # Generate new signals (only if no open position)
            if not self.positions and i >= 50:  # Need enough history
                lookback_bars = bars[max(0, i-100):i+1]
                signal = strategy(lookback_bars, strategy_params)
                
                if signal:
                    signal['ticker'] = ticker
                    self.open_position(signal, bar)
        
        # Close any remaining positions at end
        if self.positions:
            final_bar = bars[-1]
            for position in list(self.positions):
                self.close_position(position, final_bar, 'EOD')
        
        # Generate results
        results = BacktestResults(
            trades=self.trades,
            initial_capital=self.initial_capital,
            start_date=start_date,
            end_date=end_date,
            strategy_params=strategy_params
        )
        
        print(f"\n[BACKTEST] Complete: {len(self.trades)} trades | "
              f"P&L: ${results.net_pnl:,.2f} ({results.total_return_pct:+.1f}%)")
        
        return results


if __name__ == "__main__":
    # Example usage
    print("Backtest Engine - Example Usage")
    print("="*80)
    print("\nSee docs/task10_backtesting_guide.md for full examples.")
