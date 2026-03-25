"""
validation.py — Unified Validation Interface v1.38b
Consolidates SignalValidator + RegimeFilter + OptionsFilter.
RegimeFilter/OptionsFilter now live in their own files to keep each under
the GitHub API safe-write threshold (~30KB).
All three are re-exported here — zero breaking changes for importers.
See CHANGELOG.md for full phase history.
"""
from typing import Dict, List, Optional, Tuple
from datetime import datetime, time as dtime
from zoneinfo import ZoneInfo
import logging

# Re-export sub-modules so importers see no change
from app.validation.regime_filter import RegimeFilter, RegimeState
from app.validation.options_filter import OptionsFilter, get_options_recommendation

from app.indicators import technical_indicators as ti
from utils import config

logger = logging.getLogger(__name__)
ET = ZoneInfo("America/New_York")

# IVR gate constants (forwarded for any code that reads them from this module)
IVR_HARD_BLOCK = 80
IVR_WARN       = 60

try:
    from daily_bias_engine import bias_engine
    BIAS_ENGINE_ENABLED = True
except ImportError:
    BIAS_ENGINE_ENABLED = False
    bias_engine = None

try:
    from vpvr_calculator import vpvr_calculator
    VPVR_ENABLED = True
except ImportError:
    VPVR_ENABLED = False
    vpvr_calculator = None


def get_time_of_day_quality(signal_time: datetime) -> Tuple[str, float]:
    t = signal_time.time()
    if dtime(9, 30)  <= t < dtime(10, 30): return 'MORNING_SESSION',   0.05
    if dtime(15, 0)  <= t < dtime(16, 0):  return 'POWER_HOUR',        0.05
    if dtime(10, 30) <= t < dtime(11, 30): return 'LATE_MORNING',      0.02
    if dtime(13, 30) <= t < dtime(15, 0):  return 'EARLY_AFTERNOON',   0.02
    if dtime(11, 30) <= t < dtime(13, 0):  return 'DEAD_ZONE',        -0.03
    if dtime(13, 0)  <= t < dtime(13, 30): return 'LUNCH_RECOVERY',    0.00
    return 'OFF_HOURS', 0.0


class SignalValidator:
    """Multi-indicator signal validation engine."""

    def __init__(
        self,
        min_final_confidence: float = 0.50,
        min_adx: float = 15.0,
        min_volume_ratio: float = 1.5,
        enable_vpvr: bool = True,
        enable_daily_bias: bool = True,
        enable_time_filter: bool = True,
        enable_ema_stack: bool = True,
        enable_rsi_divergence: bool = True,
        min_bias_confidence: float = 0.65,
        strict_mode: bool = False
    ):
        self.min_final_confidence = min_final_confidence
        self.min_adx              = min_adx
        self.min_volume_ratio     = min_volume_ratio
        self.enable_vpvr          = enable_vpvr and VPVR_ENABLED
        self.enable_daily_bias    = enable_daily_bias and BIAS_ENGINE_ENABLED
        self.enable_time_filter   = enable_time_filter
        self.enable_ema_stack     = enable_ema_stack
        self.enable_rsi_divergence = enable_rsi_divergence
        self.min_bias_confidence  = min_bias_confidence
        self.strict_mode          = strict_mode

        self.validation_stats = {
            'total_validated': 0, 'passed': 0, 'filtered': 0, 'boosted': 0,
            'bias_penalized': 0, 'vpvr_rescued': 0, 'vpvr_scored': 0,
            'time_zones': {}, 'ema_stack_aligned': 0, 'rsi_divergence_detected': 0,
            'confidence_filtered': 0
        }

        logger.info(f"[VALIDATOR] SignalValidator init | min_conf={int(min_final_confidence*100)}% | adx={min_adx} | vol={min_volume_ratio}x")

    def validate_signal(
        self,
        ticker: str,
        signal_direction: str,
        current_price: float,
        current_volume: int,
        base_confidence: float
    ) -> Tuple[bool, float, Dict]:
        self.validation_stats['total_validated'] += 1
        signal_time = datetime.now(ET)
        _dir = signal_direction.upper()
        _dir = 'BUY' if _dir in ('BULL', 'BUY', 'LONG') else 'SELL'

        metadata = {
            'timestamp': signal_time.isoformat(),
            'ticker': ticker, 'direction': signal_direction,
            'base_confidence': base_confidence, 'checks': {}
        }

        conf_adj               = 0.0
        failed_checks          = []
        passed_checks          = []
        counter_trend_penalty  = 0.0
        needs_vpvr_rescue      = False

        # ── Daily Bias ────────────────────────────────────────────────────────
        if self.enable_daily_bias and bias_engine:
            try:
                should_filter, bias_reason = bias_engine.should_filter_signal(ticker, signal_direction)
                bias_data = bias_engine._get_bias_dict()
                metadata['checks']['daily_bias'] = {
                    'bias': bias_data['bias'], 'confidence': bias_data['confidence'],
                    'should_filter': should_filter, 'reason': bias_reason
                }
                if should_filter and bias_data['confidence'] >= self.min_bias_confidence:
                    counter_trend_penalty = -0.25
                    conf_adj += counter_trend_penalty
                    failed_checks.append('BIAS_COUNTER_TREND_STRONG')
                    needs_vpvr_rescue = True
                    self.validation_stats['bias_penalized'] += 1
                    logger.info(f"[VALIDATOR] {ticker} counter-trend to {bias_data['bias']} bias (-25%) — VPVR can rescue")
                elif bias_data['bias'] != 'NEUTRAL':
                    if not should_filter:
                        conf_adj += bias_data['confidence'] * 0.10
                        passed_checks.append(f"BIAS_ALIGNED_{bias_data['bias']}")
                    else:
                        passed_checks.append('BIAS_WEAK')
            except Exception as e:
                metadata['checks']['daily_bias'] = {'error': str(e)}

        # ── Regime ────────────────────────────────────────────────────────────
        regime_filter = get_regime_filter()
        try:
            rs = regime_filter.get_regime_state()
            metadata['checks']['regime_filter'] = {
                'regime': rs.regime, 'vix': rs.vix, 'spy_trend': rs.spy_trend,
                'adx': rs.adx, 'favorable': rs.favorable, 'reason': rs.reason
            }
            if not rs.favorable:
                conf_adj -= 0.30
                failed_checks.append(f'REGIME_{rs.regime}')
                logger.info(f"[VALIDATOR] {ticker} in {rs.regime} regime (-30%): {rs.reason}")
            elif rs.regime == 'TRENDING':
                conf_adj += 0.05
                passed_checks.append('REGIME_TRENDING')
            else:
                passed_checks.append('REGIME_NEUTRAL')
        except Exception as e:
            metadata['checks']['regime_filter'] = {'error': str(e)}

        # ── Time of Day ───────────────────────────────────────────────────────
        if self.enable_time_filter:
            try:
                time_zone, time_adj = get_time_of_day_quality(signal_time)
                metadata['checks']['time_of_day'] = {
                    'zone': time_zone, 'time': signal_time.strftime('%H:%M:%S'), 'adjustment': time_adj
                }
                conf_adj += time_adj
                self.validation_stats['time_zones'].setdefault(time_zone, 0)
                self.validation_stats['time_zones'][time_zone] += 1
                if   time_adj > 0: passed_checks.append(f'TIME_{time_zone}')
                elif time_adj < 0: failed_checks.append(f'TIME_{time_zone}')
                else:              passed_checks.append('TIME_NEUTRAL')
            except Exception as e:
                metadata['checks']['time_of_day'] = {'error': str(e)}

        # ── EMA Stack ─────────────────────────────────────────────────────────
        if self.enable_ema_stack:
            try:
                d9, d20, d50 = ti.fetch_ema(ticker, period=9), ti.fetch_ema(ticker, period=20), ti.fetch_ema(ticker, period=50)
                if all([d9, d20, d50]):
                    e9  = ti.get_latest_value(d9,  'ema')
                    e20 = ti.get_latest_value(d20, 'ema')
                    e50 = ti.get_latest_value(d50, 'ema')
                    if all([e9, e20, e50]):
                        if _dir == 'BUY':
                            full    = current_price > e9 > e20 > e50
                            partial = current_price > e9 and e9 > e20
                        else:
                            full    = current_price < e9 < e20 < e50
                            partial = current_price < e9 and e9 < e20
                        metadata['checks']['ema_stack'] = {
                            'ema9': round(e9, 2), 'ema20': round(e20, 2), 'ema50': round(e50, 2),
                            'full_stack': full, 'partial_stack': partial
                        }
                        if full:
                            conf_adj += 0.07; passed_checks.append('EMA_FULL_STACK')
                            self.validation_stats['ema_stack_aligned'] += 1
                        elif partial:
                            conf_adj += 0.03; passed_checks.append('EMA_PARTIAL_STACK')
                        else:
                            conf_adj -= 0.04; failed_checks.append('EMA_NO_STACK')
                    else:
                        metadata['checks']['ema_stack'] = {'error': 'Missing EMA values'}
                else:
                    metadata['checks']['ema_stack'] = {'error': 'Failed to fetch EMA data'}
            except Exception as e:
                metadata['checks']['ema_stack'] = {'error': str(e)}

        # ── RSI Divergence ────────────────────────────────────────────────────
        if self.enable_rsi_divergence:
            try:
                div_result, div_details = ti.check_rsi_divergence(ticker, signal_direction, lookback_bars=10)
                if div_result and div_details:
                    metadata['checks']['rsi_divergence'] = div_details
                    expected = ('BEARISH_DIV' if _dir == 'SELL' else 'BULLISH_DIV')
                    if div_result == expected:
                        conf_adj += 0.05; passed_checks.append('RSI_DIV_FAVORABLE')
                    else:
                        conf_adj -= 0.05; failed_checks.append('RSI_DIV_WARNING')
                    self.validation_stats['rsi_divergence_detected'] += 1
            except Exception as e:
                metadata['checks']['rsi_divergence'] = {'error': str(e)}

        # ── ADX ───────────────────────────────────────────────────────────────
        try:
            is_trending, adx_value = ti.check_trend_strength(ticker, self.min_adx)
            metadata['checks']['adx'] = {'value': adx_value, 'passed': is_trending, 'threshold': self.min_adx}
            if adx_value:
                if   adx_value >= 40:          conf_adj += 0.05; passed_checks.append('ADX_STRONG')
                elif adx_value >= self.min_adx:                   passed_checks.append('ADX_OK')
                else:                          conf_adj -= 0.05; failed_checks.append('ADX_WEAK')
        except Exception as e:
            metadata['checks']['adx'] = {'error': str(e)}

        # ── Volume ────────────────────────────────────────────────────────────
        try:
            is_confirmed, vol_ratio = ti.check_volume_confirmation(ticker, current_volume, self.min_volume_ratio)
            metadata['checks']['volume'] = {'ratio': vol_ratio, 'passed': is_confirmed, 'threshold': self.min_volume_ratio}
            if vol_ratio:
                if   vol_ratio >= 2.0:                conf_adj += 0.10; passed_checks.append('VOLUME_STRONG')
                elif vol_ratio >= self.min_volume_ratio: conf_adj += 0.03; passed_checks.append('VOLUME_OK')
                else:                                conf_adj -= 0.08; failed_checks.append('VOLUME_WEAK')
        except Exception as e:
            metadata['checks']['volume'] = {'error': str(e)}

        # ── DMI ───────────────────────────────────────────────────────────────
        try:
            trend_dir = ti.get_trend_direction(ticker)
            metadata['checks']['dmi'] = {'direction': trend_dir}
            if trend_dir:
                expected = 'BULLISH' if _dir == 'BUY' else 'BEARISH'
                if trend_dir == expected:
                    conf_adj += 0.05; passed_checks.append('DMI_ALIGNED')
                else:
                    conf_adj -= 0.10; failed_checks.append('DMI_CONFLICT')
        except Exception as e:
            metadata['checks']['dmi'] = {'error': str(e)}

        # ── CCI ───────────────────────────────────────────────────────────────
        try:
            cci_data = ti.fetch_cci(ticker)
            if cci_data:
                cci = ti.get_latest_value(cci_data, 'cci')
                metadata['checks']['cci'] = {'value': cci}
                if cci is not None:
                    if _dir == 'BUY':
                        if   cci < -100: conf_adj += 0.05; passed_checks.append('CCI_OVERSOLD')
                        elif cci >  100: conf_adj -= 0.05; failed_checks.append('CCI_OVERBOUGHT')
                    else:
                        if   cci >  100: conf_adj += 0.05; passed_checks.append('CCI_OVERBOUGHT')
                        elif cci < -100: conf_adj -= 0.05; failed_checks.append('CCI_OVERSOLD')
        except Exception as e:
            metadata['checks']['cci'] = {'error': str(e)}

        # ── Bollinger Bands ───────────────────────────────────────────────────
        try:
            is_squeezed, band_width = ti.check_bollinger_squeeze(ticker)
            metadata['checks']['bbands'] = {'band_width': band_width, 'is_squeezed': is_squeezed}
            if is_squeezed:
                conf_adj += 0.05; passed_checks.append('BB_SQUEEZE')
        except Exception as e:
            metadata['checks']['bbands'] = {'error': str(e)}

        # ── VPVR ──────────────────────────────────────────────────────────────
        vpvr_rescue_applied = False
        if self.enable_vpvr and vpvr_calculator:
            try:
                from app.data.data_manager import data_manager
                bars = data_manager.get_today_session_bars(ticker)
                if bars and len(bars) >= 78:
                    vpvr = vpvr_calculator.calculate_vpvr(bars, lookback_bars=78)
                    if vpvr and vpvr['poc'] is not None:
                        entry_score, entry_reason = vpvr_calculator.get_entry_score(current_price, vpvr)
                        metadata['checks']['vpvr'] = {
                            'poc': vpvr['poc'], 'vah': vpvr['vah'], 'val': vpvr['val'],
                            'entry_score': round(entry_score, 2), 'entry_reason': entry_reason,
                            'hvn_zones': vpvr['hvn_zones'][:2], 'lvn_zones': vpvr['lvn_zones'][:2]
                        }
                        self.validation_stats['vpvr_scored'] += 1

                        if needs_vpvr_rescue and entry_score >= 0.85:
                            rescue = abs(counter_trend_penalty)
                            conf_adj += rescue
                            passed_checks.append('VPVR_RESCUE')
                            failed_checks.remove('BIAS_COUNTER_TREND_STRONG')
                            vpvr_rescue_applied = True
                            self.validation_stats['vpvr_rescued'] += 1
                            logger.info(f"[VPVR] {ticker} RESCUED: {entry_reason} overrides bias penalty (+{rescue:.2%})")

                        if entry_score >= 0.85:
                            if not vpvr_rescue_applied:
                                conf_adj += 0.08; passed_checks.append('VPVR_STRONG')
                            logger.info(f"[VPVR] {ticker} strong entry: {entry_reason}")
                        elif entry_score >= 0.70:
                            conf_adj += 0.03; passed_checks.append('VPVR_GOOD')
                        elif entry_score < 0.50:
                            conf_adj -= 0.05; failed_checks.append('VPVR_WEAK')
                        else:
                            passed_checks.append('VPVR_NEUTRAL')

                        if vpvr_rescue_applied:
                            metadata['checks']['vpvr']['rescued'] = True
                    else:
                        metadata['checks']['vpvr'] = {'error': 'Insufficient VPVR data'}
                else:
                    metadata['checks']['vpvr'] = {'error': f'Need 78+ bars, got {len(bars) if bars else 0}'}
            except Exception as e:
                metadata['checks']['vpvr'] = {'error': str(e)}

        # ── Final decision ────────────────────────────────────────────────────
        adjusted = max(0.0, min(1.0, base_confidence + conf_adj))

        if adjusted < self.min_final_confidence:
            should_pass = False
            self.validation_stats['confidence_filtered'] += 1
            logger.info(f"[VALIDATOR] {ticker} FILTERED: {adjusted*100:.1f}% < {self.min_final_confidence*100:.1f}%")
        elif self.strict_mode:
            critical = ['VOLUME_WEAK', 'DMI_CONFLICT', 'ADX_WEAK']
            should_pass = not any(f in failed_checks for f in critical)
        else:
            should_pass = len(passed_checks) > 0 and len(passed_checks) >= len(failed_checks)

        if should_pass:
            self.validation_stats['passed'] += 1
            if conf_adj > 0:
                self.validation_stats['boosted'] += 1
        else:
            self.validation_stats['filtered'] += 1

        metadata['summary'] = {
            'should_pass':           should_pass,
            'adjusted_confidence':   round(adjusted, 3),
            'confidence_adjustment': round(conf_adj, 3),
            'passed_checks':         passed_checks,
            'failed_checks':         failed_checks,
            'check_score':           f"{len(passed_checks)}/{len(passed_checks)+len(failed_checks)}",
            'vpvr_rescued':          vpvr_rescue_applied,
            'min_confidence_met':    adjusted >= self.min_final_confidence
        }
        return should_pass, adjusted, metadata

    def print_validation_summary(self, ticker: str, metadata: Dict) -> None:
        summary = metadata.get('summary', {})
        checks  = metadata.get('checks', {})
        result  = "OK PASS" if summary.get('should_pass') else "FAIL"
        conf    = summary.get('adjusted_confidence', 0)
        quality = "STRONG" if conf >= 0.80 else ("GOOD" if conf >= 0.65 else ("FAIR" if conf >= 0.50 else "WEAK"))
        base    = metadata.get('base_confidence', 0)
        adj     = summary.get('confidence_adjustment', 0)
        logger.info(f"[VALIDATOR] {result} {ticker} | {quality} | {base*100:.1f}%→{conf*100:.1f}% ({adj*100:+.1f}%) | {summary.get('check_score')}")
        passed  = summary.get('passed_checks', [])
        failed  = summary.get('failed_checks', [])
        if passed: logger.info(f"[VALIDATOR]   Passed: {', '.join(passed[:5])}")
        if failed: logger.info(f"[VALIDATOR]   Failed: {', '.join(failed)}")
        if summary.get('vpvr_rescued'):
            logger.info("[VALIDATOR]   VPVR RESCUE: Counter-trend signal saved!")

    def get_validation_stats(self) -> Dict:
        total = self.validation_stats['total_validated']
        if total == 0:
            return self.validation_stats
        return {
            **self.validation_stats,
            'pass_rate':               round(self.validation_stats['passed']    / total, 3),
            'filter_rate':             round(self.validation_stats['filtered']  / total, 3),
            'boost_rate':              round(self.validation_stats['boosted']   / total, 3),
            'bias_penalty_rate':       round(self.validation_stats['bias_penalized'] / total, 3),
            'vpvr_rescue_rate':        round(self.validation_stats['vpvr_rescued']   / total, 3),
            'ema_stack_rate':          round(self.validation_stats['ema_stack_aligned']       / total, 3),
            'rsi_div_rate':            round(self.validation_stats['rsi_divergence_detected'] / total, 3),
            'vpvr_scored_rate':        round(self.validation_stats['vpvr_scored']             / total, 3),
            'confidence_filter_rate':  round(self.validation_stats['confidence_filtered']     / total, 3),
        }

    def reset_stats(self):
        self.validation_stats = {
            'total_validated': 0, 'passed': 0, 'filtered': 0, 'boosted': 0,
            'bias_penalized': 0, 'vpvr_rescued': 0, 'vpvr_scored': 0,
            'time_zones': {}, 'ema_stack_aligned': 0, 'rsi_divergence_detected': 0,
            'confidence_filtered': 0
        }


# ── Global instances ──────────────────────────────────────────────────────────
_validator_instance:      Optional[SignalValidator] = None
_regime_filter_instance:  Optional[RegimeFilter]   = None
_options_filter_instance: Optional[OptionsFilter]  = None


def get_validator() -> SignalValidator:
    global _validator_instance
    if _validator_instance is None:
        _validator_instance = SignalValidator()
    return _validator_instance


def get_regime_filter() -> RegimeFilter:
    global _regime_filter_instance
    if _regime_filter_instance is None:
        _regime_filter_instance = RegimeFilter()
    return _regime_filter_instance


def get_options_filter() -> OptionsFilter:
    global _options_filter_instance
    if _options_filter_instance is None:
        _options_filter_instance = OptionsFilter()
    return _options_filter_instance


__all__ = [
    'SignalValidator', 'RegimeFilter', 'RegimeState', 'OptionsFilter',
    'get_validator', 'get_regime_filter', 'get_options_filter',
    'get_time_of_day_quality', 'get_options_recommendation',
    'IVR_HARD_BLOCK', 'IVR_WARN',
]
