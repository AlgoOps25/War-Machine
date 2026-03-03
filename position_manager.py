#!/usr/bin/env python3
"""
Position Manager - Track and manage open options positions
Integrates with DTE selector for position analysis and rolling decisions.
"""

import logging
from datetime import datetime, timedelta
from typing import List, Dict, Any, Optional
from dataclasses import dataclass
from dte_selector import DTESelector, DTEConfig

logger = logging.getLogger(__name__)

@dataclass
class Position:
    """Represents an open options position"""
    symbol: str
    option_symbol: str
    side: str  # 'long' or 'short'
    option_type: str  # 'call' or 'put'
    strike: float
    quantity: int
    entry_price: float
    current_price: float
    expiration: datetime
    dte: int
    entry_time: datetime
    pnl: float = 0.0
    pnl_pct: float = 0.0
    position_id: Optional[str] = None

class PositionManager:
    """Manages options positions with DTE-aware analytics"""
    
    def __init__(self, config: Dict[str, Any]):
        self.config = config
        self.positions: List[Position] = []
        
        # Initialize DTE selector for analysis
        dte_config = DTEConfig(
            default_dte=config.get('default_dte', 0),
            pre_1000_dte=config.get('pre_1000_dte', 0),
            post_1000_dte=config.get('post_1000_dte', 1),
            post_1030_dte=config.get('post_1030_dte', 2),
            avoid_wed_0dte=config.get('avoid_wed_0dte', True),
            min_time_value=config.get('min_time_value', 0.05)
        )
        self.dte_selector = DTESelector(dte_config)
        
        logger.info("POSITIONS Manager initialized with DTE integration")
    
    def add_position(self, position: Position) -> None:
        """Add a new position to tracking"""
        self.positions.append(position)
        logger.info(
            f"POSITIONS Added {position.side} {position.quantity} "
            f"{position.option_symbol} @ ${position.entry_price:.2f} (DTE={position.dte})"
        )
    
    def update_position(self, position_id: str, current_price: float) -> None:
        """Update position with current market price"""
        for pos in self.positions:
            if pos.position_id == position_id:
                pos.current_price = current_price
                pos.pnl = (current_price - pos.entry_price) * pos.quantity * 100
                pos.pnl_pct = ((current_price - pos.entry_price) / pos.entry_price) * 100
                break
    
    def close_position(self, position_id: str, exit_price: float) -> Optional[Position]:
        """Close and remove position from tracking"""
        for i, pos in enumerate(self.positions):
            if pos.position_id == position_id:
                pos.current_price = exit_price
                pos.pnl = (exit_price - pos.entry_price) * pos.quantity * 100
                pos.pnl_pct = ((exit_price - pos.entry_price) / pos.entry_price) * 100
                
                closed_pos = self.positions.pop(i)
                logger.info(
                    f"POSITIONS Closed {closed_pos.option_symbol} "
                    f"PnL=${closed_pos.pnl:.2f} ({closed_pos.pnl_pct:+.1f}%)"
                )
                return closed_pos
        return None
    
    def get_positions_by_dte(self) -> Dict[int, List[Position]]:
        """Group positions by DTE"""
        dte_groups: Dict[int, List[Position]] = {}
        
        for pos in self.positions:
            # Recalculate current DTE
            current_dte = (pos.expiration.date() - datetime.now().date()).days
            
            if current_dte not in dte_groups:
                dte_groups[current_dte] = []
            dte_groups[current_dte].append(pos)
        
        return dte_groups
    
    def get_expiring_positions(self, within_minutes: int = 30) -> List[Position]:
        """Get positions expiring within specified minutes"""
        expiring = []
        cutoff_time = datetime.now() + timedelta(minutes=within_minutes)
        
        for pos in self.positions:
            # Assume 4:00 PM ET expiration
            expiration_time = pos.expiration.replace(hour=16, minute=0)
            
            if expiration_time <= cutoff_time:
                expiring.append(pos)
        
        return expiring
    
    def get_at_risk_positions(self, loss_threshold: float = -0.5) -> List[Position]:
        """Get positions with losses exceeding threshold"""
        at_risk = []
        
        for pos in self.positions:
            if pos.pnl_pct <= loss_threshold:
                at_risk.append(pos)
        
        return at_risk
    
    def should_roll_position(self, position: Position) -> Dict[str, Any]:
        """
        Analyze if position should be rolled to next DTE
        
        Returns decision with reasoning
        """
        current_time = datetime.now()
        time_to_exp = (position.expiration - current_time).total_seconds() / 3600
        
        # Get recommended DTE for current time
        recommended_dte = self.dte_selector.select_dte()
        current_dte = (position.expiration.date() - current_time.date()).days
        
        reasons = []
        should_roll = False
        
        # Check if position is profitable
        if position.pnl_pct < -20:
            reasons.append(f"Position down {position.pnl_pct:.1f}% - consider cutting loss")
            should_roll = False
        
        # Check time decay
        if time_to_exp < 1 and position.option_type == 'call':
            reasons.append("Less than 1 hour to expiration - urgent action needed")
            should_roll = True
        
        # Check if should move to next DTE
        if current_dte < recommended_dte and position.pnl_pct > 0:
            reasons.append(f"Current DTE={current_dte}, Recommended={recommended_dte} - consider rolling")
            should_roll = True
        
        # Check Wednesday 0DTE avoidance
        if current_time.weekday() == 2 and current_dte == 0 and self.dte_selector.config.avoid_wed_0dte:
            reasons.append("Wednesday 0DTE - should have rolled earlier")
            should_roll = False  # Too late now
        
        return {
            'should_roll': should_roll,
            'current_dte': current_dte,
            'recommended_dte': recommended_dte,
            'time_to_exp_hours': time_to_exp,
            'pnl_pct': position.pnl_pct,
            'reasons': reasons
        }
    
    def get_portfolio_summary(self) -> Dict[str, Any]:
        """Get summary of all positions"""
        if not self.positions:
            return {
                'total_positions': 0,
                'total_pnl': 0.0,
                'by_dte': {},
                'by_symbol': {}
            }
        
        total_pnl = sum(pos.pnl for pos in self.positions)
        dte_groups = self.get_positions_by_dte()
        
        # Group by underlying symbol
        by_symbol: Dict[str, List[Position]] = {}
        for pos in self.positions:
            if pos.symbol not in by_symbol:
                by_symbol[pos.symbol] = []
            by_symbol[pos.symbol].append(pos)
        
        return {
            'total_positions': len(self.positions),
            'total_pnl': total_pnl,
            'by_dte': {dte: len(positions) for dte, positions in dte_groups.items()},
            'by_symbol': {symbol: len(positions) for symbol, positions in by_symbol.items()},
            'expiring_soon': len(self.get_expiring_positions()),
            'at_risk': len(self.get_at_risk_positions())
        }
    
    def get_all_positions(self) -> List[Position]:
        """Get all current positions"""
        return self.positions.copy()