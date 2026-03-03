#!/usr/bin/env python3
"""
Sniper Module - Options Order Execution
Handles the execution of options trades with DTE selection logic.
"""

import logging
from datetime import datetime
from typing import Optional, Dict, Any
from dte_selector import DTESelector, DTEConfig

logger = logging.getLogger(__name__)

class Sniper:
    """Handles options order execution with intelligent DTE selection"""
    
    def __init__(self, broker_client, config: Dict[str, Any]):
        self.broker = broker_client
        self.config = config
        
        # Initialize DTE selector with configuration
        dte_config = DTEConfig(
            default_dte=config.get('default_dte', 0),
            pre_1000_dte=config.get('pre_1000_dte', 0),
            post_1000_dte=config.get('post_1000_dte', 1),
            post_1030_dte=config.get('post_1030_dte', 2),
            avoid_wed_0dte=config.get('avoid_wed_0dte', True),
            min_time_value=config.get('min_time_value', 0.05),
            enable_smart_routing=config.get('enable_smart_routing', True)
        )
        self.dte_selector = DTESelector(dte_config)
        
        logger.info(f"SNIPER initialized with DTE config: {dte_config}")
    
    def execute_options_trade(
        self,
        symbol: str,
        side: str,  # 'buy' or 'sell'
        option_type: str,  # 'call' or 'put'
        strike: float,
        quantity: int,
        limit_price: Optional[float] = None,
        force_dte: Optional[int] = None
    ) -> Dict[str, Any]:
        """
        Execute options trade with intelligent DTE selection
        
        Args:
            symbol: Underlying symbol
            side: 'buy' or 'sell'
            option_type: 'call' or 'put'
            strike: Strike price
            quantity: Number of contracts
            limit_price: Optional limit price
            force_dte: Override DTE selection (optional)
        
        Returns:
            Dict with order details and execution status
        """
        try:
            # Determine optimal DTE
            if force_dte is not None:
                selected_dte = force_dte
                logger.info(f"SNIPER Using forced DTE={selected_dte} for {symbol}")
            else:
                selected_dte = self.dte_selector.select_dte()
                logger.info(f"SNIPER Selected DTE={selected_dte} for {symbol} at {datetime.now().strftime('%H:%M')}")
            
            # Get expiration date for selected DTE
            expiration = self.dte_selector.get_expiration_for_dte(selected_dte)
            
            if not expiration:
                logger.error(f"SNIPER No valid expiration found for DTE={selected_dte}")
                return {
                    'success': False,
                    'error': 'No valid expiration available',
                    'dte': selected_dte
                }
            
            # Build option symbol (OCC format)
            option_symbol = self._build_option_symbol(
                symbol, expiration, option_type, strike
            )
            
            logger.info(
                f"SNIPER Executing {side.upper()} {quantity} {option_symbol} "
                f"@ ${limit_price:.2f} (DTE={selected_dte})"
            )
            
            # Place order through broker
            order_result = self._place_order(
                option_symbol=option_symbol,
                side=side,
                quantity=quantity,
                limit_price=limit_price
            )
            
            # Add DTE info to result
            order_result['dte'] = selected_dte
            order_result['expiration'] = expiration.strftime('%Y-%m-%d')
            order_result['underlying'] = symbol
            order_result['strike'] = strike
            order_result['option_type'] = option_type
            
            return order_result
            
        except Exception as e:
            logger.error(f"SNIPER Error executing options trade: {e}", exc_info=True)
            return {
                'success': False,
                'error': str(e),
                'symbol': symbol
            }
    
    def _build_option_symbol(self, symbol: str, expiration: datetime, 
                            option_type: str, strike: float) -> str:
        """
        Build OCC option symbol format
        Example: AAPL260307C00150000 (AAPL Mar 7 2026 $150 Call)
        """
        exp_str = expiration.strftime('%y%m%d')
        type_code = 'C' if option_type.lower() == 'call' else 'P'
        strike_str = f"{int(strike * 1000):08d}"
        
        return f"{symbol}{exp_str}{type_code}{strike_str}"
    
    def _place_order(self, option_symbol: str, side: str, 
                    quantity: int, limit_price: Optional[float]) -> Dict[str, Any]:
        """
        Place order through broker API
        """
        try:
            # Example broker API call - adapt to your broker
            order = self.broker.place_order(
                symbol=option_symbol,
                side=side,
                quantity=quantity,
                order_type='limit' if limit_price else 'market',
                limit_price=limit_price,
                time_in_force='DAY'
            )
            
            return {
                'success': True,
                'order_id': order.get('id'),
                'status': order.get('status'),
                'filled_qty': order.get('filled_qty', 0),
                'avg_fill_price': order.get('avg_fill_price'),
                'timestamp': datetime.now().isoformat()
            }
            
        except Exception as e:
            logger.error(f"SNIPER Broker order failed: {e}")
            return {
                'success': False,
                'error': str(e)
            }
    
    def get_dte_info(self) -> Dict[str, Any]:
        """
        Get current DTE selector status and recommendations
        """
        current_dte = self.dte_selector.select_dte()
        expiration = self.dte_selector.get_expiration_for_dte(current_dte)
        
        return {
            'current_dte': current_dte,
            'expiration': expiration.strftime('%Y-%m-%d') if expiration else None,
            'time': datetime.now().strftime('%H:%M'),
            'is_wednesday': datetime.now().weekday() == 2,
            'config': self.dte_selector.config.__dict__
        }