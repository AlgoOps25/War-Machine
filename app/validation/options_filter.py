"""
options_filter.py — Options Chain Validation
Extracted from validation.py (Phase 3A consolidation) to reduce file size.
OptionsFilter + get_options_recommendation live here; validation.py re-exports.
"""
from __future__ import annotations
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple
from zoneinfo import ZoneInfo
import requests
import logging

from utils import config
from app.options.iv_tracker import store_iv_observation, compute_ivr, ivr_to_confidence_multiplier
from app.options.gex_engine import compute_gex_levels, get_gex_signal_context

logger = logging.getLogger(__name__)

try:
    from app.options.options_intelligence import scan_chain_for_uoa
    from uoa_scanner import format_uoa_summary
except ImportError:
    def scan_chain_for_uoa(*a, **kw):
        return {'uoa_multiplier': 1.0, 'uoa_label': 'UOA-UNAVAILABLE',
                'uoa_detected': False, 'uoa_aligned': False, 'uoa_opposing': False,
                'uoa_max_score': 0.0, 'uoa_top_aligned': [], 'uoa_top_opposing': []}
    def format_uoa_summary(d): return "UOA scanner unavailable"

try:
    from app.options.options_optimizer import get_optimal_strikes_sync
    _OPTIMIZER_AVAILABLE = True
except ImportError:
    _OPTIMIZER_AVAILABLE = False

# IVR gate thresholds (Phase P2-1)
IVR_HARD_BLOCK = 80
IVR_WARN       = 60


class OptionsFilter:
    """Filters and analyzes options chains for trading signals."""

    def __init__(self):
        self.api_key  = config.EODHD_API_KEY
        self.base_url = "https://eodhd.com/api/mp/unicornbay/options/contracts"

    def _get_ivr_for_gate(self, ticker: str) -> Tuple[Optional[float], int, bool]:
        """Pull ATM IV from greeks_cache and compute IVR — zero extra API calls."""
        try:
            from app.validation.greeks_precheck import greeks_cache
            cache_data = greeks_cache._cache.get(ticker, {})
            if not cache_data:
                return None, 0, False
            best_iv, best_diff = None, 999.0
            for _strike, opts in cache_data.items():
                call = opts.get("call")
                if call and call.iv > 0:
                    diff = abs(call.delta - 0.50)
                    if diff < best_diff:
                        best_diff, best_iv = diff, call.iv
            if not best_iv:
                return None, 0, False
            return compute_ivr(ticker, best_iv)
        except Exception as e:
            logger.debug(f"[IVR-GATE] {ticker}: _get_ivr_for_gate error — {e}")
            return None, 0, False

    def _normalize_v2_chain(self, v2_data: List[Dict]) -> Dict:
        nested: Dict = {}
        for item in v2_data:
            attrs  = item.get("attributes", item)
            exp    = attrs.get("exp_date", "")
            ctype  = attrs.get("type", "").lower()
            strike = str(attrs.get("strike", ""))
            if not exp or ctype not in ("call", "put") or not strike:
                continue
            if exp not in nested:
                nested[exp] = {"calls": {}, "puts": {}}
            bucket = "calls" if ctype == "call" else "puts"
            nested[exp][bucket][strike] = {
                "openInterest":      attrs.get("open_interest", 0),
                "volume":            attrs.get("volume", 0),
                "bid":               attrs.get("bid", 0),
                "ask":               attrs.get("ask", 0),
                "delta":             attrs.get("delta", 0),
                "impliedVolatility": attrs.get("volatility", 0),
                "theta":             attrs.get("theta", 0),
                "gamma":             attrs.get("gamma", 0),
                "vega":              attrs.get("vega", 0),
                "rho":               attrs.get("rho", 0),
                "dte":               attrs.get("dte", 0),
            }
        return nested

    def get_options_chain(self, ticker: str) -> Optional[Dict]:
        today  = datetime.now()
        params = {
            "filter[underlying_symbol]": ticker,
            "filter[exp_date_from]": (today - timedelta(days=1)).strftime("%Y-%m-%d"),
            "filter[exp_date_to]":   (today + timedelta(days=30)).strftime("%Y-%m-%d"),
            "sort": "exp_date", "limit": 1000, "api_token": self.api_key,
        }
        try:
            r = requests.get(self.base_url, params=params, timeout=10)
            r.raise_for_status()
            raw   = r.json()
            items = raw.get("data", [])
            return {"data": self._normalize_v2_chain(items)} if isinstance(items, list) else raw
        except Exception as e:
            logger.info(f"[OPTIONS] Error fetching chain for {ticker}: {e}")
            return None

    def filter_by_liquidity(self, option: Dict) -> bool:
        oi, vol = option.get("openInterest", 0), option.get("volume", 0)
        bid, ask = option.get("bid", 0), option.get("ask", 0)
        if oi < config.MIN_OPTION_OI or vol < config.MIN_OPTION_VOLUME:
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
            now_et = datetime.now(ZoneInfo("America/New_York")).replace(
                hour=0, minute=0, second=0, microsecond=0, tzinfo=None
            )
            dte = (datetime.strptime(expiration_date, "%Y-%m-%d") - now_et).days
            return (config.MIN_DTE <= dte <= config.MAX_DTE), dte
        except Exception:
            return False, 0

    def calculate_expected_move(self, price: float, iv: float, dte: int) -> float:
        return round(price * iv * ((dte / 365) ** 0.5), 2)

    def find_best_strike(self, ticker, direction, entry_price, target_price,
                         stop_price: float = 0.0, ideal_dte: Optional[int] = None):
        _ideal_dte = ideal_dte if ideal_dte is not None else config.IDEAL_DTE

        if _OPTIMIZER_AVAILABLE:
            try:
                strikes = get_optimal_strikes_sync(
                    ticker=ticker, current_price=entry_price, direction=direction,
                    target_delta_min=config.TARGET_DELTA_MIN,
                    target_delta_max=config.TARGET_DELTA_MAX
                )
                if strikes:
                    return strikes[0]
                logger.info(f"[OPTIONS] {ticker}: No strikes from optimizer")
            except Exception as e:
                logger.info(f"[OPTIONS] {ticker}: Optimizer error — {e}, falling back")

        chain = self.get_options_chain(ticker)
        if not chain:
            return None

        best_option, best_score = None, -1
        is_call     = (direction == "bull")
        option_type = "calls" if is_call else "puts"

        for exp_date, options_data in chain.get("data", {}).items():
            is_valid_dte, dte = self.filter_by_dte(exp_date)
            if not is_valid_dte:
                continue
            for strike_str, option in options_data.get(option_type, {}).items():
                strike = float(strike_str)
                if not self.filter_by_liquidity(option) or not self.filter_by_delta(option):
                    continue
                if is_call  and not (entry_price * 0.95 <= strike <= entry_price * 1.10): continue
                if not is_call and not (entry_price * 0.90 <= strike <= entry_price * 1.05): continue

                bid, ask = option.get("bid", 0), option.get("ask", 0)
                mid = (bid + ask) / 2 if (bid and ask) else 0
                delta_score  = max(0, 50 - abs(abs(option.get("delta", 0)) - config.IDEAL_DELTA) * 200)
                dte_score    = 100 - abs(dte - _ideal_dte)
                oi_score     = min(option.get("openInterest", 0) / 1000, 100)
                spread_pct   = (ask - bid) / mid if mid > 0 else 999
                spread_score = max(0, 100 - spread_pct * 1000)
                total_score  = dte_score + oi_score + spread_score + delta_score

                if total_score > best_score:
                    best_score = total_score
                    iv = option.get("impliedVolatility", 0)
                    best_option = {
                        "strike": strike, "expiration": exp_date,
                        "delta": option.get("delta", 0), "theta": option.get("theta", 0),
                        "oi": option.get("openInterest", 0), "volume": option.get("volume", 0),
                        "bid": bid, "ask": ask, "iv": iv, "dte": dte,
                        "expected_move": self.calculate_expected_move(entry_price, iv, dte),
                        "score": total_score
                    }

        if not best_option:
            return None

        # IVR enrichment
        iv = best_option.get("iv", 0)
        if iv and iv > 0:
            store_iv_observation(ticker, iv)
            ivr, obs, reliable = compute_ivr(ticker, iv)
            mult, label = ivr_to_confidence_multiplier(ivr, reliable)
            best_option.update({"ivr": ivr, "ivr_obs": obs, "ivr_reliable": reliable,
                                 "ivr_multiplier": mult, "ivr_label": label})
            status = f"IVR={ivr:.0f}" if (ivr is not None and reliable) else "IVR-BUILDING"
            logger.info(f"[IVR] {ticker}: IV={iv*100:.1f}% | {status} ({obs} obs) | {mult:.2f}x [{label}]")
        else:
            best_option.update({"ivr": None, "ivr_obs": 0, "ivr_reliable": False,
                                 "ivr_multiplier": 1.0, "ivr_label": "IVR-NO-DATA"})

        # UOA enrichment
        try:
            uoa = scan_chain_for_uoa(ticker, direction, entry_price)
            best_option.update(uoa)
            if uoa.get('uoa_detected'):
                logger.info(f"[UOA] {ticker}: {format_uoa_summary(uoa)}")
            else:
                logger.info(f"[UOA] {ticker}: No unusual activity")
        except Exception as e:
            logger.info(f"[UOA] {ticker} error: {e}")
            best_option.update({'uoa_multiplier': 1.0, 'uoa_label': 'UOA-ERROR',
                                 'uoa_detected': False, 'uoa_aligned': False,
                                 'uoa_opposing': False, 'uoa_max_score': 0.0,
                                 'uoa_top_aligned': [], 'uoa_top_opposing': []})

        # GEX enrichment
        gex_stop = stop_price if stop_price > 0 else best_option.get("strike", entry_price)
        try:
            gex_data = compute_gex_levels(chain, entry_price)
            if gex_data["has_data"]:
                gex_mult, gex_label, _ = get_gex_signal_context(
                    gex_data, direction, entry_price, gex_stop, target_price
                )
                best_option.update({
                    "gex_multiplier": gex_mult, "gex_label": gex_label,
                    "gamma_pin": gex_data["gamma_pin"], "gamma_flip": gex_data["gamma_flip"],
                    "neg_gex_zone": gex_data["neg_gex_zone"], "total_gex": gex_data["total_gex"],
                    "gex_top_pos": gex_data["top_positive"], "gex_top_neg": gex_data["top_negative"]
                })
                flip = f"${gex_data['gamma_flip']:.2f}" if gex_data["gamma_flip"] else "N/A"
                pin  = f"${gex_data['gamma_pin']:.2f}" if gex_data["gamma_pin"] else "N/A"
                zone = "NEG" if gex_data["neg_gex_zone"] else "POS"
                logger.info(f"[GEX] {ticker}: Pin={pin} | Flip={flip} | Zone={zone} | {gex_mult:.2f}x [{gex_label}]")
            else:
                logger.info(f"[GEX] {ticker}: No gamma data")
                best_option.update({"gex_multiplier": 1.0, "gex_label": "GEX-NO-DATA",
                                     "gamma_pin": None, "gamma_flip": None,
                                     "neg_gex_zone": False, "total_gex": 0.0,
                                     "gex_top_pos": [], "gex_top_neg": []})
        except Exception as e:
            logger.info(f"[GEX] {ticker} error: {e}")
            best_option.update({"gex_multiplier": 1.0, "gex_label": "GEX-ERROR",
                                 "gamma_pin": None, "gamma_flip": None,
                                 "neg_gex_zone": False, "total_gex": 0.0,
                                 "gex_top_pos": [], "gex_top_neg": []})

        # Limit-price entry enrichment
        _bid, _ask = best_option["bid"], best_option["ask"]
        _mid  = round((_bid + _ask) / 2, 2) if (_bid and _ask) else 0.0
        _spd  = round(((_ask - _bid) / _mid) * 100, 1) if _mid > 0 else 0.0
        _ctype = "CALL" if direction == "bull" else "PUT"
        try:
            _m, _d = int(best_option["expiration"][5:7]), int(best_option["expiration"][8:10])
            _exp_label = f"{_m}/{_d}"
        except Exception:
            _exp_label = best_option["expiration"]
        best_option.update({
            "mid": _mid, "limit_entry": _mid, "max_entry": _ask,
            "contract_type": _ctype, "spread_pct": _spd,
            "contract_label": f"{ticker} ${int(best_option['strike'])}{_ctype[0]} {_exp_label}",
        })
        logger.info(
            f"[LIMIT-ENTRY] {ticker}: {_ctype} ${int(best_option['strike'])} "
            f"Bid:${_bid:.2f}  Mid:${_mid:.2f}  Ask:${_ask:.2f}  Spread:{_spd:.1f}%"
        )
        return best_option

    def validate_signal_for_options(
        self, ticker, direction, entry_price, target_price,
        stop_price: float = 0.0, explosive_mover: bool = False,
        ideal_dte: Optional[int] = None,
    ) -> Tuple[bool, Optional[Dict], str]:
        # Gate 1: IVR pre-check
        ivr_val, ivr_obs, ivr_reliable = self._get_ivr_for_gate(ticker)
        _ivr_warning_flag = False
        if ivr_reliable and ivr_val is not None and isinstance(ivr_val, (int, float)):
            if ivr_val > IVR_HARD_BLOCK:
                msg = f"IVR too high ({ivr_val:.0f}>{IVR_HARD_BLOCK}) — options crush risk ({ivr_obs} obs)"
                if explosive_mover:
                    logger.info(f"[IVR-GATE] WARNING {ticker} HIGH-IVR EXPLOSIVE MOVER: {msg} — proceeding")
                    _ivr_warning_flag = True
                else:
                    logger.info(f"[IVR-GATE] BLOCKED {ticker}: {msg}")
                    return False, None, msg
            elif ivr_val > IVR_WARN:
                logger.info(f"[IVR-GATE] WARNING {ticker}: IVR={ivr_val:.0f} elevated — proceeding with caution")
                _ivr_warning_flag = True

        # Gate 2: find best strike
        best = self.find_best_strike(ticker, direction, entry_price, target_price,
                                     stop_price=stop_price, ideal_dte=ideal_dte)
        if not best:
            return False, None, "No suitable options found"

        if _ivr_warning_flag:
            best["ivr_elevated_warning"] = True
            best["ivr_gate_val"] = round(ivr_val, 1) if ivr_val else None

        # Gate 3: expected move
        if abs(target_price - entry_price) > best["expected_move"] * 2:
            return False, best, "Target exceeds 2x expected move"

        # Gate 4: IV > 100%
        iv = best.get("iv", 0)
        if iv > 1.0:
            iv_pct = iv * 100
            if explosive_mover:
                logger.info(f"[OPTIONS-GATE] WARNING {ticker} HIGH-IV EXPLOSIVE MOVER: IV={iv_pct:.1f}% — proceeding")
                best["high_iv_warning"] = True
                best["high_iv_pct"]     = round(iv_pct, 1)
            else:
                return False, best, f"IV too high ({iv_pct:.1f}%)"

        # Gate 5: theta decay
        mid   = (best.get("bid", 0) + best.get("ask", 0)) / 2 if best.get("bid") else 0
        theta = abs(best.get("theta", 0))
        if mid > 0 and best["dte"] > 0 and theta > 0:
            theta_pct = theta / mid
            if theta_pct > config.MAX_THETA_DECAY_PCT:
                return False, best, f"Theta decay too high ({theta_pct:.1%}/day)"

        iv_warn  = " [HIGH-IV]"  if best.get("high_iv_warning") else ""
        ivr_warn = " [HIGH-IVR]" if best.get("ivr_elevated_warning") else ""
        return True, best, f"Options signal validated{iv_warn}{ivr_warn}"


def get_options_recommendation(ticker, direction, entry_price, target_price,
                               stop_price: float = 0.0) -> Optional[Dict]:
    f = OptionsFilter()
    is_valid, data, reason = f.validate_signal_for_options(
        ticker, direction, entry_price, target_price, stop_price=stop_price
    )
    if is_valid and data:
        logger.info(f"[OPTIONS] OK {ticker}: {reason}")
        return data
    logger.info(f"[OPTIONS] WARNING {ticker}: {reason}")
    return None
