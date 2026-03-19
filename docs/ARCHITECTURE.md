# War Machine — Architecture Reference

> **Source:** Converted from `docs/architecture/WAR_MACHINE_ARCHITECTURE.txt` (originally compiled March 10, 2026).  
> **Status:** Structural flow still accurate. For current file-level audit with all session changes, see [`docs/AUDIT_REGISTRY.md`](./AUDIT_REGISTRY.md).  
> **Changes since March 10:** See [`docs/CHANGELOG.md`](./CHANGELOG.md) — Sessions S0–S7.

---

## System Overview

```
Railway Container
└── main.py  →  app/core/scanner.py (start_scanner_loop)
                    ├── app/core/sniper.py          ★ CFW6 Signal Engine
                    ├── app/core/arm_signal.py       Position execution
                    ├── app/core/position_manager.py  Tradier order management
                    ├── app/core/health_server.py    HTTP /health endpoint
                    ├── app/core/eod_reporter.py     EOD Discord reports
                    ├── app/data/websocket_client.py  EODHD WebSocket (1m bars)
                    ├── app/data/db_connection.py    PostgreSQL pool
                    └── app/signals/signal_analytics.py  Funnel tracking
```

---

## Section 0 — Repo Root (Infrastructure / Deployment)

| File | Purpose | Risk |
|------|---------|------|
| `main.py` | Entrypoint — calls `start_scanner_loop()` | Import-time crash = silent Railway death |
| `railway.toml` | Build/start/healthcheck config | `healthcheckPath = "/health"` must stay live |
| `nixpacks.toml` | Python 3.11 + gcc/libpq for psycopg2 | Don't unpin Python version |
| `requirements.txt` | Dependency manifest | See `docs/AUDIT_REGISTRY.md` for pinning issues |
| `.railway-trigger` / `.railway_trigger` | Force-redeploy dummy files | Two variants exist (hyphen + underscore) — redundant |

---

## Section 1 — `app/core/` (Orchestration Layer)

### `scanner.py` ★ PRIMARY ORCHESTRATOR
- **Size:** ~37 KB / ~900 lines
- **Role:** Master control loop. Owns entire session lifecycle: market open detection, pre-market scan, RTH scan loop, EOD reporting, WebSocket management.
- **Key flows:** `market_open_routine()` → `run_scan_cycle()` → `sniper.process_ticker()` × N tickers → `eod_reporter.run_eod_report()`

### `sniper.py` ★ CFW6 SIGNAL ENGINE
- **Size:** ~78 KB / ~2000 lines (largest file in repo)
- **Role:** Core signal detection per ticker. Implements full CFW6 logic: BOS detection, FVG detection, confirmation flow, grade assignment, confidence scoring, MTF alignment check, all validator gates.
- **Critical:** `_armed_signals` and `_watching_signals` are unprotected plain dicts — `thread_safe_state.py` exists but is not wired in (see C3 below).

### `arm_signal.py`
- **Role:** Executes position open via `position_manager.py` after `sniper.py` confirms signal. Fires Discord alert after position confirmed (fixed in S0).
- **Updated S4:** Now calls `signal_tracker.record_trade_executed()` after successful open.

### `position_manager.py`
- **Role:** Tradier API wrapper. Places option orders, tracks open positions in PostgreSQL, manages stop/target monitoring.

### `thread_safe_state.py`
- **Role:** `ThreadSafeDict` / `ThreadSafeSet` wrappers using `threading.RLock()`.
- **⚠ NOT WIRED:** Built but never imported by `sniper.py`. Pending fix — see C3 below.

### `eod_reporter.py`
- **Role:** Fires at market close. Sends signal funnel, performance report, MTF stats, gate distribution, regime summary to Railway logs + Discord.

### `health_server.py`
- **Role:** Starts a lightweight HTTP server on port 8080. Returns 200 on `/health` when scanner loop is alive.
- **Note:** `app/health_check.py` also exists — verify only one is active at runtime.

---

## Section 2 — `app/data/` (Data Layer)

| File | Role |
|------|------|
| `websocket_client.py` | EODHD WebSocket — streams 1m bars, feeds `candle_cache.py` |
| `candle_cache.py` | In-memory bar store with TTL. All REST bar fetches route here |
| `db_connection.py` | PostgreSQL connection pool (authoritative) |
| `database.py` | Re-export shim → `db_connection.py` (backward compat only, S2) |
| `eodhd_client.py` | EODHD REST fallback for symbols not in WebSocket stream |
| `tradier_client.py` | Tradier REST client — quotes, option chains, account data |

---

## Section 3 — `app/signals/` (Signal Lifecycle)

| File | Role |
|------|------|
| `signal_analytics.py` | `SignalTracker` — GENERATED→VALIDATED→ARMED→TRADED→CLOSED funnel |
| `signal_validator.py` | Gate checks: ADX, VOLUME, DMI, VPVR, IV, MTF |
| `signal_boosters.py` | Confidence point additions: explosive override, UOA boost, GEX boost |
| `grade_gate.py` | Grade assignment (A+/A/A-) + confidence threshold enforcement |
| `cooldown_manager.py` | 30-min per-ticker cooldown, resets at market open |

---

## Section 4 — `app/mtf/` (Multi-Timeframe)

| File | Role |
|------|------|
| `mtf_compression.py` | Compresses 1m WS bars to 5m/15m/1H in memory — no extra REST calls |
| `mtf_integration.py` | Builds MTF bias object (trend + FVG alignment per timeframe) |
| `bos_fvg_engine.py` | BOS + FVG detection across all timeframes |
| `mtf_fvg_priority.py` | Ranks and selects highest-priority FVG when multiple detected |
| `sniper_mtf_trend_patch.py` | Hot-patch during Phase 2A transition — to be absorbed |

---

## Section 5 — `app/ml/` (Machine Learning)

| File | Role |
|------|------|
| `ml_signal_scorer_v2.py` | Active production scorer — Random Forest on 10-feature CFW6 vector |
| `ml_signal_scorer.py` | v1 scorer — retained as fallback |
| `ml_confidence_boost.py` | Applies calibrated ±delta to sniper confidence |
| `ai_learning.py` | Daily retraining at EOD — writes updated model to PostgreSQL |
| `train_from_analytics.py` | Manual retraining script → `scripts/ml/` |
| `train_historical.py` | Historical batch trainer → `scripts/ml/` |

---

## Section 6 — `app/filters/` (Gate Layer)

| File | Role |
|------|------|
| `correlation.py` | Sector correlation check — blocks >2 positions in same group |
| `entry_timing.py` | Blocks entries in final 30-min (3:30–4:00 PM ET) |
| `explosive_filter.py` | Validates explosive move candidates against minimum criteria |
| `greeks_precheck.py` | Options Greeks pre-validation before full options analysis |

---

## Section 7 — `app/options/` (Options Intelligence)

| File | Role |
|------|------|
| `options_intelligence.py` | Scores contracts by liquidity, spread, OI, flow alignment |
| `gex_engine.py` | GEX (Gamma Exposure) — identifies pinning vs explosive zones |
| `iv_tracker.py` | Rolling IV Rank per ticker (0–100) |
| `options_data_manager.py` | Caches all Tradier options calls — prevents redundant API hits |
| `unusual_options_activity.py` | UOA detection — feeds `signal_boosters.py` |

---

## Section 8 — `app/risk/` (Risk Management)

| File | Role |
|------|------|
| `trade_calculator.py` | Position sizing: account equity × risk% ÷ stop distance |
| `vix_sizing.py` | VIX-driven size multiplier (1.0x → 0.4x based on VIX level) |
| `circuit_breaker.py` | Halts trading on drawdown or loss streak trigger |
| `portfolio_heat.py` | Tracks aggregate risk exposure across all open positions |

---

## Section 9 — `app/analytics/` (Monitoring)

| File | Role |
|------|------|
| `performance_monitor.py` | P&L tracking, win rate by grade, Sharpe, max drawdown, streaks |
| `performance_alerts.py` | Discord alerts for circuit breaker proximity, win/loss streaks |
| `explosive_tracker.py` | Real-time session explosive move monitor |
| `explosive_mover_tracker.py` | Historical explosive move cataloguer → PostgreSQL |
| `rth_filter.py` | RTH sub-session quality tracking (Power Hour, Midday, etc.) |
| `scanner_optimizer.py` | Uses RTH quality data to adjust scan intensity by time window |

---

## Section 16 — Critical Flaws (Prioritized)

> These flaws were identified March 10, 2026. Check `docs/AUDIT_REGISTRY.md` for current resolution status.

### 🔴 CRITICAL — Can cause real money loss or silent data corruption

| ID | Flaw | Fix |
|----|------|-----|
| C1 | Position state in-memory only — container restart loses all open positions (live trades invisible to bot) | Persist `open_positions` to PostgreSQL on every open/close event |
| C2 | Discord alert fires BEFORE `position_manager` accepts trade — rejected trade still shows as alert | Fire Discord only after `open_position()` confirms — **FIXED S0** |
| C3 | `thread_safe_state.py` exists but NEVER used — `_armed_signals` / `_watching_signals` are unprotected plain dicts | Replace with `ThreadSafeDict` from `thread_safe_state.py` |
| C4 | Parquet cache write non-atomic — crash mid-write corrupts cache file, next startup reads garbage silently | Write to `.tmp` then `os.replace()` atomically |
| C5 | Health check always returns 200 — Railway never restarts a crashed scanner | Health endpoint must check scanner loop heartbeat timestamp |

### 🟠 HIGH

| ID | Flaw | Fix |
|----|------|-----|
| H1 | Regime filter makes one API call per ticker per cycle (up to 50/cycle) | Cache regime result 5 min system-wide — **FIXED (Phase 3A)** |
| H2 | MTF bars have no cache — 50 REST calls per cycle for HTF trend | Cache HTF bars per ticker with 5-min TTL via `mtf_compression.py` — **FIXED (Phase 2A)** |
| H3 | ML model weights saved to ephemeral container filesystem — lost on restart | Write weights to PostgreSQL or Railway persistent volume |
| H4 | Analytics DB connection has no reconnect logic | Wrap all DB calls with reconnect-on-error pattern |
| H5 | Backtest imports live `sniper.py` without disabling side effects | Add `DRY_RUN` flag to `sniper.py` |

### 🟡 MEDIUM

| ID | Flaw |
|----|------|
| M1 | Two `AnalyticsIntegration` paths create two sources of truth |
| M2 | `signal_analytics.py` (legacy in-memory) duplicates DB analytics tracking |
| M3 | `sniper_stubs.py` runs silently with no alert when active (ghost mode) |
| M4 | Cooldown state lost on restart — duplicate signals possible post-restart |
| M5 | Loss streak counter not reset at EOD independently |
| M6 | Indicators assume oldest-first bar sort — no defensive sort guarantee |
| M7 | No CI pipeline — broken code can reach production on every git push |
| M8 | IV Rank hardcoded to 50 — options sizing wrong in high/low IV environments |
| M9 | `build_0dte_trade()` is dead code in live production |
| M10 | Discord calls are synchronous — webhook outage blocks the scan loop |

---

*Last updated: 2026-03-16 | Converted from `docs/architecture/WAR_MACHINE_ARCHITECTURE.txt` | For current audit: see `docs/AUDIT_REGISTRY.md`*
