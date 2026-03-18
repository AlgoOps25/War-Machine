# War Machine Signal Logic Audit

This document is maintained by the assistant to track the ongoing end-to-end audit of War Machine's signal logic and execution pipeline.

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

## Batches

### Batch 1: Core signal path (in progress)

**Modules**
- app/data/data_manager.py
- app/data/ws_feed.py
- app/screening/market_calendar.py
- app/screening/dynamic_screener.py
- app/screening/premarket_scanner.py
- app/screening/volume_analyzer.py
- app/screening/watchlist_funnel.py
- app/risk/position_manager.py

**Objectives**
- Ensure every live signal is based on:
  - Correct and complete bar data (1m + 5m, WS-first with safe REST fallback).
  - A well-defined, time-aware universe and scoring model.
  - A watchlist funnel whose stage transitions and thresholds are consistent with the stated timeline and intent.
  - Execution and risk rules that strictly enforce RTH guard, R:R thresholds, circuit-breaker and max-drawdown limits, and T1/T2 invariants.
- Eliminate race conditions and stale-cache edge cases between WS, REST, screener, and position manager.

**Status**
- Plan agreed with maintainer (Michael) on 2026-03-18.
- Initial code read for all Batch 1 modules completed on 2026-03-18 (ET).
- Batch 1.A, 1.B, and 1.C invariants captured. Batch 1 is **COMPLETE**.
- Next: Batch 2 (signal engine: scanner.py, signal generators, options recommender).

---

### Batch 1.A: Calendar, sessions, and data ingestion

**Modules**
- app/screening/market_calendar.py
- app/data/data_manager.py
- app/data/ws_feed.py

**Current behaviour (summary)**
- `market_calendar` defines US market holidays for 2026–2027 and exposes `is_market_day()`, `is_premarket_window()`, `is_market_hours()`, and `is_active_session()` with a 4:00–16:00 ET active window.
- `data_manager` treats PostgreSQL/SQLite as the single source of truth for 1m bars, materializes 5m bars from 1m, and is explicitly WS-first during market hours (skipping REST intraday fetches when WS is connected).
- `ws_feed` maintains in-memory open bars and pending closed bars, flushes both to the DB on a fixed interval, and provides a REST failover path via `get_current_bar_with_fallback()` when the WebSocket is down.

**Key invariants to enforce**
- No scanning should occur on weekends or defined US holidays; Batch 1 confirms `build_watchlist()` already short-circuits via `is_active_session()`.
- During market hours with WS connected, no REST intraday API calls should be made for the same symbols; `update_ticker()` and `bulk_fetch_live_snapshots()` both honor WS-first semantics.
- `get_today_session_bars()` must only ever return bars for *today's* ET date and must never silently fall back to a prior date.
- Every bar flushed from `ws_feed` must be persisted exactly once to `intraday_bars`, and 5m bars must be idempotently materialized from the 1m store.
- REST failover must be bounded by a per-ticker TTL and must not be used while `_connected=True`.

**Findings / notes**
- `market_calendar.is_active_session()` correctly prevents scanning on weekends and enumerated holidays, but holiday sets are currently hard-coded for 2026–2027 only; future years will require updates.
- `data_manager.update_ticker()` correctly skips intraday REST fetches during RTH when `ENABLE_WEBSOCKET_FEED` is on and `ws_feed.is_connected()` is True.
- `get_today_session_bars()` and `get_today_5m_bars()` have explicit date boundaries (04:00–20:00 ET) and never fall back to prior days, which matches the stated design.
- `ws_feed` uses a single `_flush_loop` that calls both `_flush_pending()` (closed bars) and `_flush_open()` (open bars), with open-bar upserts always `quiet=True` to avoid log spam.
- REST failover in `ws_feed.get_current_bar_with_fallback()` is protected by a 15-second per-ticker cache and only triggers when `_connected` is False, which prevents API hammering during short WS outages.

**Status: CLOSED — no outstanding issues.**

---

### Batch 1.B: Screener, pre-market scanner, and volume signals

**Modules**
- app/screening/dynamic_screener.py
- app/screening/premarket_scanner.py
- app/screening/gap_analyzer.py
- app/screening/news_catalyst.py
- app/screening/volume_analyzer.py

**Current behaviour (summary)**
- `dynamic_screener` (v3.1) builds an EOD-based universe via three passes (liquid, momentum, downside, breakout), applies ETF exclusion, dollar-volume and "in-play" gates, RVOL tiering (A/B/C), conflict and stale penalties, and returns a scored list used by `WatchlistFunnel`.
- `premarket_scanner` runs a 3-tier professional scan per ticker: Tier 1 (volume quality) computes RVOL vs ADV with a time-of-day adjustment and cumulative intraday volume; Tier 2 adds gap quality from `gap_analyzer` plus earnings/news flags from `news_catalyst`; Tier 3 adds catalyst score and a sector-rotation bonus when v2 modules are available.
- `gap_analyzer` classifies gaps by size (SMALL–EXTREME), type (earnings/news/technical/overnight), ATR-normalizes them, estimates fill probability, and converts that into a 0–100 quality score used directly in composite scoring.
- `news_catalyst` scans recent (≤48h) ticker-specific EODHD news, matches event-specific keyword sets for earnings/analyst/FDA/M&A, computes a weighted catalyst object, and optionally posts a Discord embed without blocking the scan.
- `volume_analyzer` tracks per-ticker rolling volume/price state to detect bottom/peak volume and volume–price divergence patterns.

**Key invariants to enforce**
- ETFs (except SPY/QQQ) must never leak into the scored universe; Tier D (sub-1.0 RVOL) is hard-dropped.
- Pre-market RVOL uses cumulative intraday volume; REST bars are clamped (10×) to prevent prior-day artifacts.
- `fetch_fundamental_data()` failure → `scan_ticker()` returns `None`, never a ghost score.
- `price <= 0` after bar resolution → hard-stop for that ticker (return `None`).
- `detect_catalyst()` called at most once per scan; Discord failures never affect scoring.
- Composite = 0.60·volume + 0.25·gap + 0.15·catalyst + sector_bonus (strictly additive; no alternate weight path).

**Findings / notes**
- All ghost-score paths (ADV==0, price==0, REST RVOL inflated) closed by Phase 1.23–1.29.
- Gap analysis correctly uses REST `open` + `previousClose`; 0.0% gap bug resolved.
- Catalyst detection: strict keyword set, 48h window, per-ticker cache, Discord non-blocking.
- Volume cumulative denominator aligned across `volume_analyzer` and `premarket_scanner`.

**Status: CLOSED — no outstanding issues.**

---

### Batch 1.C: Watchlist funnel and position manager

**Modules**
- app/screening/watchlist_funnel.py
- app/risk/position_manager.py

**Current behaviour (summary)**
- `watchlist_funnel` (v3.8) orchestrates 4 timed stages (wide 8:00–9:15, narrow 9:15–9:25, final 9:25–9:30, live 9:30+). At 9:30 the watchlist is locked for the session. Stage thresholds are: wide min_score=30, narrow min_score=50 (with catalyst bypass for wide+narrow), final min_score=50 with volume filter ≥5k, live min_score=40 (max 12 tickers). Catalyst bypass injects tickers with catalyst_score>0 past the min_score gate at wide and narrow stages.
- Relative-outlier boost (+20 to composite_score) fires for tickers moving opposite their sector group; requires ≥2 tickers in the same sector and abs(group_avg_gap)≥0.1%.
- WS coverage filter (v3.8) drops zero-session-bar tickers at lock time; falls back to full list only if every ticker fails the check.
- `position_manager` enforces: RTH guard (no new positions outside 9:30–16:00 ET), circuit breaker (daily loss ≤ -MAX_DAILY_LOSS_PCT%), max-drawdown from intraday high-water mark, max open positions, per-sector concentration cap, and duplicate-ticker guard. T1 scale-out closes half the position, moves stop to breakeven; T2 close fires only after t1_hit confirmed live from DB (FIX #9).
- Sizing uses a multiplicative stack: base_risk_pct (grade/confidence tier) × performance_multiplier (0.5–1.25, streak-based) × vix_multiplier (0.3–1.3). EOD close resets the streak to neutral.

**Key invariants**
- **Funnel lock is unconditional**: once live stage is entered and watchlist built, `build_watchlist()` returns the frozen list without re-scoring until next session.
- **Catalyst bypass must be idempotent**: a ticker already in scored_tickers must never be added a second time by bypass logic; deduplication via `passed_tickers` set enforces this.
- **Relative-outlier boost is additive only**: no ticker is removed or repositioned by this logic; only composite_score is incremented.
- **RTH guard precedes all other risk checks**: `can_open_position()` returns False immediately if `_is_rth_now()` is False, before any DB reads.
- **T1 and T2 are mutually exclusive per position**: after `_scale_out()` sets t1_hit=True in DB, `_get_t1_hit_from_db()` is re-read immediately before the T2 check, preventing double-fire on a gap-through bar (FIX #9).
- **Circuit breaker uses session-cumulative P&L**: `close_position()` busts the stats cache before calling `check_circuit_breaker()` so the breaker evaluates the true running total, not just the last trade (FIX #8).
- **Streak reset is EOD-only**: `close_all_eod()` resets consecutive_wins/losses and performance_multiplier to 1.0; individual trade closes only increment/decrement the streak.
- **Stale positions are purged at startup**: `_close_stale_positions()` force-closes any OPEN positions from prior days before session state is loaded, preventing phantom sizing from carry-overs.
- **R:R validation uses T2 (not T1) as the reward target**: `validate_risk_reward(entry, stop, t2)` is called before `_check_risk_limits()`, so the minimum R:R is evaluated against the full trade target.

**Findings / notes**

1. **ISSUE — `_build_narrow_scan()` double-applies catalyst bypass (minor)**
   The narrow-stage path when `self.current_watchlist` is non-empty manually re-filters to `composite_score >= min_score OR catalyst_bypass=True`, then passes the result to `_apply_catalyst_bypass()` again with `all_scored`. Tickers already marked `catalyst_bypass=True` in the inline filter are safe due to the `passed_tickers` dedup set inside `_apply_catalyst_bypass()`, but the intent is obscured. **Recommendation**: remove the inline `or t.get('catalyst_bypass')` check and rely solely on `_apply_catalyst_bypass()` for bypass logic.

2. **ISSUE — `_build_live_watchlist()` volume signals are additive without bound (low severity)**
   In `_build_live_watchlist()`, every bullish volume signal unconditionally adds +5 to `composite_score`. Unlike the narrow-stage adjustment (±10 with symmetric bearish), the live path only has the bullish +5 with no corresponding bearish subtraction. This means live-stage scores can be inflated by repeated volume signal matches for the same ticker if `get_active_signals()` returns multiple signals. **Recommendation**: cap the live volume-signal adjustment at +5/-5 per ticker (deduplicate by ticker before summing).

3. **ISSUE — `_build_final_selection()` has no catalyst bypass (informational)**
   The final stage (9:25–9:30) applies `run_momentum_screener` with `min_composite_score=50` but does not call `_apply_catalyst_bypass()`. This is by design per the docstring but is undocumented in the stage config. **Recommendation**: add an inline comment confirming catalyst bypass intentionally does not apply at final stage, to prevent future accidental omission.

4. **ISSUE — `validate_risk_reward()` uses `t2` but `open_position()` also stores `t1`**
   The R:R validation only checks entry→stop vs entry→t2. There is no guard ensuring `t1 < t2` (bull) or `t1 > t2` (bear), i.e., that T1 and T2 are ordered correctly relative to direction. An inverted T1/T2 would not be caught at open time and could cause `_scale_out()` to fire incorrectly. **Recommendation**: add a T1/T2 ordering assertion in `open_position()` (e.g., `assert t1 < t2 if direction == 'bull' else t1 > t2`).

5. **ISSUE — `SECTOR_GROUPS` is a static hard-coded dict (informational)**
   Sector concentration limits use a fixed list of ~30 large-cap tickers. Screened small/mid-caps (which are the primary targets of War Machine) will never match any sector group, meaning `_calculate_sector_exposure()` returns 0.0 for them and the sector cap is effectively bypassed. **Recommendation**: integrate the `sector` field from `dynamic_screener`'s scored ticker metadata into `_get_ticker_sector()` as a dynamic lookup, replacing the static dict for non-large-cap names.

6. **OBSERVATION — `performance_multiplier` after restart**
   After a mid-session Railway crash, `_load_session_state()` correctly calls `_update_performance_streak(closed_trades)` which replays today's trades to reconstruct the streak. This is correct and robust. No issue.

7. **OBSERVATION — `close_all_eod()` does not pass `current_prices` to circuit breaker**
   Each `close_position()` call inside `close_all_eod()` calls `check_circuit_breaker()` post-close with the real session P&L (FIX #8). For EOD closes this is informational only (session is ending), but it is correct and consistent. No issue.

**Status: CLOSED — 2 actionable issues (#1 narrow-bypass redundancy, #2 live volume signal unbounded), 1 safety gap (#4 T1/T2 ordering), 1 dynamic improvement (#5 sector lookup). Recommendations recorded above.**

---

_This file will be updated continuously as we work through each batch so it stays in sync with the current understanding and decisions from the audit._
