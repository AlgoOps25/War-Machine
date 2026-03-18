# Batch 1: Core Signal Path — COMPLETE

**Modules**
- app/data/data_manager.py
- app/data/ws_feed.py
- app/screening/market_calendar.py
- app/screening/dynamic_screener.py
- app/screening/premarket_scanner.py
- app/screening/volume_analyzer.py
- app/screening/watchlist_funnel.py
- app/risk/position_manager.py

**Status: COMPLETE — 1.A, 1.B, 1.C all closed. See sub-sections below.**

---

## Batch 1.A: Calendar, sessions, and data ingestion — CLOSED

**Status: CLOSED — no outstanding issues.**

**Key invariants confirmed**
- No scanning on weekends or holidays; `build_watchlist()` short-circuits via `is_active_session()`. ✅
- WS-first: no REST intraday calls when `ws_feed.is_connected()` is True. ✅
- `get_today_session_bars()` bounded to today's ET date (04:00–20:00); never falls back to prior day. ✅
- Every WS bar flushed exactly once; 5m bars idempotently materialized. ✅
- REST failover: 15s per-ticker TTL, only when `_connected=False`. ✅

**Findings**
- Holiday sets hard-coded for 2026–2027 only — future years need updates.
- All other invariants confirmed clean.

---

## Batch 1.B: Screener, pre-market scanner, and volume signals — CLOSED

**Status: CLOSED — no outstanding issues.**

**Key invariants confirmed**
- ETFs (except SPY/QQQ) never leak into scored universe; Tier D (sub-1.0 RVOL) hard-dropped. ✅
- Pre-market RVOL uses cumulative intraday volume; REST bars clamped (10×). ✅
- `fetch_fundamental_data()` failure → `scan_ticker()` returns `None` (no ghost scores). ✅
- `price <= 0` after bar resolution → hard-stop for that ticker. ✅
- `detect_catalyst()` called at most once per scan; Discord failures non-blocking. ✅
- Composite = 0.60·volume + 0.25·gap + 0.15·catalyst + sector_bonus (no alternate weight path). ✅

**Findings**
- All ghost-score paths closed by Phase 1.23–1.29.
- Gap analysis uses REST `open` + `previousClose`; 0.0% bug resolved.
- Catalyst: strict keywords, 48h window, per-ticker cache.

---

## Batch 1.C: Watchlist funnel and position manager — CLOSED

**Status: CLOSED — 4 actionable items recorded.**

**Outstanding action items**
1. (**Safety**) `open_position()`: add T1/T2 ordering assertion.
2. (**Design**) Replace static `SECTOR_GROUPS` lookup with dynamic screener `sector` field.
3. (**Low**) Cap live-stage volume signal adjustment at ±5 per ticker (deduplicate).
4. (**Minor**) Remove redundant inline bypass check from `_build_narrow_scan()`.
