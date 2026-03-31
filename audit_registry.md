# WAR MACHINE — AUDIT REGISTRY
> **Purpose:** Single source of truth for the line-by-line file audit.  
> Every bug found, fix applied, and architectural decision is logged here permanently.  
> Updated after every commit. Never delete entries — append only.

---

## AUDIT RULES
- Files audited one at a time, line by line
- Every finding gets a unique ID: `BUG-<ABBREV>-<N>` (e.g. `BUG-ASS-1`)
- Severity: `CRITICAL` (runtime crash) | `HIGH` (silent wrong behavior) | `LOW` (cosmetic/style)
- Status: `OPEN` | `FIXED` | `WONTFIX`
- GitHub 100 KB pull limit — no single fetch may exceed 100 KB
- All commits documented below in the **COMMIT LOG** section

---

## MASTER FILE INDEX

| # | File | Path | Size (approx) | Status | Last Audited |
|---|------|------|---------------|--------|--------------|
| 1 | `armed_signal_store.py` | `app/state/armed_signal_store.py` | ~14 KB | ⚠️ 2 open bugs | 2026-03-31 |
| 2 | `watch_signal_store.py` | `app/state/watch_signal_store.py` | ~14 KB | ⚠️ 3 open bugs | 2026-03-31 |
| 3 | `position_manager.py` | `app/risk/position_manager.py` | ~48 KB | ⚠️ 2 open bugs | 2026-03-31 |
| 4 | `position_helpers.py` | `app/risk/position_helpers.py` | TBD | 🔲 Queued | — |
| 5 | `vix_sizing.py` | `app/risk/vix_sizing.py` | TBD | 🔲 Queued | — |
| 6 | `rth_filter.py` | `app/filters/rth_filter.py` | TBD | 🔲 Queued | — |
| 7 | `db_connection.py` | `app/data/db_connection.py` | TBD | 🔲 Queued | — |
| 8 | `sql_safe.py` | `app/data/sql_safe.py` | TBD | 🔲 Queued | — |
| 9 | `signal_analytics.py` | `app/signals/signal_analytics.py` | TBD | 🔲 Queued | — |
| 10 | `sniper.py` | `app/signals/sniper.py` | TBD | 🔲 Queued | — |
| 11 | `discord_helpers.py` | `app/notifications/discord_helpers.py` | TBD | 🔲 Queued | — |
| 12 | `ai_learning.py` | `app/ai/ai_learning.py` | TBD | 🔲 Queued | — |
| 13 | `config.py` | `utils/config.py` | TBD | 🔲 Queued | — |
| 14 | `main.py` / entry point | (root or app/) | TBD | 🔲 Queued | — |
| 15 | All `__init__.py` files | various | TBD | 🔲 Queued | — |
| 16 | `requirements.txt` | `/requirements.txt` | ~400 B | 🔲 Queued | — |
| 17 | `railway.toml` | `/railway.toml` | ~366 B | 🔲 Queued | — |
| 18 | `nixpacks.toml` | `/nixpacks.toml` | ~246 B | 🔲 Queued | — |
| 19 | `pytest.ini` | `/pytest.ini` | ~698 B | 🔲 Queued | — |
| 20 | All test files | `tests/` | TBD | 🔲 Queued | — |
| 21 | All migration files | `migrations/` | TBD | 🔲 Queued | — |

> **Legend:** ✅ = Audited clean or all findings fixed | ⚠️ = Audited, open findings | 🔲 = Not yet audited

---

## BUG REGISTRY

### SESSION 1 — 2026-03-31
**Files:** `armed_signal_store.py`, `watch_signal_store.py`, `position_manager.py`

---

#### BUG-ASS-1
| Field | Value |
|-------|-------|
| **File** | `app/state/armed_signal_store.py` |
| **Severity** | LOW |
| **Status** | OPEN |
| **Line(s)** | ~8–12 (import block) |
| **Description** | `import logging` is the last import in the block but `logger = logging.getLogger(__name__)` immediately follows it inline. Order is syntactically valid but inconsistent with the rest of the codebase style (all other files place `import logging` near the top of the import block, before `from datetime`, `from zoneinfo`, and `from app.*` imports). Non-crashing. Cosmetic/style. |
| **Fix** | Move `import logging` to the top of the import block, immediately after `from utils import config` (or as first stdlib import). |
| **Committed** | No |

---

#### BUG-ASS-2
| Field | Value |
|-------|-------|
| **File** | `app/state/armed_signal_store.py` |
| **Severity** | LOW |
| **Status** | OPEN |
| **Line(s)** | Inside `clear_armed_signals()` function body |
| **Description** | `from app.data.sql_safe import safe_execute` is re-imported inside the function body. `safe_execute` is already imported at module scope (`from app.data.sql_safe import safe_execute, ...`). The inner import is redundant — it is non-crashing (Python deduplicates imports) but misleading: it implies `safe_execute` is not available at module scope, which it is. Could confuse future readers or tools. |
| **Fix** | Remove the inner `from app.data.sql_safe import safe_execute` from inside `clear_armed_signals()`. |
| **Committed** | No |

---

#### BUG-WSS-1
| Field | Value |
|-------|-------|
| **File** | `app/state/watch_signal_store.py` |
| **Severity** | LOW |
| **Status** | OPEN |
| **Line(s)** | All `except` blocks in: `_ensure_watch_db()`, `_persist_watch()`, `_remove_watch_from_db()`, `_cleanup_stale_watches()`, `_load_watches_from_db()`, `send_bos_watch_alert()`, `clear_watching_signals()` |
| **Description** | All error-path `except` blocks log at `logger.info` level. The equivalent file `armed_signal_store.py` was previously upgraded so all error paths use `logger.warning`. Errors in `watch_signal_store.py` are invisible in production where the log level is typically WARNING or above. Silent failures. |
| **Fix** | Change all `logger.info(f"[WATCH-DB]... error: {e}")` calls in `except` blocks to `logger.warning(...)`. |
| **Committed** | No |

---

#### BUG-WSS-2
| Field | Value |
|-------|-------|
| **File** | `app/state/watch_signal_store.py` |
| **Severity** | LOW |
| **Status** | OPEN |
| **Line(s)** | `_load_watches_from_db()`, approximately line 140 |
| **Description** | `print(f"[WATCH-DB] 📄 Reloaded {len(loaded)} watch state(s)...")` uses a raw `print()` instead of `logger.info()`. `armed_signal_store.py` had the same issue fixed in a prior session. In Railway deployment, print output goes to stdout but bypasses the logging subsystem — no timestamps, no log level, no handler routing. |
| **Fix** | Replace `print(...)` with `logger.info(...)` on that line. |
| **Committed** | No |

---

#### BUG-WSS-3
| Field | Value |
|-------|-------|
| **File** | `app/state/watch_signal_store.py` |
| **Severity** | LOW |
| **Status** | OPEN |
| **Line(s)** | `clear_watching_signals()` function body |
| **Description** | `safe_execute(cursor, "DELETE FROM watching_signals_persist", ())` passes an empty tuple `()` as the params argument. The equivalent call in `armed_signal_store.py`'s `clear_armed_signals()` passes no params argument at all. Minor cosmetic inconsistency between two parallel files that should mirror each other exactly. |
| **Fix** | Remove the trailing `()` params argument: `safe_execute(cursor, "DELETE FROM watching_signals_persist")`. Confirm `safe_execute` handles missing params (default to `None` or `()`). |
| **Committed** | No |

---

#### BUG-PM-4
| Field | Value |
|-------|-------|
| **File** | `app/risk/position_manager.py` |
| **Severity** | LOW |
| **Status** | OPEN |
| **Line(s)** | `open_position()` — rejected position log lines (2 occurrences) |
| **Description** | When a position is rejected (bad R:R or risk limit breach), the rejection logs use `logger.info`. Position rejections are operationally significant — they mean the system silently skipped a trade signal. They should be `logger.warning` so they appear in production logs regardless of log level configuration. |
| **Fix** | Change the two `logger.info(f"[RISK] ❌ ...")` rejection lines in `open_position()` to `logger.warning(...)`. |
| **Committed** | No |

---

#### BUG-PM-5
| Field | Value |
|-------|-------|
| **File** | `app/risk/position_manager.py` |
| **Severity** | LOW |
| **Status** | OPEN |
| **Line(s)** | `close_position()` — circuit breaker trigger log block (~line 470) |
| **Description** | Circuit breaker trigger event uses `logger.info` for both the trigger message and the "no new positions" notice. This is the most critical risk event in the system — a daily loss limit breach. It must be visible in production at WARNING level at minimum. |
| **Fix** | Change both circuit breaker trigger log lines in `close_position()` from `logger.info` to `logger.warning`. |
| **Committed** | No |

---

### PRIOR BUG HISTORY (pre-audit, already fixed)

The following bugs were fixed prior to this audit session and are documented here for completeness. All confirmed resolved during the Session 1 audit.

| ID | File | Fix Summary | Fixed Date |
|----|------|-------------|------------|
| PHASE C1 | `position_manager.py` | `_load_session_state()` now re-populates `self.positions` from DB on startup | 2026-03-10 |
| FIX M5 | `position_manager.py` | `close_all_eod()` resets streak counters after EOD close | 2026-03-10 |
| FIX #4 | `position_manager.py` | `close_position()` calls `_write_completed_at()` after every real close | 2026-03-11 |
| FIX #5 | `position_manager.py` | 10s TTL cache on `get_daily_stats()` and `get_open_positions()` | 2026-03-13 |
| FIX #6 | `position_manager.py` | `_check_risk_limits()` testable wrapper around `can_open_position()` | 2026-03-14 |
| FIX #7 | `position_manager.py` | Python 3.10 f-string backslash compat in `get_risk_summary()` | 2026-03-14 |
| FIX #8 | `position_manager.py` | `close_position()` circuit-breaker check uses real session P&L | 2026-03-15 |
| FIX #9 | `position_manager.py` | `check_exits()` re-reads `t1_hit` from DB after `_scale_out()` | 2026-03-15 |
| FIX #10 | `position_manager.py` | Unicode surrogate pair fix for rotate/siren emojis | 2026-03-16 |
| FIX #11 | `position_manager.py` | SQLite AT TIME ZONE crash fix via `_date_eq_today` / `_date_lt_today` helpers | 2026-03-19 |
| FIX #12 | `position_manager.py` | Corrected RTH import path and function name | 2026-03-25 |
| FIX #13 | `position_manager.py` | `get_win_rate()` uses `_date_col()` for range queries | 2026-03-26 |
| BUG-PM-1 | `position_manager.py` | `generate_report()` uses live `current_balance` not stale `self.account_size` | 2026-03-30 |
| BUG-PM-2 | `position_helpers.py` | Clarifying docstrings on `_date_col()` vs `_date_eq_today()` | 2026-03-30 |
| BUG-PM-3 | `position_manager.py` | `calculate_position_size()` logs when odd contract count is bumped to even | 2026-03-30 |

---

## ARCHITECTURAL NOTES

### Import Order Standard
All files should follow this import order (established by `position_manager.py` as the reference):
1. `from utils import config` (project config always first)
2. stdlib: `from datetime import ...`, `from zoneinfo import ...`, `import logging`, `import time`, etc.
3. `logger = logging.getLogger(__name__)` immediately after `import logging`
4. `from typing import ...`
5. `from app.*` imports
6. Optional dependency `try/except` blocks (VIX, RTH, signal tracking, etc.)

### Log Level Standard
| Event Type | Required Level |
|-----------|----------------|
| Normal operational info (loaded, opened, closed) | `logger.info` |
| Position rejection (R:R, risk limits) | `logger.warning` |
| DB or external service errors | `logger.warning` |
| Circuit breaker trigger | `logger.warning` (minimum) |
| Unrecoverable startup errors | `logger.error` |

### DB Connection Pattern
All DB access must follow:
```python
conn = None
try:
    conn = get_conn()
    cursor = dict_cursor(conn)  # or conn.cursor() for DDL
    # ... work ...
    conn.commit()
finally:
    if conn:
        return_conn(conn)
```
No exceptions. No bare `conn = get_conn()` outside a try/finally.

### Dual-Dialect SQL Pattern
All date comparisons must use helpers from `position_helpers.py`:
- `_date_col("col")` — for range queries (`>=`, `<=`, `BETWEEN`)
- `_date_eq_today("col")` — for equality (`= today`)
- `_date_lt_today("col")` — for `< today` (stale position detection)
Never use raw `DATE(col)` or `col::date` — breaks cross-dialect compatibility.

### Cache Invalidation Pattern
Any method that writes to the DB must call `self._invalidate_caches()` immediately after `conn.commit()`. This is enforced in `position_manager.py`. Any future file that wraps `position_manager` must NOT maintain its own position cache.

### Parallel File Consistency Rule
`armed_signal_store.py` and `watch_signal_store.py` are parallel files that must mirror each other exactly in structure, log levels, error handling patterns, and import style. Any change to one must be reviewed against the other.

---

## COMMIT LOG

| # | Date | SHA | Files Changed | Description |
|---|------|-----|---------------|-------------|
| 1 | 2026-03-31 | (pending) | `audit_registry.md` | Initial creation. Session 1 complete: 3 files audited, 7 open bugs found (BUG-ASS-1, BUG-ASS-2, BUG-WSS-1, BUG-WSS-2, BUG-WSS-3, BUG-PM-4, BUG-PM-5). All LOW severity, non-crashing. |

---

## OPEN ITEMS QUEUE

> All items to fix in next commit batch (all LOW severity, non-crashing):

| ID | File | Fix Required |
|----|------|--------------|
| BUG-ASS-1 | `armed_signal_store.py` | Move `import logging` to top of import block |
| BUG-ASS-2 | `armed_signal_store.py` | Remove redundant inner `from app.data.sql_safe import safe_execute` from `clear_armed_signals()` |
| BUG-WSS-1 | `watch_signal_store.py` | Change all error-path `logger.info` → `logger.warning` in `except` blocks |
| BUG-WSS-2 | `watch_signal_store.py` | Replace `print(...)` with `logger.info(...)` in `_load_watches_from_db()` |
| BUG-WSS-3 | `watch_signal_store.py` | Remove trailing `()` from `safe_execute` call in `clear_watching_signals()` |
| BUG-PM-4 | `position_manager.py` | Change position rejection `logger.info` → `logger.warning` in `open_position()` |
| BUG-PM-5 | `position_manager.py` | Change circuit breaker trigger `logger.info` → `logger.warning` in `close_position()` |

---

## NEXT AUDIT QUEUE

> Files to audit next, in priority order:

1. `app/risk/position_helpers.py` — helpers used by position_manager; verify `_date_col`, `_date_eq_today`, `_date_lt_today`, `_write_completed_at`, `SECTOR_GROUPS`, cache TTL constants
2. `app/data/db_connection.py` — foundational; `get_conn`, `return_conn`, `ph`, `dict_cursor`, `serial_pk`, `USE_POSTGRES`
3. `app/data/sql_safe.py` — `safe_execute`, `safe_in_clause`; used everywhere
4. `app/risk/vix_sizing.py` — `get_vix_multiplier`; verify fallback behavior
5. `app/filters/rth_filter.py` — `is_rth`; verify correct RTH window
6. `app/signals/sniper.py` — largest signal file; audit last due to size
7. `app/signals/signal_analytics.py` — `signal_tracker.record_trade_executed`
8. `app/notifications/discord_helpers.py` — `send_scaling_alert`, `send_exit_alert`, `send_simple_message`
9. `app/ai/ai_learning.py` — `learning_engine.record_trade`
10. `utils/config.py` — all constants used across the codebase
11. All `tests/` files
12. Root config files: `requirements.txt`, `railway.toml`, `nixpacks.toml`, `pytest.ini`
