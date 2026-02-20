"""
Options Chain Filter Module
Analyzes options chains to validate signal quality and suggest optimal strikes.
INTEGRATED: IV Rank (IVR) + Unusual Options Activity (UOA) + GEX Levels.
"""

import requests
from datetime import datetime
from typing import Dict, Optional, Tuple
import config
from iv_tracker   import store_iv_observation, compute_ivr, ivr_to_confidence_multiplier
from uoa_scanner  import scan_chain_for_uoa
from gex_engine   import compute_gex_levels, get_gex_signal_context


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
        oi     = option.get("openInterest", 0)
        volume = option.get("volume", 0)
        bid    = option.get("bid", 0)
        ask    = option.get("ask", 0)
        if oi < config.MIN_OPTION_OI or volume < config.MIN_OPTION_VOLUME:
            return False
        if ask > 0 and bid > 0:
            mid = (bid + ask) / 2
            if mid > 0 and (ask - bid) / mid > config.MAX_BID_ASK_SPREAD_PCT:
                return False
        return True

    def filter_by_delta(self, option: Dict) -> bool:
        d = abs(option.get("delta", 0))
        return config.TARGET_DELTA_MIN <= d <= config.TARGET_DELTA_MAX

    def filter_by_dte(self, expiration_date: str) -> Tuple[bool, int]:
        try:
            dte = (datetime.strptime(expiration_date, "%Y-%m-%d") - datetime.now()).days
            return (config.MIN_DTE <= dte <= config.MAX_DTE), dte
        except Exception:
            return False, 0

    def calculate_expected_move(self, price: float, iv: float, dte: int) -> float:
        return round(price * iv * ((dte / 365) ** 0.5), 2)

    def find_best_strike(self, ticker: str, direction: str,
                         entry_price: float, target_price: float) -> Optional[Dict]:
        """Find the optimal option strike and enrich with IVR + UOA + GEX."""
        chain = self.get_options_chain(ticker)
        if not chain:
            return None

        best_option = None
        best_score  = -1

        for expiration_date, options_data in chain.get("data", {}).items():
            is_valid_dte, dte = self.filter_by_dte(expiration_date)
            if not is_valid_dte:
                continue

            option_type = "calls" if direction == "bull" else "puts"
            is_call     = (direction == "bull")

            for strike_str, option in options_data.get(option_type, {}).items():
                strike = float(strike_str)
                if not self.filter_by_liquidity(option):
                    continue
                if not self.filter_by_delta(option):
                    continue
                if is_call and not (entry_price * 0.95 <= strike <= entry_price * 1.10):
                    continue
                if not is_call and not (entry_price * 0.90 <= strike <= entry_price * 1.05):
                    continue

                bid = option.get("bid", 0)
                ask = option.get("ask", 0)
                mid = (bid + ask) / 2 if (bid and ask) else 0

                dte_score    = 100 - abs(dte - config.IDEAL_DTE)
                oi_score     = min(option.get("openInterest", 0) / 1000, 100)
                spread_pct   = (ask - bid) / mid if mid > 0 else 999
                spread_score = max(0, 100 - spread_pct * 1000)
                total_score  = dte_score + oi_score + spread_score

                if total_score > best_score:
                    best_score  = total_score
                    iv          = option.get("impliedVolatility", 0)
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
                "ivr": ivr, "ivr_obs": obs, "ivr_reliable": reliable,
                "ivr_multiplier": mult, "ivr_label": label
            })
            status = f"IVR={ivr:.0f}" if (ivr is not None and reliable) else "IVR-BUILDING"
            print(f"[IVR] {ticker}: IV={iv*100:.1f}% | {status} ({obs} obs) | {mult:.2f}x [{label}]")
        else:
            best_option.update({
                "ivr": None, "ivr_obs": 0, "ivr_reliable": False,
                "ivr_multiplier": 1.0, "ivr_label": "IVR-NO-DATA"
            })

        # ── UOA enrichment ───────────────────────────────────────────────
        try:
            uoa = scan_chain_for_uoa(chain, direction, entry_price)
            best_option.update({
                "uoa_multiplier":    uoa["multiplier"],
                "uoa_label":         uoa["label"],
                "uoa_detected":      uoa["uoa_detected"],
                "uoa_aligned":       uoa["aligned"],
                "uoa_opposing":      uoa["opposing"],
                "uoa_max_score":     uoa["max_uoa_score"],
                "uoa_top_aligned":   uoa.get("top_aligned",  []),
                "uoa_top_opposing":  uoa.get("top_opposing", [])
            })
            if uoa["uoa_detected"]:
                print(f"[UOA] {ticker}: {uoa['label']} | "
                      f"Aligned:{len(uoa['top_aligned'])} Opposing:{len(uoa['top_opposing'])}")
                for h in uoa["top_aligned"][:2]:
                    print(f"  \u2b06 {h['type'].upper()} ${h['strike']:.0f} "
                          f"exp {h['expiry']} | Vol {h['volume']:,} OI {h['oi']:,} | {h['uoa_score']:.2f}x")
                for h in uoa["top_opposing"][:2]:
                    print(f"  \u2b07 {h['type'].upper()} ${h['strike']:.0f} "
                          f"exp {h['expiry']} | Vol {h['volume']:,} OI {h['oi']:,} | {h['uoa_score']:.2f}x")
            else:
                print(f"[UOA] {ticker}: No unusual activity")
        except Exception as e:
            print(f"[UOA] {ticker} error: {e}")
            best_option.update({
                "uoa_multiplier": 1.0, "uoa_label": "UOA-ERROR",
                "uoa_detected": False, "uoa_aligned": False,
                "uoa_opposing": False, "uoa_max_score": 0.0,
                "uoa_top_aligned": [], "uoa_top_opposing": []
            })

        # ── GEX enrichment ───────────────────────────────────────────────
        try:
            gex_data = compute_gex_levels(chain, entry_price)
            if gex_data["has_data"]:
                gex_mult, gex_label, gex_ctx = get_gex_signal_context(
                    gex_data, direction, entry_price,
                    best_option.get("strike", entry_price),   # stop proxy
                    target_price
                )
                best_option.update({
                    "gex_multiplier": gex_mult,
                    "gex_label":      gex_label,
                    "gamma_pin":      gex_data["gamma_pin"],
                    "gamma_flip":     gex_data["gamma_flip"],
                    "neg_gex_zone":   gex_data["neg_gex_zone"],
                    "total_gex":      gex_data["total_gex"],
                    "gex_top_pos":    gex_data["top_positive"],
                    "gex_top_neg":    gex_data["top_negative"]
                })
                flip_str = f"${gex_data['gamma_flip']:.2f}" if gex_data["gamma_flip"] else "N/A"
                pin_str  = f"${gex_data['gamma_pin']:.2f}"  if gex_data["gamma_pin"]  else "N/A"
                zone     = "NEG" if gex_data["neg_gex_zone"] else "POS"
                print(f"[GEX] {ticker}: Pin={pin_str} | Flip={flip_str} | "
                      f"Zone={zone} | {gex_mult:.2f}x [{gex_label}]")
            else:
                print(f"[GEX] {ticker}: No gamma data in chain")
                best_option.update({
                    "gex_multiplier": 1.0, "gex_label": "GEX-NO-DATA",
                    "gamma_pin": None, "gamma_flip": None,
                    "neg_gex_zone": False, "total_gex": 0.0,
                    "gex_top_pos": [], "gex_top_neg": []
                })
        except Exception as e:
            print(f"[GEX] {ticker} error: {e}")
            best_option.update({
                "gex_multiplier": 1.0, "gex_label": "GEX-ERROR",
                "gamma_pin": None, "gamma_flip": None,
                "neg_gex_zone": False, "total_gex": 0.0,
                "gex_top_pos": [], "gex_top_neg": []
            })

        return best_option

    def validate_signal_for_options(self, ticker, direction, entry_price,
                                    target_price) -> Tuple[bool, Optional[Dict], str]:
        best_strike = self.find_best_strike(ticker, direction, entry_price, target_price)
        if not best_strike:
            return False, None, "No suitable options found"

        if abs(target_price - entry_price) > best_strike["expected_move"] * 2:
            return False, best_strike, "Target exceeds 2x expected move"

        if best_strike.get("iv", 0) > 1.0:
            return False, best_strike, f"IV too high ({best_strike['iv']*100:.1f}%)"

        dte = best_strike["dte"]
        mid = (best_strike["bid"] + best_strike["ask"]) / 2 if (
            best_strike.get("bid") and best_strike.get("ask")
        ) else 0
        if mid > 0 and dte > 0 and (mid / dte) / mid > config.MAX_THETA_DECAY_PCT:
            return False, best_strike, "Theta decay too high"

        return True, best_strike, "Options signal validated"


def get_options_recommendation(ticker, direction, entry_price,
                               target_price) -> Optional[Dict]:
    f = OptionsFilter()
    is_valid, data, reason = f.validate_signal_for_options(
        ticker, direction, entry_price, target_price
    )
    if is_valid and data:
        print(f"[OPTIONS] \u2705 {ticker}: {reason}")
        return data
    print(f"[OPTIONS] \u26a0\ufe0f {ticker}: {reason}")
    return None
