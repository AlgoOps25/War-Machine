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
- Batch 1.A and 1.B initial invariants captured; next up is 1.C (funnel + risk).

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

**Initial findings / notes**
- `market_calendar.is_active_session()` correctly prevents scanning on weekends and enumerated holidays, but holiday sets are currently hard-coded for 2026–2027 only; future years will require updates.
- `data_manager.update_ticker()` correctly skips intraday REST fetches during RTH when `ENABLE_WEBSOCKET_FEED` is on and `ws_feed.is_connected()` is True.
- `get_today_session_bars()` and `get_today_5m_bars()` have explicit date boundaries (04:00–20:00 ET) and never fall back to prior days, which matches the stated design.
- `ws_feed` uses a single `_flush_loop` that calls both `_flush_pending()` (closed bars) and `_flush_open()` (open bars), with open-bar upserts always `quiet=True` to avoid log spam.
- REST failover in `ws_feed.get_current_bar_with_fallback()` is protected by a 15-second per-ticker cache and only triggers when `_connected` is False, which prevents API hammering during short WS outages.

_Additional, more granular invariants and any discovered edge cases will be appended here as testing and static analysis proceeds._

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
- `volume_analyzer` tracks per-ticker rolling volume/price state to detect bottom/peak volume and volume–price divergence patterns, and exposes `get_session_volume()` which premarket_scanner uses as the true intraday volume denominator for RVOL.

**Key invariants to enforce**
- **Universe consistency**
  - All tickers entering `WatchlistFunnel` must have come from either `dynamic_screener` (scored output) or an explicit emergency list; ETFs (except SPY/QQQ) must never leak into the scored universe.
  - RVOL tiers (A/B/C) from `dynamic_screener` must align with RVOL expectations in premarket scoring; Tier D (sub-1.0 RVOL) is hard-dropped and cannot surface later.

- **RVOL and dollar-volume correctness**
  - Pre-market RVOL in `premarket_scanner` must always use cumulative intraday volume from `get_intraday_cumulative_volume()` when WS/DB data is present, never a single-bar slice when more data is available.
  - REST-sourced bars must have RVOL clamped (currently 10x) to prevent prior-day cumulative volume from producing artificial outliers.
  - The early RVOL exit gate (`EARLY_EXIT_RVOL_MIN`) must only execute after a successful fundamentals fetch (ADV>0) and must never fabricate a score path when ADV is missing.

- **Ghost-score and data-failure handling**
  - When `fetch_fundamental_data()` fails (e.g., HTTP error or insufficient bars), `_get_default_fundamentals()` must cause `scan_ticker()` to return `None` (not a low but non-zero composite), so that dead data never pollutes the watchlist.
  - Any path that yields `price <= 0` after bar resolution must hard-stop the scan for that ticker and return `None`.

- **Gap and catalyst semantics**
  - Gap analysis must always use the best-available previous close: REST-derived `previousClose` when available pre-market, otherwise the EOD close from fundamentals; `current_price` must reflect the true pre-market gap price (`open` field) when EODHD real-time returns prior-close in `close`.
  - `detect_catalyst()` must be called at most once per ticker per scan; its result is shared between Tier 2 (gap flags) and Tier 3 (catalyst score).
  - Catalyst scores (earnings/news/analyst/FDA/M&A) must be strictly additive and bounded, and any Discord/webhook failures must never block or alter scoring.

- **Composite score integrity**
  - Every composite score must be a deterministic function of: volume_score, gap_score, catalyst_score, and sector_bonus, with weights 60/25/15 plus the additive sector bonus; no alternative weighting paths should exist.
  - The only legitimate "volume-only" composite path is the early-exit low-RVOL path, and it must still be derived from real ADV and bar data (not defaults).

**Initial findings / notes**
- `dynamic_screener` correctly enforces ETF exclusion while explicitly exempting SPY/QQQ, and its in-play/RVOL/dollar-vol gates mean all candidates entering the pre-market scanner already meet a baseline liquidity standard.
- `premarket_scanner` Phase 1.23/1.23a/1.24/1.28/1.29 changes collectively eliminate the previously observed ghost 12.9 scores by: (a) bailing out when ADV==0, (b) bailing out when price==0, (c) clamping REST-based RVOL, and (d) injecting an early-exit gate that only triggers when both ADV and RVOL are valid.
- Gap analysis now correctly treats REST `open` as the gap price and REST `previousClose` as the reference when present, fixing the earlier 0.0% gap bug for REST-only tickers.
- News catalyst detection uses a strict, event-focused keyword set and a 48h recency window, with per-ticker caching to avoid repeated EODHD calls; Discord webhook errors are logged but do not affect detection or scoring.
- `volume_analyzer.get_session_volume()` and `get_intraday_cumulative_volume()` are aligned on the idea of cumulative same-day volume as the denominator; both explicitly constrain by today’s date and handle DB/connection failures by returning 0 (which in turn is guarded by the ADV>0 checks in premarket_scanner).

_Further refinements in this batch will focus on codifying these invariants into tests (unit + integration) and validating behaviour on edge conditions such as partial WS data, early-morning fundamentals lag, and mixed REST/WS sessions._

---

_This file will be updated continuously as we work through each batch so it stays in sync with the current understanding and decisions from the audit._
