
***

## File 2: Updated `docs/signal_logic_audit_index.md`

Replace the existing file with this — the only change is adding the Batch 9 row to the table and the 9.C-1 through 9.C-5 entries to the Outstanding Criticals section:

```markdown
# War Machine Signal Logic Audit — Index

This document is the master index for the ongoing end-to-end audit of War Machine's signal logic and execution pipeline.
Each batch is maintained in its own file under `docs/`.

## Scope

- Repository: AlgoOps25/War-Machine
- Focus: Data → Screening → Signals → Risk/Execution → Surrounding services
- Goal: Mathematically clear, invariant-based signal logic with no edge-case failure modes.

## Working Methodology

- Audit is performed in batches, aligned to the live signal pipeline rather than directory layout.
- For each batch we:
  - Document current behaviour and assumptions.
  - Define explicit invariants (what must always be true for correctness).
  - Identify issues, ambiguities, and edge cases.
  - Propose concrete code changes and new/updated tests.
  - Record decisions and rationale here.

## Batch Status

| Batch | File | Scope | Status | Findings |
|-------|------|-------|--------|----------|
| 1 | [batch1](signal_logic_audit_batch1.md) | Data ingestion, screening, position manager | ✅ Complete | Calendar, WS/REST, volume signals, watchlist funnel |
| 2 | [batch2](signal_logic_audit_batch2.md) | Signal engine (breakout, OR, analytics) | ✅ Complete | 11 findings |
| 3 | [batch3](signal_logic_audit_batch3.md) | Core pipeline orchestration (sniper, arm_signal) | ✅ Complete | 18 findings |
| 4 | [batch4](signal_logic_audit_batch4.md) | Validation layer (confirmation, entry timing, hourly gate, volume profile) | ✅ Complete | 17 findings |
| 5 | [batch5](signal_logic_audit_batch5.md) | Filters layer (VWAP, MTF, OB, liquidity sweep, correlation) | ✅ Complete | 19 findings |
| 6 | [batch6](signal_logic_audit_batch6.md) | Indicators layer (technical, volume, VWAP calculator) | ✅ Complete | 17 findings |
| 7 | [batch7](signal_logic_audit_batch7.md) | Options layer (options_intelligence, gex_engine, __init__) | ✅ Complete | 19 findings |
| 8 | [batch8](signal_logic_audit_batch8.md) | Validation layer deep-dive (SignalValidator, RegimeFilter, OptionsFilter) | ✅ Complete | 22 findings |
| 9 | [batch9](signal_logic_audit_batch9.md) | Core orchestration (scanner, thread_safe_state, armed_signal_store, watch_signal_store) | ✅ Complete | 23 findings |
| 10 | batch10 | Risk layer (position_manager, risk_manager, trade_calculator) | ✅ Complete | 20 findings |
| 11 | batch11 | Risk layer — VIX sizing, dynamic thresholds | ✅ Complete | 18 findings |
| 12 | batch12 | Analytics layer (cooldown_tracker, performance_monitor, grade_gate_tracker) | ✅ Complete | 17 findings |
| 13 | batch13 | Analytics layer (funnel_analytics, explosive_mover_tracker, ab_test_framework) | ✅ Complete | 16 findings |
| 14 | batch14 | Data layer (db_connection, candle_cache) | ✅ Complete | 16 findings |
| 15 | batch15 | Data layer (data_manager) | ✅ Complete | 18 findings |
| 16 | batch16 | Real-time feeds (ws_feed, ws_quote_feed, unusual_options) | ✅ Complete | 20 findings |
| 17 | batch17 | Signal detectors (breakout_detector, opening_range) | ✅ Complete | 21 findings |
| 18 | batch18 | Signal analytics / lifecycle tracker | ✅ Complete | 17 findings |
| 19 | batch19 | sniper.py — core signal pipeline | ✅ Complete | 26 findings (2C / 8H / 10M / 6L) |
| 20 | batch20 | scanner.py — main scan loop | ✅ Complete | 21 findings (1C / 5H / 9M / 6L) |
| 21 | batch21 | thread_safe_state.py + arm_signal.py + armed_signal_store.py + watch_signal_store.py | ✅ Complete | 19 findings (1C / 4H / 8M / 6L) |
| 22 | batch22 | analytics_integration.py + eod_reporter.py + health_server.py | ✅ Complete | 16 findings (0C / 4H / 7M / 5L) |
| 23 | batch23 | ai_learning.py | ✅ Complete | 18 findings (1C / 4H / 8M / 5L) |
| 24 | batch24 | cooldown_tracker.py + funnel_analytics.py + performance_monitor.py | ✅ Complete | 19 findings (0C / 5H / 8M / 6L) |
| 25 | batch25 | grade_gate_tracker.py + explosive_mover_tracker.py + ab_test_framework.py | ✅ Complete | 21 findings (1C / 5H / 9M / 6L) |
| 26 | batch26 | db_connection.py + sql_safe.py | ✅ Complete | 18 findings (0C / 4H / 8M / 6L) |
| 27 | batch27 | candle_cache.py + database.py + unusual_options.py | ✅ Complete | 20 findings (0C / 4H / 8M / 8L) |
| 28 | batch28 | ws_feed.py + ws_quote_feed.py | ✅ Complete | 16 findings (0C / 3H / 7M / 6L) |
| 29 | batch29 | data_manager.py | ✅ Complete | 22 findings (0C / 5H / 10M / 7L) |
| 30 | batch30 | cooldown_tracker.py + explosive_mover_tracker.py | ✅ Complete | 19 findings (0C / 4H / 8M / 7L) |
| 31 | batch31 | funnel_analytics.py + performance_monitor.py + grade_gate_tracker.py + stubs | ✅ Complete | 23 findings (0C / 4H / 10M / 9L) |
| 32 | batch32 | ab_test_framework.py + funnel_tracker.py | ✅ Complete | 18 findings (0C / 4H / 8M / 6L) |
| 33 | batch33 | breakout_detector.py | ✅ Complete | 20 findings (0C / 5H / 9M / 6L) |
| 34 | batch34 | opening_range.py | ✅ Complete | 22 findings (0C / 5H / 10M / 7L) |
| 35 | batch35 | signal_analytics.py | ✅ Complete | 17 findings (0C / 3H / 8M / 6L) |
| 36 | batch36 | arm_signal.py + armed_signal_store.py | ✅ Complete | 19 findings (0C / 4H / 9M / 6L) |
| 37 | batch37 | analytics_integration.py + eod_reporter.py + watch_signal_store.py + health_server.py | ✅ Complete | 20 findings (0C / 3H / 9M / 8L) |
| 38 | batch38 | thread_safe_state.py + scanner.py | ✅ Complete | 24 findings (0C / 5H / 11M / 8L) |
| 39 | batch39 | sniper.py (CFW6 engine) | ✅ Complete | 28 findings (1C / 6H / 13M / 8L) |

## Outstanding Criticals — Cross-Batch Summary


| Priority | ID | Batch | Module | Issue |
|----------|----|-------|--------|-------|
| 🔴 | 3.A-1 | 3 | sniper.py | `adjust_signal_for_or()` CONFIRMED MISSING from pipeline |
| 🔴 | 3.A-2 | 3 | sniper.py | Analytics cooldown `return False` should be print-only |
| 🔴 | 3.C-15 | 3 | arm_signal.py | `screener_integration` deferred import has no fallback |
| 🔴 | 4.A-2 | 4 | cfw6_confirmation | `wait_for_confirmation()` only tests latest bar |
| 🔴 | 4.C-10 | 4 | entry_timing | `HOURLY_WIN_RATES` is hardcoded fabricated data |
| 🔴 | 5.G-18 | 5 | liquidity_sweep | Bull sweep close_reclaim allows close below level |
| 🔴 | 6.B-9 | 6 | technical_indicators_extended | `check_volatility_expansion()` newest/oldest bar inversion |
| 🔴 | 6.B-7 | 6 | technical_indicators_extended | Daily ATR vs intraday move mismatch |
| 🔴 | 7.C-1 | 7 | options_intelligence | `get_chain()` always returns None — options layer is dark |
| 🔴 | 7.C-2 | 7 | gex_engine | GEX gamma_flip fallback selects wrong strike |
| 🔴 | 7.C-3 | 7 | options_intelligence | UOA score uses circular self-referential averages — fires on every contract |
| 🔴 | 8.C-1 | 8 | validation.py | Direction mismatch: `'BUY'/'SELL'` vs `'bull'/'bear'` — -14% penalty on every bull signal |
| 🔴 | 8.C-2 | 8 | validation.py | VPVR rescue doesn't fully restore bias penalty — net -5% leak |
| 🔴 | 8.C-3 | 8 | validation.py | `_classify_regime()` returns favorable=True for VIX 25–29 TRENDING |
| 🔴 | 8.C-4 | 8 | validation.py | `filter_by_dte()` uses `datetime.now()` (UTC) instead of ET — 0-DTE permanently invisible |
| 🔴 | 9.C-1 | 9 | scanner.py | Single-worker watchdog executor — OR window scan loop serializes all tickers |
| 🔴 | 9.C-2 | 9 | scanner.py | Circuit breaker operator precedence bug — scanner may halt incorrectly |
| 🔴 | 9.C-3 | 9 | scanner.py | Health server starts at module import before env validation |
| 🔴 | 9.C-4 | 9 | scanner.py | `analytics_conn` shared across threads without lock — connection corruption |
| 🔴 | 9.C-5 | 9 | armed_signal_store.py | TOCTOU race in `_maybe_load_armed_signals()` — signals missed on restart |
| 🔴 | 10.C-1 | 10 | position_manager.py | datetime.now() UTC — circuit breaker clears after midnight UTC (8 PM ET) |
| 🔴 | 10.C-2 | 10 | position_manager.py | Dual timestamps for exit_time — positions vs ml_signals drift on DST |
| 🔴 | 10.C-4 | 10 | trade_calculator.py | Stop above entry possible on bull A+ high-vol tight-OR — silent rejection |
| 🔴 | 11.C-2 | 11 | dynamic_thresholds.py | trades table doesn't exist — win-rate threshold adjustment has never fired |
| 🔴 | 11.C-3 | 11 | dynamic_thresholds.py | proposed_trades table doesn't exist — quality adjustment has never fired |
| 🔴 | 12.C-2 | 12 | cooldown_tracker.py | tz-aware vs naive timestamp — expired cooldowns never cleaned on Railway/Postgres |
| 🔴 | 13.C-1 | 13 | explosive_mover_tracker.py | conn.close() instead of return_conn() — pool exhaustion over session |
| 🔴 | 13.C-2 | 13 | ab_test_framework.py | get_conn(db_path) raises TypeError at import — crashes Railway startup |
| 🔴 | 14.H-7 | 14 | candle_cache.py | Stripped TZ on cache rows → naive UTC vs ET boundary → _filter_session_bars() returns zero bars on Railway |
| 🔴 | 14.H-6 | 14 | candle_cache.py | is_cache_fresh() stamps ET on UTC timestamp → stale cache appears fresh |
| 🔴 | 14.C-1 | 14 | db_connection.py | Pool init at import — transient Postgres unavailability during Railway deploy crashes process |
| 🔴 | 15.C-1 | 15 | data_manager.py | Destructive migration fires on transient DB error mid-session — wipes all bars |
| 🔴 | 15.C-2 | 15 | data_manager.py | Inverted tz logic in startup_backfill_with_cache() → TypeError → full API backfill every startup, cache never used |
| 🔴 | 16.C-1 | 16 | ws_feed.py | Gate 3 dead code — multi-condition ticks with unknown leading code bypass INVALID_TRADE_CONDITIONS filter |
| 🔴 | 16.H-7 | 16 | unusual_options.py | Cache key is ticker not (ticker, direction) — all PUT whale alerts return CALL data |
| 🔴 | 17.C-1 | 17 | breakout_detector.py | session_anchored flag can mislabel entries using rolling resistance; Discord reason string is wrong |
_This index is updated as each batch is completed._
