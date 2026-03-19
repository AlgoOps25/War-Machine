# War Machine — Remediation Tracker
**Audit Scope:** Batches 1–46 | ~850 findings across the full codebase
**Tracker Created:** 2026-03-18
**Last Updated:** 2026-03-19

> This file is updated after **every committed fix**. Each row tracks finding ID,
> file, description, status, commit SHA, and date resolved.
> Never mark a finding DONE until the fix is committed and the SHA is recorded here.

---

## Status Legend
| Symbol | Meaning |
|--------|---------|
| ⬜ | Not started |
| 🔄 | In progress |
| ✅ | Fixed & committed |
| ❌ | Won't fix / not applicable |
| 🔁 | Superseded by another fix |

---

## Phase 1 — Root Cause Fixes (Fix These First)
> These fixes automatically resolve or reduce 10+ downstream findings each.

| Status | ID | File | Description | Commit SHA | Date |
|--------|----|------|-------------|------------|------|
| ✅ | 44.H-2 | `utils/time_helpers.py` | `_strip_tz()` drops TZ without converting to ET first — root cause of 15+ tz-naive bugs across 20+ files. Fix: `dt.astimezone(ET).replace(tzinfo=None)` | `5cee401` | 2026-03-18 |
| ✅ | 8.C-1 | `app/validation/validation.py` | Direction mismatch `BUY/SELL` vs `bull/bear` — -14% confidence penalty on every bull signal. Fix: normalize direction string before comparison | `409b5f6` | 2026-03-18 |
| ✅ | 7.C-1 | `app/options/options_intelligence.py` | `get_chain()` always returns `None` — entire options layer is dark. Fix: restore live chain fetch via `OptionsFilter.get_options_chain()` | `c9f613f` | 2026-03-18 |
| ✅ | 14.C-1 | `app/data/db_connection.py` | Pool initialized at module import — Railway cold-start crash if DB unavailable. Fix: lazy pool init via `_init_pool()` with double-checked locking | `242a37a` | 2026-03-19 |
| ⬜ | 15.C-1 | `app/data/data_manager.py` | Destructive migration fires on transient DB error mid-session — can wipe all bars. Fix: require explicit `FORCE_MIGRATION=true` env flag | — | — |
| ⬜ | 15.C-2 | `app/data/data_manager.py` | Inverted tz logic in `startup_backfill_with_cache()` → TypeError → full API backfill every startup, cache never used | — | — |

---

## Phase 2A — BOS/FVG Signal Logic
> Core signal detection correctness.

| Status | ID | File | Description | Commit SHA | Date |
|--------|----|------|-------------|------------|------|
| ⬜ | 40.H-2 | `app/mtf/bos_fvg_engine.py` | `detect_bos()` only checks the single latest bar — BOS events 1-2 cycles old are permanently missed. Fix: scan last 5 bars | — | — |
| ⬜ | 40.H-3 | `app/mtf/bos_fvg_engine.py` | FVG bounce check uses `fvg_mid` instead of `fvg_high/low` — entries fire while price still inside gap. Fix: bull=`>= fvg_high`, bear=`<= fvg_low` | — | — |
| ⬜ | 40.H-1 | `app/mtf/bos_fvg_engine.py` | `find_fvg_after_bos()` searches 5 bars BEFORE BOS — finds pre-BOS imbalances. Fix: `search_start = bos_idx` | — | — |
| ⬜ | 40.H-4 | `app/mtf/mtf_integration.py` | `_mtf_cache` keyed by `ticker_direction` never expires intra-day — stale 9:35 result returned at 11:00. Fix: key by `(ticker, direction, len(bars))` | — | — |
| ⬜ | 40.M-7 | `app/mtf/mtf_integration.py` | `scan_tf_for_signal()` uses `config.FVG_MIN_SIZE_PCT` — adaptive threshold from `sniper.py` not propagated to MTF scans | — | — |
| ⬜ | 46.H-1 | `app/mtf/mtf_compression.py` | Compression functions assume 1m input — if `bars_session` is 5m, all TFs are 5× too long | — | — |
| ⬜ | 46.H-2 | `app/mtf/mtf_compression.py` | Duplicate bar resampler — also defined inline in `sniper.py`. Fix: delete inline version, import from `mtf_compression.py` | — | — |

---

## Phase 2B — Confidence Gate & Scoring
> Ensures confidence values are accurate and gated correctly.

| Status | ID | File | Description | Commit SHA | Date |
|--------|----|------|-------------|------------|------|
| ⬜ | 39.H-2 | `app/core/sniper.py` | `record_signal_generated()` called before confidence gate — gate rejections have no stage label in funnel analytics | — | — |
| ⬜ | 40.M-11 | `app/mtf/mtf_integration.py` | `run_mtf_trend_step()` caps confidence at 0.99 instead of 0.95 — bypasses global ceiling | — | — |
| ⬜ | 41.H-2 | `app/mtf/smc_engine.py` | `enrich_signal_with_smc()` total delta can exceed +0.10 cap if multiple components each contribute +0.03 | — | — |
| ⬜ | 42.M-13 | `app/filters/order_block_cache.py` | OB retest boost `+0.03` hardcoded — should be `config.OB_RETEST_BOOST` | — | — |

---

## Phase 2C — Race Conditions & State
> Thread safety and TOCTOU correctness.

| Status | ID | File | Description | Commit SHA | Date |
|--------|----|------|-------------|------------|------|
| ⬜ | 39.C-1 | `app/core/sniper.py` | TOCTOU race: `ticker_is_watching()` checked twice with DB index resolve loop between — concurrent state change causes fall-through to OR scan. Fix: cache `is_watching` before resolve | — | — |
| ⬜ | 9.C-5 | `app/data/armed_signal_store.py` | TOCTOU in `_maybe_load_armed_signals()` — signals missed on restart | — | — |
| ⬜ | 9.C-4 | `app/core/scanner.py` | `analytics_conn` shared across threads without lock — connection corruption | — | — |
| ⬜ | 40.M-12 | `app/mtf/mtf_integration.py` | `_mtf_stats` module-level dict incremented from multiple threads without lock | — | — |
| ⬜ | 42.M-11 | `app/filters/mtf_bias.py` | `record_stat()` modifies module-level dict without lock | — | — |

---

## Phase 2D — Validation Logic
> Fixes to the validation/confirmation layer.

| Status | ID | File | Description | Commit SHA | Date |
|--------|----|------|-------------|------------|------|
| ⬜ | 8.C-2 | `app/validation/validation.py` | VPVR rescue doesn't fully restore bias penalty — net -5% confidence leak | — | — |
| ⬜ | 8.C-3 | `app/validation/validation.py` | `_classify_regime()` returns `favorable=True` for VIX 25–29 TRENDING — wrong regime label | — | — |
| ⬜ | 8.C-4 | `app/validation/validation.py` | `filter_by_dte()` uses `datetime.now()` UTC — 0-DTE permanently invisible (4-5 hour offset) | — | — |
| ⬜ | 4.A-2 | `app/validation/cfw6_confirmation.py` | `wait_for_confirmation()` only tests latest bar — misses multi-bar confirmation patterns | — | — |
| ⬜ | 4.C-10 | `app/validation/entry_timing.py` | `HOURLY_WIN_RATES` is hardcoded fabricated data — win rate gating is noise | — | — |
| ⬜ | 41.H-3 | `app/mtf/mtf_validator.py` | `validate_signal_mtf()` re-fetches bars from DB — 3 extra DB reads per pipeline call. Fix: accept `bars` as parameter | — | — |

---

## Phase 2E — OR / FVG Thresholds
> Reference level and threshold correctness.

| Status | ID | File | Description | Commit SHA | Date |
|--------|----|------|-------------|------------|------|
| ⬜ | 5.G-18 | `app/filters/liquidity_sweep.py` | Bull sweep `close_reclaim` allows close only $0.01 above OR low — not a valid reclaim. Fix: require close above `or_low + 20% of OR range` | — | — |
| ⬜ | 43.M-10 | `app/signals/vwap_reclaim.py` | Synthetic FVG zone ±0.15% hardcoded — should use `get_adaptive_fvg_threshold()` | — | — |
| ⬜ | 40.M-9 | `app/mtf/mtf_integration.py` | MTF OR window `9:30–9:40` is 5 min shorter than main OR window `9:30–9:45` — mismatched levels | — | — |

---

## Phase 3A — Database Safety
> Prevents data loss, pool exhaustion, and cache corruption.

| Status | ID | File | Description | Commit SHA | Date |
|--------|----|------|-------------|------------|------|
| ⬜ | 13.C-1 | `app/analytics/explosive_mover_tracker.py` | `conn.close()` instead of `return_conn()` — pool exhaustion over session | — | — |
| ⬜ | 13.C-2 | `app/analytics/ab_test_framework.py` | `get_conn(db_path)` raises TypeError at import — crashes Railway startup | — | — |
| ⬜ | 14.H-7 | `app/data/candle_cache.py` | Stripped TZ on cache rows → naive UTC vs ET boundary → `_filter_session_bars()` returns zero bars on Railway | — | — |
| ⬜ | 14.H-6 | `app/data/candle_cache.py` | `is_cache_fresh()` stamps ET on UTC timestamp → stale cache appears fresh | — | — |
| ⬜ | 12.C-2 | `app/analytics/cooldown_tracker.py` | tz-aware vs naive timestamp — expired cooldowns never cleaned on Railway/Postgres | — | — |
| ⬜ | 43.M-9 | `app/signals/signal_generator_cooldown.py` | DELETE expired cooldowns on every read query — adds write load in hot path. Fix: scheduled cleanup task | — | — |
| ⬜ | 43.M-12 | `app/signals/signal_generator_cooldown.py` | `expires_at` uses `datetime.utcnow()` without explicit TZ in SQL — drift risk on TIMESTAMPTZ columns | — | — |

---

## Phase 3B — Import-Time Side Effects
> Prevents Railway cold-start crashes from import-time operations.

| Status | ID | File | Description | Commit SHA | Date |
|--------|----|------|-------------|------------|------|
| ⬜ | 39.H-1 | `app/core/sniper.py` | `_TICKER_WIN_CACHE = get_ticker_win_rates(days=30)` at module import — DB query before pool ready crashes on cold start. Fix: lazy init | — | — |
| ⬜ | 9.C-3 | `app/core/scanner.py` | Health server starts at module import before env validation | — | — |
| ⬜ | 44.H-1 | `utils/config.py` | `float(os.getenv(...))` raises `ValueError` at import if env var is non-numeric string. Fix: wrap in `try/except` | — | — |

---

## Phase 3C — Scan Cycle Performance
> Eliminates redundant work during the OR open hot path.

| Status | ID | File | Description | Commit SHA | Date |
|--------|----|------|-------------|------------|------|
| ⬜ | 42.H-1 | `app/filters/vwap_gate.py` | VWAP recomputed 3× per signal — compute once and pass as parameter | — | — |
| ⬜ | 41.H-5 | `app/mtf/mtf_fvg_priority.py` | `get_full_mtf_analysis()` makes 3 DB reads per call — accept `bars_1m` param, resample internally | — | — |
| ⬜ | 43.H-1 | `app/validation/greeks_precheck.py` | 50 live options chain fetches per cycle at OR open — add 60s TTL cache per ticker | — | — |
| ⬜ | 43.H-3 | `app/signals/signal_generator_cooldown.py` | `is_on_cooldown()` makes DB query on every call in hot path — add in-memory cache | — | — |
| ⬜ | 44.H-3 | `utils/production_helpers.py` | `_fetch_data_safe()` sleeps 1s per retry × 3 retries × 50 tickers = 150s dead time if all fail. Fix: max 0.5s total backoff | — | — |
| ⬜ | 39.H-3 | `app/core/sniper.py` | `_resample_bars()` redefined inside `_run_signal_pipeline()` on every call — move to module level | — | — |

---

## Phase 3D — Threading & Concurrency
> Ensures safe operation under concurrent ticker processing.

| Status | ID | File | Description | Commit SHA | Date |
|--------|----|------|-------------|------------|------|
| ⬜ | 9.C-1 | `app/core/scanner.py` | Single-worker watchdog executor — OR window scan loop serializes all tickers | — | — |
| ⬜ | 9.C-2 | `app/core/scanner.py` | Circuit breaker operator precedence bug — scanner may halt incorrectly | — | — |
| ⬜ | 10.C-1 | `app/risk/position_manager.py` | `datetime.now()` UTC — circuit breaker clears after midnight UTC (8 PM ET) | — | — |
| ⬜ | 10.C-2 | `app/risk/position_manager.py` | Dual timestamps for `exit_time` — positions vs ml_signals drift on DST | — | — |

---

## Phase 4A — Analytics & Tracking
> Restores signal quality measurement and funnel visibility.

| Status | ID | File | Description | Commit SHA | Date |
|--------|----|------|-------------|------------|------|
| ⬜ | 11.C-2 | `app/risk/dynamic_thresholds.py` | `trades` table doesn't exist — win-rate threshold adjustment has never fired | — | — |
| ⬜ | 11.C-3 | `app/risk/dynamic_thresholds.py` | `proposed_trades` table doesn't exist — quality adjustment has never fired | — | — |
| ⬜ | 10.C-4 | `app/risk/trade_calculator.py` | Stop above entry possible on bull A+ high-vol tight-OR — silent rejection | — | — |
| ⬜ | 45.H-3 | `app/core/sniper.py` | Screener stub always returns `qualified: False` — explosive mover override never fires, `rvol=0.0` on all trade records | — | — |
| ⬜ | 45.M-6 | `app/core/sniper.py` | `rvol=0.0` permanently corrupts performance analytics that depend on RVOL for signal quality attribution | — | — |

---

## Phase 4B — Options Layer Restoration
> Restores the options intelligence layer to functional state.

| Status | ID | File | Description | Commit SHA | Date |
|--------|----|------|-------------|------------|------|
| ✅ | 7.C-1 | `app/options/options_intelligence.py` | `get_chain()` always returns `None` — entire options layer is dark. Fix: restore live chain fetch via `OptionsFilter.get_options_chain()` | `c9f613f` | 2026-03-18 |
| ⬜ | 7.C-2 | `app/options/gex_engine.py` | GEX gamma_flip fallback selects wrong strike | — | — |
| ⬜ | 7.C-3 | `app/options/options_intelligence.py` | UOA score uses circular self-referential averages — fires on every contract | — | — |
| ⬜ | 16.H-7 | `app/data/unusual_options.py` | Cache key is ticker not (ticker, direction) — all PUT whale alerts return CALL data | — | — |
| ⬜ | 43.H-2 | `app/validation/greeks_precheck.py` | Strike selection uses current close not next-bar open — wrong strike validated | — | — |
| ⬜ | 43.M-11 | `app/validation/greeks_precheck.py` | Pre-check `options_data` used for multipliers instead of full validation result — more complete data discarded | — | — |

---

## Phase 4C — Notifications & Alerts
> Ensures Discord alerts are reliable and non-blocking.

| Status | ID | File | Description | Commit SHA | Date |
|--------|----|------|-------------|------------|------|
| ⬜ | 45.H-1 | `app/notifications/discord_helpers.py` | Synchronous HTTP POST in scan loop blocks ticker processing 100–500ms per send. Fix: fire-and-forget thread | — | — |
| ⬜ | 45.H-2 | `app/notifications/discord_helpers.py` | Webhook URL read on every call — raises TypeError if unset. Fix: cache at module load | — | — |
| ⬜ | 45.M-4 | `app/notifications/discord_helpers.py` | No rate limiting — 10 simultaneous signals → HTTP 429 from Discord | — | — |
| ⬜ | 45.M-5 | `app/notifications/discord_helpers.py` | No request timeout — can block indefinitely. Fix: `timeout=5` | — | — |
| ⬜ | 45.M-7 | `app/notifications/discord_helpers.py` | Messages over 2000 chars silently rejected (HTTP 400). Fix: truncate at 1900 chars | — | — |
| ⬜ | 45.M-10 | `app/notifications/discord_helpers.py` | Trade fires but Discord alert silently dropped on webhook failure — no fallback logging | — | — |

---

## Phase 4D — Screening Layer
> Restores dynamic watchlist generation.

| Status | ID | File | Description | Commit SHA | Date |
|--------|----|------|-------------|------------|------|
| ⬜ | 45.M-8 | `app/screening/` | Entire screening layer dark — no dynamic watchlist, static ticker list only | — | — |
| ⬜ | 45.M-11 | `app/screening/` | No RVOL/gap%/float filtering — War Machine scans same tickers regardless of which are moving | — | — |

---

## Phase 4E — Indicators & Technical Fixes

| Status | ID | File | Description | Commit SHA | Date |
|--------|----|------|-------------|------------|------|
| ⬜ | 6.B-9 | `app/indicators/technical_indicators_extended.py` | `check_volatility_expansion()` newest/oldest bar inversion | — | — |
| ⬜ | 6.B-7 | `app/indicators/technical_indicators_extended.py` | Daily ATR vs intraday move mismatch | — | — |
| ⬜ | 16.C-1 | `app/data/ws_feed.py` | Gate 3 dead code — multi-condition ticks with unknown leading code bypass INVALID_TRADE_CONDITIONS filter | — | — |
| ⬜ | 17.C-1 | `app/signals/breakout_detector.py` | `session_anchored` flag can mislabel entries using rolling resistance — Discord reason string wrong | — | — |

---

## Phase 5 — Code Quality & Hygiene
> DRY violations, dead code, naming, and logging cleanup.
> Fix these last — lowest risk, highest volume.

| Status | ID | File | Description | Commit SHA | Date |
|--------|----|------|-------------|------------|------|
| ⬜ | 43.H-4 | `app/signals/vwap_reclaim.py` | Duplicate VWAP implementation — should import from `vwap_gate.compute_vwap()` | — | — |
| ⬜ | 46.M-5 | `app/mtf/mtf_compression.py` | Three identical compression functions — consolidate to `compress_bars(bars, minutes)` | — | — |
| ⬜ | 40.L-14 | `app/mtf/bos_fvg_engine.py` | `c1` (middle candle) assigned but never used in `find_fvg_after_bos()` | — | — |
| ⬜ | 40.L-15 | `app/mtf/bos_fvg_engine.py` | `"dte": 0` hardcoded in `scan_bos_fvg()` return — dead field | — | — |
| ⬜ | 40.L-16 | `app/mtf/mtf_integration.py` | `compress_to_1m` imported but is identity transform on 1m input — effectively no-op | — | — |
| ⬜ | MULTI | ALL modules | ~40 import-time `print("[MODULE] ✅ ...")` statements — replace all with `logger.debug()` | — | — |
| ⬜ | 45.L-13 | `app/` | Legacy `app/discord_helpers.py` and current `app/notifications/discord_helpers.py` both exist — delete legacy | — | — |
| ⬜ | 44.L-14 | `utils/time_helpers.py` | `_now_et`, `_bar_time`, `_strip_tz` have `_` private prefix but are public utilities — rename | — | — |
| ⬜ | 46.L-10 | `app/mtf/mtf_compression.py` | No module docstring — critical given input resolution assumption (46.H-1) | — | — |
| ⬜ | 41.L-20 | `app/mtf/smc_engine.py` | `clear_smc_cache()` not called in EOD reset path — stale context persists across sessions | — | — |

---

## Progress Summary

| Phase | Total Findings | Fixed | Remaining |
|-------|---------------|-------|-----------|
| Phase 1 — Root Causes | 6 | 4 | 2 |
| Phase 2A — BOS/FVG Logic | 7 | 0 | 7 |
| Phase 2B — Confidence Gate | 4 | 0 | 4 |
| Phase 2C — Race Conditions | 5 | 0 | 5 |
| Phase 2D — Validation Logic | 6 | 0 | 6 |
| Phase 2E — OR/FVG Thresholds | 3 | 0 | 3 |
| Phase 3A — Database Safety | 7 | 0 | 7 |
| Phase 3B — Import-Time Side Effects | 3 | 0 | 3 |
| Phase 3C — Scan Cycle Performance | 6 | 0 | 6 |
| Phase 3D — Threading | 4 | 0 | 4 |
| Phase 4A — Analytics | 5 | 0 | 5 |
| Phase 4B — Options Layer | 6 | 1 | 5 |
| Phase 4C — Notifications | 6 | 0 | 6 |
| Phase 4D — Screening | 2 | 0 | 2 |
| Phase 4E — Indicators | 4 | 0 | 4 |
| Phase 5 — Code Quality | 10 | 0 | 10 |
| **TOTAL** | **84** | **4** | **80** |

> Note: 84 tracked findings represent the highest-priority subset of ~850 total audit findings.
> Lower-priority L-findings not listed above will be bundled into Phase 5 cleanup commits.

---

## Commit Log

| Date | Commit SHA | Files Changed | Findings Fixed |
|------|------------|---------------|----------------|
| 2026-03-18 | `5cee401` | `utils/time_helpers.py` | 44.H-2 — `_strip_tz()` ET conversion fix |
| 2026-03-18 | `409b5f6` | `app/validation/validation.py` | 8.C-1 — Direction normalization `bull/bear` → `BUY/SELL` |
| 2026-03-18 | `c9f613f` | `app/options/options_intelligence.py` | 7.C-1 — `get_chain()` wired to `OptionsFilter.get_options_chain()` |
| 2026-03-19 | `242a37a` | `app/data/db_connection.py` | 14.C-1 — Lazy pool init via `_init_pool()` with double-checked locking |

---

*Tracker maintained by Perplexity audit assistant. Update after every committed fix.*
