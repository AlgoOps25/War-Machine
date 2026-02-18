"""
Options Chain Filter Module
Analyzes options chains to validate signal quality and suggest optimal strikes.
"""

import requests
import os
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple
import config


class OptionsFilter:
    """Filters and analyzes options chains for trading signals."""
    
    def __init__(self):
        self.api_key = config.EODHD_API_KEY
        self.base_url = "https://eodhd.com/api/options"
        
    def get_options_chain(self, ticker: str) -> Optional[Dict]:
        """Fetch full options chain from EODHD."""
        url = f"{self.base_url}/{ticker}.US"
        params = {"api_token": self.api_key}
        
        try:
            response = requests.get(url, params=params, timeout=10)
            response.raise_for_status()
            return response.json()
        except Exception as e:
            print(f"[OPTIONS] Error fetching chain for {ticker}: {e}")
            return None
    
    def filter_by_liquidity(self, option: Dict) -> bool:
        """Check if option meets minimum liquidity requirements."""
        oi = option.get("openInterest", 0)
        volume = option.get("volume", 0)
        bid = option.get("bid", 0)
        ask = option.get("ask", 0)
        
        if oi < config.MIN_OPTION_OI:
            return False
        if volume < config.MIN_OPTION_VOLUME:
            return False
            
        if ask > 0 and bid > 0:
            mid = (bid + ask) / 2
            spread_pct = (ask - bid) / mid if mid > 0 else 999
            if spread_pct > config.MAX_BID_ASK_SPREAD_PCT:
                return False
                
        return True
    
    def filter_by_delta(self, option: Dict) -> bool:
        """Check if option delta is in target range."""
        delta = option.get("delta", 0)
        delta_abs = abs(delta)
        
        if delta_abs < config.TARGET_DELTA_MIN:
            return False
        if delta_abs > config.TARGET_DELTA_MAX:
            return False
            
        return True
    
    def filter_by_dte(self, expiration_date: str) -> Tuple[bool, int]:
        """Check if expiration is in acceptable DTE range."""
        try:
            exp_date = datetime.strptime(expiration_date, "%Y-%m-%d")
            today = datetime.now()
            dte = (exp_date - today).days
            
            if dte < config.MIN_DTE:
                return False, dte
            if dte > config.MAX_DTE:
                return False, dte
                
            return True, dte
        except Exception:
            return False, 0
    
    def calculate_expected_move(self, price: float, iv: float, dte: int) -> float:
        """Calculate expected move based on IV and DTE."""
        expected_move = price * iv * ((dte / 365) ** 0.5)
        return round(expected_move, 2)
    
    def find_best_strike(self, ticker: str, direction: str, 
                        entry_price: float, target_price: float) -> Optional[Dict]:
        """Find the optimal option strike for a given signal."""
        chain = self.get_options_chain(ticker)
        if not chain:
            return None
            
        best_option = None
        best_score = -1
        
        for expiration_date, options_data in chain.get("data", {}).items():
            is_valid_dte, dte = self.filter_by_dte(expiration_date)
            if not is_valid_dte:
                continue
                
            is_call = (direction == "bull")
            option_type = "calls" if is_call else "puts"
            
            if option_type not in options_data:
                continue
                
            for strike_str, option in options_data[option_type].items():
                strike = float(strike_str)
                
                if not self.filter_by_liquidity(option):
                    continue
                if not self.filter_by_delta(option):
                    continue
                    
                if is_call:
                    if strike < entry_price * 0.95 or strike > entry_price * 1.10:
                        continue
                else:
                    if strike > entry_price * 1.05 or strike < entry_price * 0.90:
                        continue
                
                dte_score = 100 - abs(dte - config.IDEAL_DTE)
                oi_score = min(option.get("openInterest", 0) / 1000, 100)
                
                bid = option.get("bid", 0)
                ask = option.get("ask", 0)
                if ask > 0 and bid > 0:
                    mid = (bid + ask) / 2
                    spread_pct = (ask - bid) / mid if mid > 0 else 999
                    spread_score = max(0, 100 - (spread_pct * 1000))
                else:
                    spread_score = 0
                    
                total_score = dte_score + oi_score + spread_score
                
                if total_score > best_score:
                    best_score = total_score
                    iv = option.get("impliedVolatility", 0)
                    expected_move = self.calculate_expected_move(entry_price, iv, dte)
                    
                    best_option = {
                        "strike": strike,
                        "expiration": expiration_date,
                        "delta": option.get("delta", 0),
                        "oi": option.get("openInterest", 0),
                        "volume": option.get("volume", 0),
                        "bid": bid,
                        "ask": ask,
                        "iv": iv,
                        "dte": dte,
                        "expected_move": expected_move,
                        "score": total_score
                    }
        
        return best_option
    
    def validate_signal_for_options(self, ticker: str, direction: str,
                                    entry_price: float, target_price: float) -> Tuple[bool, Optional[Dict], str]:
        """Validate if a signal is suitable for options trading."""
        best_strike = self.find_best_strike(ticker, direction, entry_price, target_price)
        
        if not best_strike:
            return False, None, "No suitable options found meeting liquidity/delta requirements"
        
        expected_move = best_strike["expected_move"]
        price_move_needed = abs(target_price - entry_price)
        
        if price_move_needed > expected_move * 2:
            return False, best_strike, f"Target requires ${price_move_needed:.2f} but expected move only ${expected_move:.2f}"
        
        iv = best_strike["iv"]
        if iv > 1.0:
            return False, best_strike, f"IV too high at {iv*100:.1f}%"
        
        dte = best_strike["dte"]
        bid = best_strike["bid"]
        ask = best_strike["ask"]
        mid = (bid + ask) / 2 if (bid and ask) else 0
        
        if mid > 0 and dte > 0:
            daily_theta_est = mid / dte
            theta_pct = (daily_theta_est / mid) if mid > 0 else 0
            
            if theta_pct > config.MAX_THETA_DECAY_PCT:
                return False, best_strike, f"Theta decay too high: {theta_pct*100:.2f}% per day"
        
        return True, best_strike, "Options signal validated"


def get_options_recommendation(ticker: str, direction: str, 
                               entry_price: float, target_price: float) -> Optional[Dict]:
    """Simplified interface to get options recommendation for a signal."""
    filter_engine = OptionsFilter()
    is_valid, options_data, reason = filter_engine.validate_signal_for_options(
        ticker, direction, entry_price, target_price
    )
    
    if is_valid and options_data:
        print(f"[OPTIONS] ✅ {ticker} options validated: {reason}")
        return options_data
    else:
        print(f"[OPTIONS] ⚠️ {ticker} not suitable: {reason}")
        return None
