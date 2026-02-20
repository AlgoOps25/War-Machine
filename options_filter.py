"""
Options Chain Filter Module
Analyzes options chains to validate signal quality and suggest optimal strikes.
INTEGRATED: IV Rank (IVR) + Unusual Options Activity (UOA).
"""

import requests
from datetime import datetime, timedelta
from typing import Dict, Optional, Tuple
import config
from iv_tracker import store_iv_observation, compute_ivr, ivr_to_confidence_multiplier
from uoa_scanner import scan_chain_for_uoa


class OptionsFilter:
    """Filters and analyzes options chains for trading signals."""

    def __init__(self):
        self.api_key  = config.EODHD_API_KEY
        self.base_url = "https://eodhd.com/api/options"

    def get_options_chain(self, ticker: str) -> Optional[Dict]:
        """Fetch full options chain from EODHD."""
        url    = f"{self.base_url}/{ticker}.US"
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
        oi     = option.get("openInterest", 0)
        volume = option.get("volume", 0)
        bid    = option.get("bid", 0)
        ask    = option.get("ask", 0)
        if oi < config.MIN_OPTION_OI:
            return False
        if volume < config.MIN_OPTION_VOLUME:
            return False
        if ask > 0 and bid > 0:
            mid        = (bid + ask) / 2
            spread_pct = (ask - bid) / mid if mid > 0 else 999
            if spread_pct > config.MAX_BID_ASK_SPREAD_PCT:
                return False
        return True

    def filter_by_delta(self, option: Dict) -> bool:
        """Check if option delta is in target range."""
        delta_abs = abs(option.get("delta", 0))
        return config.TARGET_DELTA_MIN <= delta_abs <= config.TARGET_DELTA_MAX

    def filter_by_dte(self, expiration_date: str) -> Tuple[bool, int]:
        """Check if expiration is in acceptable DTE range."""
        try:
            exp_date = datetime.strptime(expiration_date, "%Y-%m-%d")
            dte      = (exp_date - datetime.now()).days
            if dte < config.MIN_DTE or dte > config.MAX_DTE:
                return False, dte
            return True, dte
        except Exception:
            return False, 0

    def calculate_expected_move(self, price: float, iv: float, dte: int) -> float:
        """Calculate expected move based on IV and DTE."""
        return round(price * iv * ((dte / 365) ** 0.5), 2)

    def find_best_strike(self, ticker: str, direction: str,
                         entry_price: float, target_price: float) -> Optional[Dict]:
        """Find the optimal option strike and enrich with IVR + UOA."""
        chain = self.get_options_chain(ticker)
        if not chain:
            return None

        best_option = None
        best_score  = -1

        for expiration_date, options_data in chain.get("data", {}).items():
            is_valid_dte, dte = self.filter_by_dte(expiration_date)
            if not is_valid_dte:
                continue

            is_call     = (direction == "bull")
            option_type = "calls" if is_call else "puts"

            for strike_str, option in options_data.get(option_type, {}).items():
                strike = float(strike_str)

                if not self.filter_by_liquidity(option):
                    continue
                if not self.filter_by_delta(option):
                    continue

                # Strike proximity filter
                if is_call:
                    if not (entry_price * 0.95 <= strike <= entry_price * 1.10):
                        continue
                else:
                    if not (entry_price * 0.90 <= strike <= entry_price * 1.05):
                        continue

                bid = option.get("bid", 0)
                ask = option.get("ask", 0)
                mid = (bid + ask) / 2 if (bid and ask) else 0

                dte_score    = 100 - abs(dte - config.IDEAL_DTE)
                oi_score     = min(option.get("openInterest", 0) / 1000, 100)
                spread_pct   = (ask - bid) / mid if mid > 0 else 999
                spread_score = max(0, 100 - (spread_pct * 1000))
                total_score  = dte_score + oi_score + spread_score

                if total_score > best_score:
                    best_score = total_score
                    iv         = option.get("impliedVolatility", 0)
                    best_option = {
                        "strike":        strike,
                        "expiration":    expiration_date,
                        "delta":         option.get("delta", 0),
                        "oi":            option.get("openInterest", 0),
                        "volume":        option.get("volume", 0),
                        "bid":           bid,
                        "ask":           ask,
                        "iv":            iv,
                        "dte":           dte,
                        "expected_move": self.calculate_expected_move(entry_price, iv, dte),
                        "score":         total_score
                    }

        if not best_option:
            return None

        # ── IVR enrichment ───────────────────────────────────────────────
        iv = best_option.get("iv", 0)
        if iv and iv > 0:
            store_iv_observation(ticker, iv)
            ivr, obs, reliable = compute_ivr(ticker, iv)
            mult, label        = ivr_to_confidence_multiplier(ivr, reliable)
            best_option.update({
                "ivr":           ivr,
                "ivr_obs":       obs,
                "ivr_reliable":  reliable,
                "ivr_multiplier": mult,
                "ivr_label":     label
            })
            status = f"IVR={ivr:.0f}" if (ivr is not None and reliable) else "IVR-BUILDING"
            print(f"[IVR] {ticker}: IV={iv*100:.1f}% | {status} "
                  f"({obs} obs) | {mult:.2f}x [{label}]")
        else:
            best_option.update({
                "ivr": None, "ivr_obs": 0, "ivr_reliable": False,
                "ivr_multiplier": 1.0, "ivr_label": "IVR-NO-DATA"
            })

        # ── UOA enrichment ───────────────────────────────────────────────
        # Scan the FULL chain (not just best strike) for unusual activity.
        # Directional alignment is checked against our BOS direction.
        try:
            uoa_result = scan_chain_for_uoa(chain, direction, entry_price)
            best_option.update({
                "uoa_multiplier": uoa_result["multiplier"],
                "uoa_label":      uoa_result["label"],
                "uoa_detected":   uoa_result["uoa_detected"],
                "uoa_aligned":    uoa_result["aligned"],
                "uoa_opposing":   uoa_result["opposing"],
                "uoa_max_score":  uoa_result["max_uoa_score"],
                "uoa_top_aligned":  uoa_result.get("top_aligned",  []),
                "uoa_top_opposing": uoa_result.get("top_opposing", [])
            })
            if uoa_result["uoa_detected"]:
                print(f"[UOA] {ticker}: {uoa_result['label']} | "
                      f"Aligned: {len(uoa_result['top_aligned'])} strikes | "
                      f"Opposing: {len(uoa_result['top_opposing'])} strikes")
                # Log top aligned hits
                for hit in uoa_result["top_aligned"][:2]:
                    print(f"  ⬆ {hit['type'].upper()} ${hit['strike']:.0f} "
                          f"exp {hit['expiry']} | Vol {hit['volume']:,} "
                          f"OI {hit['oi']:,} | UOA {hit['uoa_score']:.2f}x")
                for hit in uoa_result["top_opposing"][:2]:
                    print(f"  ⬇ {hit['type'].upper()} ${hit['strike']:.0f} "
                          f"exp {hit['expiry']} | Vol {hit['volume']:,} "
                          f"OI {hit['oi']:,} | UOA {hit['uoa_score']:.2f}x")
            else:
                print(f"[UOA] {ticker}: No unusual activity detected")
        except Exception as e:
            print(f"[UOA] {ticker} scan error: {e}")
            best_option.update({
                "uoa_multiplier": 1.0, "uoa_label": "UOA-ERROR",
                "uoa_detected": False, "uoa_aligned": False,
                "uoa_opposing": False, "uoa_max_score": 0.0,
                "uoa_top_aligned": [], "uoa_top_opposing": []
            })

        return best_option

    def validate_signal_for_options(self, ticker: str, direction: str,
                                    entry_price: float,
                                    target_price: float) -> Tuple[bool, Optional[Dict], str]:
        """Validate if a signal is suitable for options trading."""
        best_strike = self.find_best_strike(ticker, direction, entry_price, target_price)
        if not best_strike:
            return False, None, "No suitable options found"

        expected_move     = best_strike["expected_move"]
        price_move_needed = abs(target_price - entry_price)
        if price_move_needed > expected_move * 2:
            return False, best_strike, (
                f"Target ${price_move_needed:.2f} exceeds 2x expected move ${expected_move:.2f}"
            )

        iv = best_strike["iv"]
        if iv > 1.0:
            return False, best_strike, f"IV too high at {iv*100:.1f}% (hard cap)"

        dte = best_strike["dte"]
        bid = best_strike["bid"]
        ask = best_strike["ask"]
        mid = (bid + ask) / 2 if (bid and ask) else 0
        if mid > 0 and dte > 0:
            theta_pct = (mid / dte) / mid
            if theta_pct > config.MAX_THETA_DECAY_PCT:
                return False, best_strike, f"Theta {theta_pct*100:.2f}%/day too high"

        return True, best_strike, "Options signal validated"


def get_options_recommendation(ticker: str, direction: str,
                               entry_price: float,
                               target_price: float) -> Optional[Dict]:
    """Simplified interface to get options recommendation for a signal."""
    f = OptionsFilter()
    is_valid, options_data, reason = f.validate_signal_for_options(
        ticker, direction, entry_price, target_price
    )
    if is_valid and options_data:
        print(f"[OPTIONS] ✅ {ticker}: {reason}")
        return options_data
    else:
        print(f"[OPTIONS] ⚠️ {ticker}: {reason}")
        return None
