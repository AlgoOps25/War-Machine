# War Machine — Signal Logic Audit

**Auditor:** Perplexity AI  
**Started:** 2026-03-18  
**Scope:** Full signal pipeline — data → screener → funnel → signal engine → validation → options → execution  
**Goal:** 100% flawless signal logic — no silent failures, no phantom blocks, no fabricated data  

---

## Legend

| Severity | Meaning |
|----------|---------|
| 🔴 Critical | Signal is broken, fabricated, or permanently blocked right now in production |
| 🟡 High | Material confidence error, wrong gate logic, or silent degradation |
| 🟠 Medium | Edge-case bug, hardcoded limit, or missing guard |
| 🟢 Low | Logging, style, or minor correctness issue |

**Status tags:** `OPEN` · `FIXED` · `DEFERRED`

---

## Batch 1 — Data Layer & Market Context

**Files:** `app/data/data_manager.py`, `ws_feed.py`, `app/screening/market_calendar.py`

### 🔴 Criticals

| ID | File | Issue | Status |
|----|------|-------|--------|
| 1.C-1 | `data_manager.py` | `get_today_5m_bars()` returns bars from previous session when called before first bar of new session arrives — no date boundary guard | OPEN |
| 1.C-2 | `ws_feed.py` | WebSocket reconnect loop does not re-subscribe to tickers after reconnect — bars stop updating silently after any disconnect | OPEN |
| 1.C-3 | `market_calendar.py` | `is_market_open()` uses `datetime.now()` (local/UTC) not ET — returns wrong result on Railway (UTC server) | OPEN |

### 🟡 Highs

| ID | File | Issue | Status |
|----|------|-------|--------|
| 1.H-4 | `data_manager.py` | `get_bars_from_memory()` has no max-age guard — returns arbitrarily stale bars if WS feed has been silent | OPEN |
| 1.H-5 | `ws_feed.py` | Bar aggregation uses `time.time()` for bar boundary — subject to clock skew; should use bar's own timestamp | OPEN |

### 🟠 Mediums

| ID | File | Issue | Status |
|----|------|-------|--------|
| 1.M-6 | `data_manager.py` | `get_vix_level()` falls back to `20.0` silently on every error — regime filter never knows VIX fetch failed | OPEN |
| 1.M-7 | `market_calendar.py` | Half-day sessions (day before Thanksgiving, Christmas Eve) not handled — system trades full session | OPEN |

---

## Batch 2 — Screener & Universe Funnel

**Files:** `app/screening/dynamic_screener.py`, `premarket_scanner.py`, `volume_analyzer.py`, `watchlist_funnel.py`

### 🔴 Criticals

| ID | File | Issue | Status |
|----|------|-------|--------|
| 2.C-1 | `dynamic_screener.py` | Composite score weights do not sum to 1.0 — over-weighted tickers ranked above genuinely stronger setups | OPEN |
| 2.C-2 | `premarket_scanner.py` | RVOL computed against 5-day average including today's partial volume — inflates RVOL early session | OPEN |

### 🟡 Highs

| ID | File | Issue | Status |
|----|------|-------|--------|
| 2.H-3 | `watchlist_funnel.py` | Catalyst bypass removes RVOL gate entirely — a low-float with a press release and 0.1x RVOL can enter the watchlist | OPEN |
| 2.H-4 | `dynamic_screener.py` | Sector outlier score computed from a static sector dict — sectors updated only at startup, misses intraday rotations | OPEN |
| 2.H-5 | `volume_analyzer.py` | `average_volume` uses 30-day EODHD daily bars but compares against intraday 5-min cumulative — apples-to-oranges RVOL | OPEN |

### 🟠 Mediums

| ID | File | Issue | Status |
|----|------|-------|--------|
| 2.M-6 | `premarket_scanner.py` | Scanner runs at fixed interval regardless of market session — wastes API calls outside RTH | OPEN |
| 2.M-7 | `watchlist_funnel.py` | Funnel cap hardcoded at 20 tickers with no config override | OPEN |

---

## Batch 3 — Signal Engine (Sniper)

**Files:** `app/sniper/sniper.py`, `app/sniper/signal_generator.py`, `app/sniper/breakout_detector.py`

### 🔴 Criticals

| ID | File | Issue | Status |
|----|------|-------|--------|
| 3.C-1 | `breakout_detector.py` | Consolidation box high/low computed from last N bars without excluding the breakout bar itself — box top is often the breakout candle, making every close above box a false breakout | OPEN |
| 3.C-2 | `signal_generator.py` | T1 target = `entry + ATR` but ATR computed on the same bars used for consolidation — during a gap-up, ATR is inflated by the gap bar, producing an unreachable T1 | OPEN |
| 3.C-3 | `sniper.py` | `generate_signal()` can emit duplicate signals for the same ticker within a single scan cycle if the ticker appears on both watchlist and explosive-mover lists | OPEN |

### 🟡 Highs

| ID | File | Issue | Status |
|----|------|-------|--------|
| 3.H-4 | `sniper.py` | RTH guard checks `is_market_open()` which uses local time (see 1.C-3) — on Railway this allows signals outside RTH | OPEN |
| 3.H-5 | `breakout_detector.py` | Minimum consolidation bars hardcoded at 3 — too permissive for 5-min bars (15 minutes of range is not a consolidation) | OPEN |
| 3.H-6 | `signal_generator.py` | Stop loss = `box_low - ATR * 0.5` for bulls — if box_low is already the breakout bar's low, stop is below a meaningless level | OPEN |

### 🟠 Mediums

| ID | File | Issue | Status |
|----|------|-------|--------|
| 3.M-7 | `sniper.py` | Signal cooldown per ticker stored in memory only — resets on every restart, allowing rapid re-entry after deployment | OPEN |
| 3.M-8 | `signal_generator.py` | T2 target computed as `T1 + ATR` with no R:R validation — T2 can be unreachable given typical stop width | OPEN |

---

## Batch 4 — Risk & Position Manager

**Files:** `app/risk/position_manager.py`, `app/risk/circuit_breaker.py`

### 🔴 Criticals

| ID | File | Issue | Status |
|----|------|-------|--------|
| 4.C-1 | `position_manager.py` | Position size computed as `risk_per_trade / stop_distance` — but `stop_distance` is in dollars not percentage; a $0.01 stop on a $500 stock results in 25,000 shares | OPEN |
| 4.C-2 | `circuit_breaker.py` | Daily drawdown counter resets at midnight UTC, not ET market open — positions opened late ET night reset drawdown mid-session the next morning | OPEN |

### 🟡 Highs

| ID | File | Issue | Status |
|----|------|-------|--------|
| 4.H-3 | `position_manager.py` | T1 scale-out does not reduce risk basis — after T1 fill, stop remains at original level, not moved to breakeven | OPEN |
| 4.H-4 | `position_manager.py` | `monitor_position_gex()` called on every bar but `get_live_gex()` fetches from broken `get_chain()` (7.C-1) — GEX exit signals are always null | OPEN |
| 4.H-5 | `circuit_breaker.py` | Max concurrent positions checked after order submission, not before — can briefly exceed the limit during fast fills | OPEN |

### 🟠 Mediums

| ID | File | Issue | Status |
|----|------|-------|--------|
| 4.M-6 | `position_manager.py` | T1 partial exit percentage hardcoded at 50% with no config override | OPEN |
| 4.M-7 | `circuit_breaker.py` | Loss streak counter not persisted to DB — 3-loss streak resets on restart, bypassing the circuit breaker | OPEN |

---

## Batch 5 — Indicators Layer

**Files:** `app/indicators/technical_indicators.py`, `app/indicators/atr_calculator.py`

### 🔴 Criticals

| ID | File | Issue | Status |
|----|------|-------|--------|
| 5.C-1 | `technical_indicators.py` | `check_trend_strength()` fetches ADX from EODHD EOD endpoint — returns yesterday's ADX for intraday signals. Intraday ADX is computed separately in `validation.py` `_calculate_adx()`, creating two different ADX values for the same ticker in the same signal cycle | OPEN |
| 5.C-2 | `technical_indicators.py` | `check_rsi_divergence()` compares price highs/lows to RSI highs/lows over a fixed `lookback_bars=10` window without aligning bar indices — can match non-corresponding bars | OPEN |

### 🟡 Highs

| ID | File | Issue | Status |
|----|------|-------|--------|
| 5.H-3 | `atr_calculator.py` | ATR uses simple average not Wilder's RMA — produces a different (higher) value than the industry-standard ATR used in most charting platforms, making stop distances wider than intended | OPEN |
| 5.H-4 | `technical_indicators.py` | `fetch_ema()` calls EODHD on every invocation with no in-process cache — during a scan cycle hitting 20 tickers, this is 60 sequential API calls for EMA9/20/50 | OPEN |
| 5.H-5 | `technical_indicators.py` | `get_trend_direction()` (DMI) uses EODHD EOD data — same staleness issue as 5.C-1 | OPEN |

### 🟠 Mediums

| ID | File | Issue | Status |
|----|------|-------|--------|
| 5.M-6 | `atr_calculator.py` | ATR period hardcoded at 14 with no override — swing signals and scalp signals use same ATR period | OPEN |
| 5.M-7 | `technical_indicators.py` | `check_bollinger_squeeze()` squeeze threshold hardcoded at `band_width < 0.02` — not normalized to price, so a $500 stock has a much harder time qualifying than a $5 stock | OPEN |

---

## Batch 6 — Execution & Order Management

**Files:** `app/execution/order_manager.py`, `app/execution/tradier_client.py`

### 🔴 Criticals

| ID | File | Issue | Status |
|----|------|-------|--------|
| 6.C-1 | `order_manager.py` | Limit price for options set to `mid` at signal time — not re-evaluated before submission. In fast markets, mid can be stale by 200–500ms, resulting in missed fills or paying ask | OPEN |
| 6.C-2 | `tradier_client.py` | Order confirmation parsed from response JSON without checking HTTP status first — a 4xx response body can contain partial JSON that is misread as a successful order | OPEN |
| 6.C-3 | `order_manager.py` | No re-entry guard after a rejected order — if Tradier rejects an order (e.g., buying power), the signal loop immediately re-submits on the next bar | OPEN |

### 🟡 Highs

| ID | File | Issue | Status |
|----|------|-------|--------|
| 6.H-4 | `tradier_client.py` | API rate limit (200 req/min) not tracked — high-frequency scan cycles can hit the limit; 429 errors are caught but not backed off | OPEN |
| 6.H-5 | `order_manager.py` | Cancel-and-replace logic issues a new order before confirming the cancel of the original — can result in duplicate fills | OPEN |
| 6.H-6 | `tradier_client.py` | Sandbox vs production URL toggled by config flag — no startup assertion that confirms which environment is active | OPEN |

### 🟠 Mediums

| ID | File | Issue | Status |
|----|------|-------|--------|
| 6.M-7 | `order_manager.py` | Order ID not stored in DB immediately after submission — a crash between submission and DB write loses the order reference | OPEN |
| 6.M-8 | `tradier_client.py` | `timeout=10` on all requests — a 10-second stall during order submission blocks the entire scan cycle for that duration | OPEN |

---

## Batch 7 — Options Layer

**Files:** `app/options/options_intelligence.py`, `app/options/gex_engine.py`, `app/options/__init__.py`, `app/options/iv_tracker.py`

### 🔴 Criticals

| ID | File | Issue | Status |
|----|------|-------|--------|
| 7.C-1 | `options_intelligence.py` | `get_chain()` always returns `None` — `chain = None  # TODO` stub never replaced. Entire options validation layer (GEX gate, IVR gate, UOA detection, Step 6.5) is permanently dark | OPEN |
| 7.C-2 | `gex_engine.py` | GEX `gamma_flip` fallback (when no zero-crossing) selects the strike with the smallest absolute GEX value and promotes it as the flip level — conceptually wrong; sets `neg_gex_zone` incorrectly on one-sided chains | OPEN |
| 7.C-3 | `options_intelligence.py` | `_calculate_uoa_score()` derives "average" volume/OI from current value when no baseline exists (`avg = current / 2`), guaranteeing every contract hits the UOA threshold — UOA detection has zero discriminating power | OPEN |

### 🟡 Highs

| ID | File | Issue | Status |
|----|------|-------|--------|
| 7.H-4 | `__init__.py` | `risk_reward` hardcoded as `"1:2.5"` on every trade — never computed from actual stop/target levels | OPEN |
| 7.H-5 | `options_intelligence.py` | Bear pin-drag soft warning fires when `pin < entry_price` — for a bear signal this is a tailwind (favorable), not a support-floor headwind. Label and gate logic inverted | OPEN |
| 7.H-6 | `options_intelligence.py` | `_compute_gex_score()` awards 10 pts for pin-above, 5 pts for pin-below regardless of signal direction — bull-biased scoring used on bear signals | OPEN |
| 7.H-7 | `options_intelligence.py` | `_get_ivr_data()` returns on first call option with any IV — uses a random non-ATM, possibly far-expiry IV as the IVR basis | OPEN |
| 7.H-8 | `__init__.py` | `_calculate_fallback_expiration()` bumps the target date an extra 7 days when target date (not today) falls on a Friday — 7-DTE trades become 14-DTE unexpectedly | OPEN |

### 🟠 Mediums

| ID | File | Issue | Status |
|----|------|-------|--------|
| 7.M-9 | `__init__.py` | Max contracts hardcoded at `min(quantity, 10)` with no config override | OPEN |
| 7.M-10 | `__init__.py` | `_get_current_price()` silently returns `None`; `build_options_trade()` returns `None` with no caller-side guard in most callers | OPEN |
| 7.M-11 | `options_intelligence.py` | `_ivr_cache` populated in `__init__` but never written to — every IVR call is a DB round-trip | OPEN |
| 7.M-12 | `gex_engine.py` | `top_negative` built with `[-5:][::-1]` on desc-sorted list — returns 5 least-negative entries, not most negative | OPEN |
| 7.M-13 | `options_intelligence.py` | Chain refresh invalidates `_score_cache`, `_gex_cache`, `_uoa_cache` but not `_ivr_cache` — stale IVR can persist across chain refresh | OPEN |
| 7.M-14 | `__init__.py` | `target_dte` computed at call time inside `_select_strike_with_greeks()` but `target_date` computed earlier in `build_options_trade()` — midnight boundary race condition | OPEN |
| 7.M-15 | `options_intelligence.py` | `scan_chain_for_uoa()` scans all expirations including LEAPS — inflates OI figures; should filter to ≤ 45 DTE | OPEN |

### 🟢 Lows

| ID | File | Issue | Status |
|----|------|-------|--------|
| 7.L-16 | `__init__.py` | `iv * 100` has no guard against IV already in percentage form — could produce IV = 4000% | OPEN |
| 7.L-17 | `gex_engine.py` | No zero-price guard in GEX formula — `current_price = 0` silently zeroes all GEX contributions | OPEN |
| 7.L-18 | `options_intelligence.py` | `print()` in `__init__` and `clear_cache()` instead of `logger.*` | OPEN |
| 7.L-19 | `__init__.py` | OCC symbol builder does not pad ticker to 6 chars (OCC standard) — symbols for short tickers malformed | OPEN |

---

## Batch 8 — Validation Layer

**Files:** `app/validation/validation.py` (SignalValidator, RegimeFilter, OptionsFilter), `cfw6_gate_validator.py`, `cfw6_confirmation.py`, `entry_timing.py`, `hourly_gate.py`, `volume_profile.py`

### 🔴 Criticals

| ID | File | Issue | Status |
|----|------|-------|--------|
| 8.C-1 | `validation.py` | `validate_signal()` compares `signal_direction == 'BUY'` / `'SELL'` but all callers pass `'bull'` / `'bear'` — EMA stack and DMI checks always fall into wrong branch, applying **-14% confidence penalty to every bull signal** in production | OPEN |
| 8.C-2 | `validation.py` | VPVR rescue adds `+0.20` but the `-0.25` bias penalty is already applied and not reversed — rescued signal carries permanent net **-5% penalty** despite "full rescue" claim | OPEN |
| 8.C-3 | `validation.py` | `_classify_regime()` returns `favorable=True` for VIX 25–29 TRENDING — both branches of the `vix < 25` split return `True`; only log message differs. High-volatility tape accepted as fully favorable | OPEN |
| 8.C-4 | `validation.py` | `filter_by_dte()` uses `datetime.now()` (UTC on Railway) vs ET market dates — 0-DTE and same-day options compute as `dte = -1` (expired) and are permanently filtered out | OPEN |

### 🟡 Highs

| ID | File | Issue | Status |
|----|------|-------|--------|
| 8.H-5 | `validation.py` | `should_pass` fallback = `len(passed_checks) >= len(failed_checks)` — numeric vote ignores check severity; 5 trivial passes override 4 critical failures | OPEN |
| 8.H-6 | `validation.py` | Regime filter called twice per signal (once in sniper, once inside `validate_signal()`) — can return different results if cache expires mid-cycle; doubles API load | OPEN |
| 8.H-7 | `validation.py` | IV hard-fail threshold `> 1.0` is correct for decimal-form IV but has no guard against percentage-form IV (e.g., `45.0`) — a single malformed EODHD record silently blocks all options trades | OPEN |
| 8.H-8 | `validation.py` | `get_options_chain()` fetches only 30 days of expirations — if `config.MAX_DTE > 30`, valid strikes are never returned from the API | OPEN |
| 8.H-9 | `validation.py` | `_get_spy_bars()` falls through 3 data sources silently — early-session CHOPPY blocks indistinguishable from real bad-tape blocks in logs | OPEN |
| 8.H-10 | `validation.py` | `scan_chain_for_uoa` imported from `options_intelligence` which is broken (7.C-1); `format_uoa_summary` imported from a stub — UOA enrichment in `find_best_strike()` is silently no-op | OPEN |

### 🟠 Mediums

| ID | File | Issue | Status |
|----|------|-------|--------|
| 8.M-11 | `validation.py` | ADX requires 29 bars but early session may have fewer — `_calculate_adx()` returns `None` → regime defaults to `favorable=False` independently of 8.H-9 | OPEN |
| 8.M-12 | `validation.py` | `VPVR_RESCUE` and `VPVR_STRONG` can both apply to the same signal — `vpvr_rescue_applied` flag doesn't block the `entry_score >= 0.85` branch below, double-counting up to `+0.28` adj | OPEN |
| 8.M-13 | `validation.py` | `_normalize_v2_chain()` silently drops malformed options records with no counter or log | OPEN |
| 8.M-14 | `validation.py` | `get_time_of_day_quality()` has no timezone enforcement — passing a naive datetime uses server local time silently | OPEN |
| 8.M-15 | `hourly_gate.py` | Hourly gate may duplicate the time-of-day penalty already applied by `SignalValidator` — double-penalizing the same signal | OPEN |
| 8.M-16 | `validation.py` | VPVR `lookback_bars=78` hardcoded — skips VPVR for first ~3.5 hours of session when fewer than 78 bars exist | OPEN |
| 8.M-17 | `entry_timing.py` | DTE filter logic duplicated from `OptionsFilter.filter_by_dte()` — two independent implementations that can diverge on threshold changes | OPEN |
| 8.M-18 | `cfw6_gate_validator.py` | CFW6 gate and `SignalValidator` both run regime checks — two separate regime evaluations per signal with independent cache windows | OPEN |

### 🟢 Lows

| ID | File | Issue | Status |
|----|------|-------|--------|
| 8.L-19 | `validation.py` | `print()` throughout all three classes instead of `logger.*` | OPEN |
| 8.L-20 | `validation.py` | `get_options_recommendation()` creates a new `OptionsFilter()` instance on every call — bypasses singleton cache, fresh chain fetch every time | OPEN |
| 8.L-21 | `validation.py` | `calculate_expected_move()` has no guard against percentage-form IV — expected move wildly inflated if IV > 1.0 | OPEN |
| 8.L-22 | `validation.py` | `get_options_recommendation` not in `__all__` — callers using `from validation import *` won't find it | OPEN |

---

## Summary — All Open Issues by Severity

| Batch | 🔴 Critical | 🟡 High | 🟠 Medium | 🟢 Low | Total |
|-------|------------|--------|----------|-------|-------|
| 1 — Data Layer | 3 | 2 | 2 | 0 | 7 |
| 2 — Screener | 2 | 3 | 2 | 0 | 7 |
| 3 — Signal Engine | 3 | 3 | 2 | 0 | 8 |
| 4 — Risk/Position | 2 | 3 | 2 | 0 | 7 |
| 5 — Indicators | 2 | 3 | 2 | 0 | 7 |
| 6 — Execution | 3 | 3 | 2 | 0 | 8 |
| 7 — Options Layer | 3 | 5 | 7 | 4 | 19 |
| 8 — Validation | 4 | 6 | 8 | 4 | 22 |
| **TOTAL** | **22** | **28** | **27** | **8** | **85** |

---

## Top Priority Fix Queue

The following issues have the highest combined impact on live signal correctness and should be addressed first regardless of batch:

1. **7.C-1** — Wire `get_chain()` — entire options layer is dark
2. **8.C-1** — Direction string mismatch (`'bull'`/`'bear'` vs `'BUY'`/`'SELL'`) — -14% on every bull signal
3. **1.C-3 / 3.H-4 / 8.C-4** — UTC vs ET timezone cluster — affects RTH guard, DTE filter, and regime detection
4. **8.C-2** — VPVR rescue math — rescued signals are still net-penalized
5. **7.C-3** — UOA self-referential baseline — every contract appears unusual
6. **7.C-2** — GEX flip fallback — wrong zone classification on one-sided chains
7. **4.C-1** — Position sizing with dollar stop — potential for massively oversized positions
8. **8.C-3** — VIX 25–29 regime — high-volatility tape accepted as fully favorable
9. **3.C-1** — Breakout box includes breakout bar — false breakout detection
10. **6.C-2** — Order confirmation parsing — 4xx response misread as success

---

*Last updated: 2026-03-18 after Batch 8. Batch 9 will cover: `app/mtf`, `app/ml`, `app/filters`, `app/backtesting`, `app/indicators` (deeper), `vpvr_calculator`, `daily_bias_engine`.*
