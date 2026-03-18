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
- Next: formalize invariants and record per-module findings below.

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

_This file will be updated continuously as we work through each batch so it stays in sync with the current understanding and decisions from the audit._
