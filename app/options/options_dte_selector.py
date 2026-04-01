"""
Options DTE Selector - Data-Driven Expiration Selection with Historical Learning

Integrates:
- Historical win rates from positions DB (40% weight)
- Live options market data from EODHD (35% weight)
- Regime context: ADX + VIX + target distance (25% weight)

Architecture note (Phase 2, Mar 26 2026):
  This class is the DTE decision layer — it decides whether to use 0DTE or 1DTE
  based on a weighted combination of historical performance, live chain quality,
  and market regime. It does NOT select specific strikes (that is
  OptionsDataManager / options_strike_selector.py's job).

  Callers: app/core/sniper_pipeline.py (indirectly via dte_selector global instance)

Phase 6 P2-1 (2026-04-01):
  Added IVR hard gate via _ivr_gate().
  - Debit trades (BUY calls / SELL puts) blocked when IVR >= 50 — paying inflated premium
  - Credit trades (SELL calls / BUY puts) blocked when IVR <= 60 — selling cheap premium
  - IVR-BUILDING state passes through — no false blocks during data accumulation

Phase 6 P2-2 (2026-04-01):
  ATR-adjusted delta target band in select_best_strikes().
  - atr_pct (ATR as % of entry price) shifts the optimal delta window:
      atr_pct < 0.5%  → tight market  → target 0.40–0.45Δ
      atr_pct 0.5–1.2% → normal        → target 0.35–0.45Δ  (default)
      atr_pct > 1.2%  → volatile       → target 0.30–0.45Δ
  - Rationale: in tight markets a 0.40Δ strike costs less in theta/premium
    and provides cleaner directional exposure; in volatile markets gamma pays
    on wider swings so a 0.30Δ entry is acceptable.
  - delta_band label appended to reasoning string for Discord visibility.
  - Backward-compatible: atr=None defaults to normal regime (atr_pct=0.75%).
"""
from typing import Dict, List, Optional
from datetime import datetime, timedelta, date
from zoneinfo import ZoneInfo
import requests
import os
import logging
logger = logging.getLogger(__name__)

ET = ZoneInfo("America/New_York")

# IVR gate thresholds (47.P2-1)
IVR_DEBIT_MAX  = 50   # block debit spreads at or above this IVR
IVR_CREDIT_MIN = 60   # block credit spreads at or below this IVR

# ATR delta-band thresholds (47.P2-2)
_ATR_TIGHT_PCT    = 0.005   # < 0.5%  → tight regime
_ATR_VOLATILE_PCT = 0.012   # > 1.2%  → volatile regime


class OptionsDTESelector:
    def __init__(self, eodhd_api_key: Optional[str] = None):
        self.api_key = eodhd_api_key or os.getenv('EODHD_API_KEY')
        if not self.api_key:
            raise ValueError("EODHD_API_KEY required")

        self.min_open_interest = 100
        self.min_volume = 50
        self.min_total_volume = 25
        self.max_spread_pct = 10.0
        self.max_iv_premium_pct = 20.0

        # Try to import historical advisor
        try:
            from app.options.dte_historical_advisor import dte_advisor
            self.historical_advisor = dte_advisor
        except Exception:
            self.historical_advisor = None
            logger.info("[OPTIONS-DTE] Historical advisor unavailable")

        logger.info("[OPTIONS-DTE] Initialized with data-driven approach")

    # ------------------------------------------------------------------
    # IVR Hard Gate (47.P2-1)
    # ------------------------------------------------------------------

    def _ivr_gate(self, ticker: str, direction: str, contracts: list) -> tuple:
        """
        Hard IVR gate — blocks trades where IV cost/benefit is unfavourable.

        Trade type classification:
          BUY  direction → buying calls  → DEBIT  → want cheap IV (IVR < 50)
          SELL direction → buying puts   → DEBIT  → want cheap IV (IVR < 50)
          (credit spreads are the inverse — want expensive IV)

        For War Machine's 0DTE/1DTE architecture all directional trades are
        debit buys (long call or long put).  Direction 'BUY' = long call,
        direction 'SELL' = long put.  Both are debits.

        Returns:
          (blocked: bool, reason: str, ivr_label: str)
          blocked=False when IVR is building (< MIN_OBSERVATIONS) — pass through.
        """
        from app.options.iv_tracker import compute_ivr, ivr_to_confidence_multiplier

        if not contracts:
            return False, "", "IVR-NO-DATA"

        # Use average IV from the fetched contracts as current_iv proxy
        ivs = [c.get('volatility', 0.0) for c in contracts if c.get('volatility', 0.0) > 0]
        if not ivs:
            return False, "", "IVR-NO-IV"

        current_iv = sum(ivs) / len(ivs)
        ivr, observations, is_reliable = compute_ivr(ticker, current_iv)
        _multiplier, ivr_label = ivr_to_confidence_multiplier(ivr, is_reliable)

        if not is_reliable:
            # Still accumulating history — never block
            logger.info(f"[IVR-GATE] {ticker} IVR building ({observations} obs) — pass through")
            return False, "", ivr_label

        # War Machine trades are always debit (long call or long put)
        # Block debit when IV is at or above neutral (IVR >= 50)
        if ivr >= IVR_DEBIT_MAX:
            reason = (
                f"IVR {ivr:.0f} >= {IVR_DEBIT_MAX} — debit options overpriced "
                f"(IV crush risk). Gate: P2-1."
            )
            logger.warning(f"[IVR-GATE] {ticker} BLOCKED — {reason}")
            return True, reason, ivr_label

        logger.info(f"[IVR-GATE] {ticker} PASSED — {ivr_label} (IVR {ivr:.0f} < {IVR_DEBIT_MAX})")
        return False, "", ivr_label

    # ------------------------------------------------------------------
    # Main entry point
    # ------------------------------------------------------------------

    def calculate_optimal_dte(
        self,
        ticker: str,
        entry_price: float,
        direction: str,
        confidence: float,
        adx: float = None,
        vix: float = None,
        t1_price: float = None,
        t2_price: float = None,
        current_time: Optional[datetime] = None,
        atr: float = None,          # 47.P2-2: intraday ATR in price units
    ) -> Dict:
        """Calculate optimal DTE using historical + live + regime data.

        Args:
            atr: Intraday ATR in price units (e.g. 1.25 for a $1.25 ATR on a
                 $250 stock).  Converted internally to atr_pct for
                 select_best_strikes().  Defaults to None → normal regime.
        """
        if current_time is None:
            current_time = datetime.now(ET)

        market_close = current_time.replace(hour=16, minute=0, second=0, microsecond=0)
        time_remaining_hours = (market_close - current_time).total_seconds() / 3600

        if time_remaining_hours <= 0:
            return self._create_skip_response("Market closed", time_remaining_hours)

        # Compute ATR as a fraction of price for downstream band selection.
        # Default 0.0075 (0.75%) → normal regime when ATR not supplied.
        atr_pct: float = (atr / entry_price) if (atr and entry_price > 0) else 0.0075

        # Fetch options data from EODHD
        try:
            options_data = self.fetch_options_chain(ticker, entry_price, direction)
            if not options_data:
                return self._create_regime_fallback(time_remaining_hours, adx, vix, t1_price, entry_price, "No options data")
        except Exception as e:
            return self._create_regime_fallback(time_remaining_hours, adx, vix, t1_price, entry_price, f"API error: {e}")

        # IVR hard gate (47.P2-1) — runs before DTE scoring
        ivr_blocked, ivr_reason, ivr_label = self._ivr_gate(ticker, direction, options_data)
        if ivr_blocked:
            return self._create_skip_response(ivr_reason, time_remaining_hours)

        dte_0_contracts = [opt for opt in options_data if opt['dte'] == 0]
        dte_1_contracts = [opt for opt in options_data if opt['dte'] == 1]

        if not dte_0_contracts and not dte_1_contracts:
            return self._create_regime_fallback(time_remaining_hours, adx, vix, t1_price, entry_price, "No contracts")

        # Score using combined approach
        final_dte, reasoning, confidence_pct = self._calculate_combined_score(
            dte_0_contracts, dte_1_contracts, time_remaining_hours,
            adx, vix, t1_price, entry_price, direction, current_time
        )

        if final_dte is None:
            return self._create_skip_response("No viable DTE", time_remaining_hours)

        selected_contracts = dte_0_contracts if final_dte == 0 else dte_1_contracts

        # 47.P2-2: pass atr_pct so strike selector uses ATR-aware delta band
        best_strikes, delta_band_label = self.select_best_strikes(
            selected_contracts, entry_price, direction, atr_pct=atr_pct
        )

        if not best_strikes:
            return self._create_regime_fallback(time_remaining_hours, adx, vix, t1_price, entry_price, f"No {final_dte}DTE strikes")

        return {
            'dte': final_dte,
            'expiry_date': best_strikes[0]['exp_date'],
            'recommended_strikes': best_strikes[:2],
            'reasoning': reasoning + f"\n📊 {ivr_label}" + f"\n🎯 {delta_band_label}",
            'time_remaining_hours': round(time_remaining_hours, 2),
            'confidence_pct': round(confidence_pct, 1)
        }

    def _calculate_combined_score(self, dte_0, dte_1, time_remaining_hours, adx, vix, t1_price, entry_price, direction, current_time):
        """Combine historical + live options + regime scores."""
        scores = {'0dte': 0.0, '1dte': 0.0}
        weights = {'historical': 0.40, 'options': 0.35, 'regime': 0.25}
        reasoning_parts = []

        # Historical score (40%)
        if self.historical_advisor and adx and vix and t1_price:
            target_pct = abs((t1_price - entry_price) / entry_price * 100)
            hist_rec = self.historical_advisor.get_recommendation(
                hour_of_day=current_time.hour, adx=adx, vix=vix, target_pct=target_pct, direction=direction
            )
            if hist_rec['has_preference']:
                rec_dte = hist_rec['recommended_dte']
                hist_score = hist_rec['confidence'] / 100.0
                scores[f"{rec_dte}dte"] += hist_score * weights['historical'] * 100
                reasoning_parts.append(f"📊 Historical: {rec_dte}DTE ({hist_rec['reason']})")
            else:
                reasoning_parts.append(f"📊 Historical: No preference ({hist_rec['reason']})")

        # Live options score (35%)
        if dte_0:
            factors = self._analyze_dte_factors(dte_0, dte_1, time_remaining_hours)
            live_score = self._calculate_dte_score(factors)
            scores['0dte'] += (live_score / 10.5) * weights['options'] * 100
            reasoning_parts.append(f"💹 Live Options: 0DTE scored {live_score:.1f}/10.5")

        # Regime score (25%)
        if adx and vix and t1_price:
            regime_score = self._calculate_regime_score(adx, vix, t1_price, entry_price, time_remaining_hours)
            if regime_score['favors'] == 0:
                scores['0dte'] += regime_score['score'] * weights['regime'] * 100
            else:
                scores['1dte'] += regime_score['score'] * weights['regime'] * 100
            reasoning_parts.append(f"🎯 Regime: Favors {regime_score['favors']}DTE ({regime_score['reason']})")

        # Final decision
        if scores['0dte'] > scores['1dte'] and scores['0dte'] > 50:
            return 0, "\n".join(["✅ SELECTED: 0DTE"] + reasoning_parts), scores['0dte']
        elif scores['1dte'] >= scores['0dte'] and scores['1dte'] > 30:
            return 1, "\n".join(["📅 SELECTED: 1DTE"] + reasoning_parts), scores['1dte']
        else:
            return None, "Scores too low", 0

    def _calculate_regime_score(self, adx, vix, t1_price, entry_price, time_remaining):
        """Score DTE based on market regime.

        FIX #19 (Mar 27 2026): Added `favors = 0` safe default at top of function.
        Previously, if VIX was in the neutral 15-25 range AND target distance was
        in the neutral 0.5-1.2% range, neither branch assigned `favors`, causing
        a NameError at `return {'favors': favors, ...}`.
        """
        target_pct = abs((t1_price - entry_price) / entry_price * 100)
        score = 0.0
        reasons = []
        favors = 0  # FIX #19: safe default — 0DTE favored unless a branch overrides

        # ADX: Choppy markets need more time
        if adx < 15:
            score += 0.3
            favors = 1
            reasons.append("choppy ADX")
        elif adx > 25:
            score += 0.4
            favors = 0
            reasons.append("strong trend")
        else:
            score += 0.2
            favors = 0 if time_remaining > 3 else 1

        # VIX: High volatility needs buffer
        if vix > 25:
            score += 0.3
            favors = 1
            reasons.append("elevated VIX")
        elif vix < 15:
            score += 0.3
            favors = 0
            reasons.append("low VIX")
        else:
            score += 0.2
            # neutral VIX — favors unchanged from ADX decision

        # Target distance: Larger moves need more time
        if target_pct > 1.2:
            score += 0.4
            favors = 1
            reasons.append("large target")
        elif target_pct < 0.5:
            score += 0.3
            favors = 0
            reasons.append("tight target")
        else:
            score += 0.2
            # neutral target — favors unchanged from prior decisions

        return {'favors': favors, 'score': min(score, 1.0), 'reason': ", ".join(reasons)}

    def _create_regime_fallback(self, time_remaining, adx, vix, t1_price, entry_price, reason):
        """Fallback using regime scoring only."""
        if not adx or not vix or not t1_price:
            dte = 0 if time_remaining >= 3.0 else (1 if time_remaining >= 1.0 else None)
            if dte is None:
                return self._create_skip_response("Too late", time_remaining)
            return {'dte': dte, 'expiry_date': None, 'recommended_strikes': [],
                    'reasoning': f"⚠️ Fallback (time-based): {dte}DTE\n{reason}",
                    'time_remaining_hours': round(time_remaining, 2), 'confidence_pct': 30}

        regime = self._calculate_regime_score(adx, vix, t1_price, entry_price, time_remaining)
        dte = regime['favors']
        return {'dte': dte, 'expiry_date': None, 'recommended_strikes': [],
                'reasoning': f"⚠️ Fallback (regime-based): {dte}DTE\n{reason}\n🎯 {regime['reason']}",
                'time_remaining_hours': round(time_remaining, 2), 'confidence_pct': 40}

    def fetch_options_chain(self, ticker, price, direction):
        today = datetime.now(ET).date()
        dte_0_date = self._get_next_trading_day(today, 0)
        dte_1_date = self._get_next_trading_day(today, 1)
        option_type = "call" if direction == "BUY" else "put"
        strike_low, strike_high = int(price * 0.95), int(price * 1.05)
        url = f"https://eodhd.com/api/options/{ticker}"
        params = {"api_token": self.api_key, "from": str(dte_0_date), "to": str(dte_1_date), "contract_name": option_type}
        try:
            response = requests.get(url, params=params, timeout=10)
            response.raise_for_status()
            data = response.json()
        except Exception:
            return []
        if not data or 'data' not in data:
            return []
        contracts = []
        for c in data['data']:
            try:
                exp_date = datetime.strptime(c['expirationDate'], '%Y-%m-%d').date()
                dte = (exp_date - today).days
                if dte not in [0, 1]:
                    continue
                strike = float(c.get('strike', 0))
                if strike < strike_low or strike > strike_high:
                    continue
                contracts.append({'contract': c.get('contractName', ''), 'strike': strike, 'exp_date': str(exp_date),
                                 'dte': dte, 'bid': float(c.get('bid', 0)), 'ask': float(c.get('ask', 0)),
                                 'last_price': float(c.get('lastPrice', 0)), 'volume': int(c.get('volume', 0)),
                                 'open_interest': int(c.get('openInterest', 0)), 'delta': float(c.get('delta', 0)),
                                 'gamma': float(c.get('gamma', 0)), 'theta': float(c.get('theta', 0)),
                                 'vega': float(c.get('vega', 0)), 'volatility': float(c.get('impliedVolatility', 0))})
            except Exception:
                continue
        return contracts

    def _analyze_dte_factors(self, dte_0, dte_1, time_remaining):
        return {'time_adequate': time_remaining >= 1.5, 'dte_0_liquid': self._check_liquidity(dte_0),
                'dte_0_theta_acceptable': self._check_theta_decay(dte_0, time_remaining),
                'dte_0_spread_tight': self._check_bid_ask_spread(dte_0),
                'iv_favorable': self._check_iv_levels(dte_0, dte_1), 'volume_sufficient': self._check_volume(dte_0)}

    def _check_liquidity(self, contracts):
        if not contracts:
            return False
        avg_oi = sum(c.get('open_interest', 0) for c in contracts) / len(contracts)
        avg_volume = sum(c.get('volume', 0) for c in contracts) / len(contracts)
        return avg_oi > self.min_open_interest and avg_volume > self.min_volume

    def _check_theta_decay(self, contracts, time_remaining):
        if not contracts:
            return False
        avg_theta = abs(sum(c.get('theta', 0) for c in contracts) / len(contracts))
        if time_remaining >= 4:
            return True
        elif time_remaining >= 2:
            return avg_theta < 0.15
        else:
            return avg_theta < 0.08

    def _check_bid_ask_spread(self, contracts):
        if not contracts:
            return False
        tight_spreads = []
        for c in contracts:
            bid, ask = c.get('bid', 0), c.get('ask', 0)
            if bid > 0 and ask > 0:
                mid = (bid + ask) / 2
                spread_pct = ((ask - bid) / mid) * 100
                tight_spreads.append(spread_pct < self.max_spread_pct)
        return len(tight_spreads) > 0 and sum(tight_spreads) / len(tight_spreads) > 0.7

    def _check_iv_levels(self, dte_0, dte_1):
        if not dte_0 or not dte_1:
            return True
        avg_iv_0 = sum(c.get('volatility', 0) for c in dte_0) / len(dte_0)
        avg_iv_1 = sum(c.get('volatility', 0) for c in dte_1) / len(dte_1)
        if avg_iv_1 == 0:
            return True
        iv_premium = ((avg_iv_0 - avg_iv_1) / avg_iv_1) * 100
        return iv_premium < self.max_iv_premium_pct

    def _check_volume(self, contracts):
        if not contracts:
            return False
        return sum(c.get('volume', 0) for c in contracts) > self.min_total_volume

    def _calculate_dte_score(self, factors):
        score = 0.0
        score += 3.0 if factors['time_adequate'] else 0
        score += 2.0 if factors['dte_0_liquid'] else 0
        score += 2.0 if factors['dte_0_theta_acceptable'] else 0
        score += 1.5 if factors['dte_0_spread_tight'] else 0
        score += 1.0 if factors['iv_favorable'] else 0
        score += 1.0 if factors['volume_sufficient'] else 0
        return score

    def select_best_strikes(
        self,
        contracts: list,
        entry_price: float,
        direction: str,
        atr_pct: float = 0.0075,    # 47.P2-2: ATR as fraction of price; default = 0.75% (normal)
    ):
        """
        Score and rank option contracts, selecting the best strikes.

        47.P2-2 — ATR-adjusted delta target band:
          The delta scoring window narrows or widens based on intraday ATR:

          atr_pct < 0.5%  (tight)    → target 0.40–0.45Δ  — directional, cheaper premium
          atr_pct 0.5–1.2% (normal)  → target 0.35–0.45Δ  — balanced (default)
          atr_pct > 1.2%  (volatile) → target 0.30–0.45Δ  — wider, more gamma acceptable

        Rationale:
          In tight markets price moves are small and predictable; a tighter
          delta (closer to 0.40) minimises premium overpay.
          In volatile markets wide swings benefit from slightly deeper OTM
          strikes (more gamma leverage) even at the cost of lower initial Δ.

        Score tiers:
          In ATR-derived target band            → 10 pts
          In extended catch-all band (0.30–0.70)  →  3 pts  (reduced from 5 to incentivise target)
          Outside extended band                  →  0 pts

        Returns:
            (scored_list, delta_band_label)  — backward-compatible via tuple
        """
        # Derive ATR regime and target delta band
        if atr_pct < _ATR_TIGHT_PCT:
            delta_lo, delta_hi = 0.40, 0.45
            regime_label = f"tight-ATR ({atr_pct*100:.2f}%)"
        elif atr_pct > _ATR_VOLATILE_PCT:
            delta_lo, delta_hi = 0.30, 0.45
            regime_label = f"volatile-ATR ({atr_pct*100:.2f}%)"
        else:
            delta_lo, delta_hi = 0.35, 0.45
            regime_label = f"normal-ATR ({atr_pct*100:.2f}%)"

        delta_band_label = (
            f"Δ-band [{delta_lo:.2f}–{delta_hi:.2f}] | regime={regime_label}"
        )
        logger.info(f"[SELECT-STRIKES] {delta_band_label}")

        scored = []
        for c in contracts:
            delta = abs(c.get('delta', 0))
            oi    = c.get('open_interest', 0)
            bid   = c.get('bid', 0)
            ask   = c.get('ask', 0)
            if bid <= 0 or ask <= 0:
                continue
            spread = ((ask - bid) / ((ask + bid) / 2)) * 100

            # Delta score — ATR-adjusted target band (47.P2-2)
            if delta_lo <= delta <= delta_hi:
                delta_score = 10                         # in target band
            elif 0.30 <= delta <= 0.70:
                delta_score = 3                          # extended catch-all
            else:
                delta_score = 0

            oi_score     = min(oi / 100, 10)
            spread_score = max(10 - spread, 0)

            scored.append({
                'contract':      c.get('contract'),
                'strike':        c.get('strike'),
                'exp_date':      c.get('exp_date'),
                'delta':         delta,
                'theta':         c.get('theta'),
                'bid':           bid,
                'ask':           ask,
                'mid_price':     (bid + ask) / 2,
                'spread_pct':    round(spread, 2),
                'open_interest': oi,
                'score':         round(delta_score + oi_score + spread_score, 2),
            })

        scored.sort(key=lambda x: x['score'], reverse=True)
        return scored, delta_band_label

    def _get_next_trading_day(self, start_date, offset=0):
        current = start_date + timedelta(days=offset)
        while current.weekday() >= 5:
            current += timedelta(days=1)
        return current

    def _create_skip_response(self, reason, time_remaining):
        return {'dte': None, 'expiry_date': None, 'recommended_strikes': [],
                'reasoning': f"🚫 SKIP: {reason}", 'time_remaining_hours': round(time_remaining, 2), 'confidence_pct': 0}

try:
    dte_selector = OptionsDTESelector()
except Exception:
    dte_selector = None
