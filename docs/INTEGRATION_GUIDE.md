# War Machine — Integration Guide

> **Purpose:** Single reference for all wiring points, module connections, and integration patterns in the live system.  
> **Scope:** Analytics, health check, risk sizing, RTH filtering, regime filter, correlation check, Phase 4 monitoring.  
> **Status:** All integrations below are LIVE unless marked ⏳ PENDING.

---

## Table of Contents
1. [Analytics Integration](#1-analytics-integration)
2. [Health Check](#2-health-check)
3. [VIX Sizing](#3-vix-sizing)
4. [RTH Filter](#4-rth-filter)
5. [Regime Filter & Correlation Check](#5-regime-filter--correlation-check)
6. [Phase 4 — Signal Lifecycle Tracking](#6-phase-4--signal-lifecycle-tracking)
7. [EOD Reporting](#7-eod-reporting)
8. [Emergency Disable Patterns](#8-emergency-disable-patterns)

---

## 1. Analytics Integration

**Module:** `app/core/analytics_integration.py`  
**Status:** ✅ LIVE

All analytics calls route through `AnalyticsIntegration` — scanner.py never imports analytics internals directly.

```python
# scanner.py initialization
from app.core.analytics_integration import AnalyticsIntegration
analytics = AnalyticsIntegration(db_connection)

# In scan loop
signal_id = analytics.process_signal(signal_data, regime=regime, vix_level=vix)
analytics.monitor_active_signals(price_fetcher=get_current_price)
analytics.check_scheduled_tasks()
```

**Rate limiting note:** `monitor_active_signals()` must be rate-limited inside `analytics_integration.py` — do NOT call on every scan tick.

---

## 2. Health Check

**Module:** `app/core/health_server.py`  
**Status:** ✅ LIVE — this is the authoritative health server  
**Endpoint:** `GET /health` → HTTP 200 when scanner loop alive  
**Railway config:** `railway.toml` → `healthcheckPath = "/health"`

> ⚠️ `app/health_check.py` also exists — verify which is started at runtime in `scanner.py`. Only one should be active. `health_server.py` is the canonical version.

```python
# scanner.py startup
from app.core.health_server import start_health_server
start_health_server(port=8080)  # Runs as daemon thread
```

**Healthcheck behavior:**
- Returns 200 as long as the scanner's main thread is alive
- Railway restarts container if `/health` fails 3 consecutive checks
- Health server failure does NOT kill the scanner — it runs independently

---

## 3. VIX Sizing

**Module:** `app/risk/vix_sizing.py`  
**Status:** ✅ LIVE  
**Called by:** `app/risk/trade_calculator.py`

VIX-driven position size scaling — applied automatically before every trade:

| VIX Level | Size Multiplier | Effect |
|-----------|----------------|--------|
| < 15 | 1.0x (full size) | Normal market |
| 15–20 | 0.85x | Slightly elevated vol |
| 20–25 | 0.70x | Elevated vol — reduce exposure |
| 25–30 | 0.55x | High vol — significantly reduced |
| > 30 | 0.40x | Extreme vol — minimum size |

```python
# trade_calculator.py
from app.risk.vix_sizing import VixSizer
vix_sizer = VixSizer()
adjusted_contracts = vix_sizer.scale_position(base_contracts, current_vix)
```

**Config:** VIX thresholds and multipliers are defined in `vix_sizing.py` constants — adjust there, not in `trade_calculator.py`.

---

## 4. RTH Filter

**Module:** `app/analytics/rth_filter.py`  
**Status:** ✅ LIVE  
**Called by:** `app/analytics/performance_monitor.py`, `app/core/scanner_optimizer.py`

Tracks performance by RTH sub-session to identify high/low quality trading windows:

| Window | Time (ET) | Notes |
|--------|-----------|-------|
| Pre-market | 4:00–9:30 AM | Watchlist build only, no live signals |
| Open | 9:30–9:45 AM | ORB window — `should_scan_now()` blocks signals |
| Power Hour 1 | 9:45–11:30 AM | Highest signal quality historically |
| Midday | 11:30 AM–1:30 PM | Reduced quality — tighter confidence gates |
| Power Hour 2 | 1:30–3:30 PM | Second-best window |
| Close | 3:30–4:00 PM | No new entries — `entry_timing.py` blocks |

```python
# scanner_optimizer.py uses RTH data
from app.analytics.rth_filter import RTHFilter
rth = RTHFilter()
current_session = rth.get_current_session()
quality_multiplier = rth.get_quality_multiplier(current_session)
```

---

## 5. Regime Filter & Correlation Check

**Modules:** regime logic in `app/core/sniper.py` + `app/filters/correlation.py`  
**Status:** ✅ LIVE

### Regime Filter — `process_ticker()` in `sniper.py`

Blocks trading in unfavorable market regimes (checked before every ticker):

```python
# sniper.py — already wired, reference only
if REGIME_FILTER_ENABLED and regime_filter:
    if not regime_filter.is_favorable_regime():
        state = regime_filter.get_regime_state()
        print(f"[{ticker}] REGIME FILTER: {state.regime} (VIX: {state.vix:.1f}) - {state.reason}")
        return
```

**Regime states:** `NORMAL` | `ELEVATED_VOL` | `VOLATILE` | `EXTREME`  
**Cache TTL:** 5 minutes — one VIX/SPY check per 5-min window, negligible overhead

### Correlation Check — `arm_ticker()` in `sniper.py`

Prevents more than 3 highly correlated positions simultaneously:

```python
# sniper.py — already wired, reference only
if CORRELATION_CHECK_ENABLED and correlation_checker:
    safe, warning = correlation_checker.is_safe_to_add_position(
        ticker=ticker, open_positions=open_positions
    )
    if not safe:
        print(f"[ARM] CORRELATION FILTER: {ticker} - {warning.reason}")
        return
```

**Config (in `config.py`):**
```python
MAX_SECTOR_EXPOSURE_PCT = 40.0   # Max % of positions in one sector
MAX_OPEN_POSITIONS = 5           # Hard cap on concurrent positions
```

---

## 6. Phase 4 — Signal Lifecycle Tracking

**Module:** `app/signals/signal_analytics.py` → `SignalTracker`  
**Status:** ✅ LIVE — all 5 lifecycle stages wired

### Signal Lifecycle

```
GENERATED → VALIDATED → ARMED → TRADED → CLOSED
```

### Integration Points (all wired as of 2026-03-16)

**Stage 1 — After pattern detection in `sniper.py`:**
```python
event_id = signal_tracker.record_signal_generated(
    ticker=ticker, signal_type="CFW6_OR",  # or "CFW6_INTRADAY"
    direction="bull",  # or "bear"
    grade=grade,       # "A+", "A", or "A-"
    confidence=base_confidence,
    entry_price=entry_price, stop_price=stop_loss, t1_price=t1, t2_price=t2
)
```

**Stage 2 — After validation:**
```python
event_id = signal_tracker.record_validation_result(
    ticker=ticker, passed=True,
    confidence_after=final_confidence,
    ivr_multiplier=ivr_mult, uoa_multiplier=uoa_mult,
    gex_multiplier=gex_mult, mtf_boost=mtf_boost,
    checks_passed=["ADX", "VOLUME", "DMI", "VPVR"],
    rejection_reason=""  # populated if passed=False
)
```

**Stage 3 — After confirmation (`wait_for_confirmation()` returns True):**
```python
event_id = signal_tracker.record_signal_armed(
    ticker=ticker, final_confidence=final_confidence,
    bars_to_confirmation=bars_waited,
    confirmation_type="retest"  # or "rejection"
)
```

**Stage 4 — After `position_manager.open_position()` succeeds (`arm_signal.py`):**
```python
# Wired in app/core/arm_signal.py as of 2026-03-16 Session 4
if PHASE_4_ENABLED and signal_tracker:
    signal_tracker.record_trade_executed(ticker, position_id)
```

### Performance Monitor — Circuit Breaker

```python
# Check BEFORE opening any position
cb_status = performance_monitor.get_circuit_breaker_status()
if cb_status['triggered']:
    print("[RISK] Circuit breaker triggered - No new positions")
    continue
```

---

## 7. EOD Reporting

**Module:** `app/core/eod_reporter.py`  
**Status:** ✅ LIVE  
**Fires:** Market close block in `scanner.py`

**What fires at EOD:**
1. `signal_tracker.get_discord_eod_summary()` → Discord
2. `performance_monitor.get_daily_performance_report()` → Railway logs + Discord
3. MTF stats report
4. Gate distribution + hourly gate stats
5. Regime summary
6. Cooldown / explosive / grade-gate tracker reports

**Pending (Batch D):** Wire `get_hourly_funnel()` into EOD output, confirm `get_discord_eod_summary()` is sending to Discord channel.

---

## 8. Emergency Disable Patterns

All major subsystems support emergency disable without a code deploy — just edit the file directly on Railway or push a one-line change:

```python
# Regime Filter
def is_favorable_regime(self, force_refresh: bool = False) -> bool:
    return True  # EMERGENCY DISABLE

# Correlation Check
def is_safe_to_add_position(self, ticker, open_positions, proposed_risk_dollars=None):
    return (True, None)  # EMERGENCY DISABLE

# Circuit Breaker
def get_circuit_breaker_status(self) -> dict:
    return {'triggered': False, 'reason': 'disabled'}  # EMERGENCY DISABLE

# Signal Tracker (skip funnel recording)
PHASE_4_ENABLED = False  # In sniper.py environment check
```

---

*Last updated: 2026-03-16 | Batch E consolidation | Replaces: INTEGRATION_INSTRUCTIONS.md, PHASE_4_INTEGRATION_GUIDE.md, HEALTH_CHECK_INTEGRATION.md, VIX_SIZING_INTEGRATION.md, RTH_FILTER_INTEGRATION.md, ANALYTICS_SYSTEM_README.md, SIGNAL_ANALYTICS_README.md*
