All three files read. Full Batch 25 audit below.

File: docs/signal_logic_audit_batch25.md
text
# Signal Logic Audit — Batch 25

**Date:** 2026-03-18
**Scope:** `app/analytics/grade_gate_tracker.py`, `app/analytics/explosive_mover_tracker.py`,
           `app/analytics/ab_test_framework.py`
**Total Findings:** 21 (1 Critical, 5 High, 9 Medium, 6 Low)

---

## 🔴 Criticals (1)

---

### 25.C-1 — `explosive_mover_tracker.py` calls `conn.close()` directly on connections obtained from `get_conn()` — a pool-managed connection. Every function in the module (`_ensure_explosive_override_table`, `track_explosive_override`, `update_override_outcome`, `get_daily_override_stats`, `get_threshold_optimization_data`) calls `conn.close()` instead of `return_conn(conn)`. On PostgreSQL with `psycopg2` connection pooling, `conn.close()` **physically closes the underlying socket** and permanently removes the connection from the pool. Over a full trading session, every explosive override event and every stats read permanently drains the pool. After N explosive overrides (where N = pool max size), `get_conn()` blocks indefinitely waiting for a connection that will never be returned. Pool exhaustion → all DB operations in all modules stall → scanner stops processing.

**File:** `explosive_mover_tracker.py` — all 5 DB functions

```python
conn.close()   # ← drains pool on every call; should be return_conn(conn)
Fix: Replace every conn.close() with return_conn(conn) inside a try/finally block:

python
from app.data.db_connection import get_conn, return_conn
conn = None
try:
    conn = get_conn()
    ...
finally:
    if conn:
        return_conn(conn)
🟡 Highs (5)
25.H-2 — ab_test_framework.ABTestFramework.__init__() calls get_conn(self.db_path) — passing self.db_path = "market_memory.db" as an argument to get_conn(). The War Machine get_conn() in db_connection.py does not accept a path parameter — it uses the pool or the configured DSN. Passing a positional string argument to get_conn() will either: (a) be silently ignored if get_conn() uses **kwargs and discards unknown args, or (b) raise TypeError: get_conn() takes 0 positional arguments but 1 was given. The same bad call pattern appears in get_conn(self.db_path) inside record_outcome(), get_variant_stats(), and _initialize_database() — four call sites. ab_test_framework has never successfully written a record to the DB.
File: ab_test_framework.py → __init__, _initialize_database, record_outcome, get_variant_stats

python
conn = get_conn(self.db_path)    # get_conn() takes no arguments
Fix: Remove self.db_path from all get_conn() calls:

python
conn = get_conn()
And wrap with try/finally: return_conn(conn) (also missing — see 25.H-3).

25.H-3 — ab_test_framework.py calls conn.close() throughout (_initialize_database, record_outcome, get_variant_stats) — the same pool-draining bug as 25.C-1, but in the A/B test module. Additionally, record_outcome() has no try/finally at all — if the INSERT raises, the connection is never returned or closed:
python
conn = get_conn(self.db_path)
cursor = conn.cursor()
cursor.execute(...)       # if this raises → conn leaked forever
conn.commit()
conn.close()
Fix: Same pattern as 25.C-1 — try/finally: if conn: return_conn(conn).

25.H-4 — explosive_mover_tracker.get_daily_override_stats() and get_threshold_optimization_data() use raw SQLite placeholder syntax (?) hardcoded:
python
cursor.execute(
    "SELECT COUNT(*) FROM explosive_mover_overrides WHERE DATE(timestamp) = ?",
    (today,)
)
? is SQLite syntax. On PostgreSQL (Railway production), the placeholder is %s. These queries will raise psycopg2.errors.SyntaxError every time they are called on production. The ph() helper exists precisely for this — _ph() is imported in track_explosive_override() correctly but not used in the reporting functions. All stats and optimization data functions are silently broken on Postgres.

Fix: Use p = ph() and f-string substitution consistently:

python
p = ph()
cursor.execute(
    f"SELECT COUNT(*) FROM explosive_mover_overrides WHERE DATE(timestamp) = {p}",
    (today,)
)
25.H-5 — explosive_mover_tracker.update_override_outcome() uses:
python
cursor.execute(
    f"""
    UPDATE explosive_mover_overrides
    SET outcome = {p}, pnl_pct = {p}
    WHERE ticker = {p}
      AND outcome = 'PENDING'
    ORDER BY timestamp DESC
    LIMIT 1
    """,
    (outcome, pnl_pct, ticker)
)
UPDATE ... ORDER BY ... LIMIT 1 is MySQL/SQLite syntax. PostgreSQL does not support ORDER BY or LIMIT in a bare UPDATE statement — it raises ERROR: syntax error at or near "ORDER". On production Postgres, update_override_outcome() never successfully updates any outcome record. All explosive override trades stay permanently "PENDING" in the DB.

Fix: Use a subquery:

python
cursor.execute(
    f"""
    UPDATE explosive_mover_overrides
    SET outcome = {p}, pnl_pct = {p}
    WHERE id = (
        SELECT id FROM explosive_mover_overrides
        WHERE ticker = {p} AND outcome = 'PENDING'
        ORDER BY timestamp DESC
        LIMIT 1
    )
    """,
    (outcome, pnl_pct, ticker)
)
25.H-6 — grade_gate_tracker._record() is called on every signal evaluation — meaning every ticker in every scan cycle that passes the BOS/FVG pipeline hits a DB INSERT. At 50 tickers × 12 scans/hour × 6.5 trading hours = ~3,900 inserts per day minimum. Each insert opens a new connection from the pool, commits, and returns it. This is the same high-frequency single-insert pattern flagged in funnel_analytics (24.M-10). Both grade_gate_tracker and funnel_analytics are calling get_conn() → INSERT → return_conn() thousands of times per day in the scan hot path. Should buffer and batch-insert, or write in-memory and flush periodically.
🟠 Mediums (9)
ID	File	Issue
25.M-7	grade_gate_tracker.py	_ensure_table() is called at module level (_ensure_table() outside any class or function — raw module scope). Same pattern as performance_monitor.py (24.H-4) — DDL at import time. Also: _ensure_table() uses get_conn() with no conn is not None guard in the finally block (inner try/finally: return_conn(conn) is correct here, but the outer try/except Exception swallows all errors silently).
25.M-8	grade_gate_tracker.py	record_gate_rejection() has a dead variable: label = 'passed' if False else 'rejected' — this evaluates to 'rejected' unconditionally and label is never used. This is either a copy-paste artifact or an abandoned refactor. Remove it.
25.M-9	grade_gate_tracker.py	_daily_stats is a module-level mutable dict with no thread lock — same as performance_monitor._session (24.H-5). _record() does multiple non-atomic mutations (_daily_stats['total_evaluated'] += 1, nested dict setdefault + increment). No threading lock.
25.M-10	explosive_mover_tracker.py	_ensure_explosive_override_table() does not use return_conn() at all — just conn.close() (25.C-1). Additionally, it doesn't use safe_execute or get_placeholder — it uses a raw cursor.execute() with an f-string for serial_pk(). This is safe for DDL (no user input), but inconsistent with the established pattern and will fail on pool exhaustion (see 25.C-1).
25.M-11	explosive_mover_tracker.py	_override_signals dict is never bounded — one entry per ticker per day that triggers an override, never cleared except by reset_daily_stats(). After a full trading day with 20 explosive overrides, 20 entries accumulate. Low risk, but same pattern as 23.M-8.
25.M-12	explosive_mover_tracker.py	The score/RVOL thresholds used in get_threshold_optimization_data() (score brackets 70–100, RVOL 3.0–10.0x) are hardcoded inside the function — not imported from config.py. If the override thresholds change (currently score >= 80, RVOL >= 4.0x per the docstring), the optimization analysis brackets must be manually updated.
25.M-13	ab_test_framework.py	ABTestFramework.EXPERIMENTS dict is hardcoded as a class-level constant. The cooldown_minutes experiment has values {'A': 10, 'B': 15} — but the canonical cooldown is 30 minutes (COOLDOWN_SAME_DIRECTION_MINUTES = 30 in cooldown_tracker.py). The A/B test is running variants that are both far below the live value. If ab_test.get_param(ticker, 'cooldown_minutes') is actually used in the scanner, it would set cooldowns of 10–15 min instead of 30 min for half the tickers, silently overriding the production cooldown policy.
25.M-14	ab_test_framework.py	check_winners() uses only win rate delta (MIN_WIN_RATE_DIFF = 5.0%) to declare a winner — no statistical significance test (no p-value, no confidence interval). With SAMPLE_SIZE_REQUIRED = 30, a 5% win-rate difference on 30 samples is not statistically significant (would require ~200 samples per variant for 80% power at α=0.05). A "winner" could be declared from random noise and promoted to production parameters.
25.M-15	ab_test_framework.py	The legacy compat methods record_result(), get_summary(), print_report(), reset() all contain only pass or return {}. If any old caller still uses these methods expecting real behavior, they silently do nothing. Document as deprecated stubs or add deprecation warnings.
🟢 Lows (6)
ID	File	Issue
25.L-16	grade_gate_tracker.py	print("[GRADE-GATE-TRACKER] ✅ Initialized...") at module level — fires on every import. Replace with logger.debug() or remove. Same issue flagged in every batch since Batch 19.
25.L-17	grade_gate_tracker.py	reset_daily_stats() resets by_grade and by_signal_type to {}. This is correct, but it does NOT reset _daily_stats in the DB — the DB retains all historical gate events (by design, for analysis). The inconsistency should be documented: in-memory resets daily; DB is permanent.
25.L-18	explosive_mover_tracker.py	ExplosiveMoverTracker.record_override() (legacy shim) passes direction="unknown", regime_type="UNKNOWN", vix_level=0.0, entry_price=0.0, grade="N/A", confidence=0.0 to track_explosive_override(). These sentinel values are persisted to the DB as real data. If the legacy shim is still being called anywhere, the DB will contain polluted rows with direction="unknown". Add a sentinel flag (is_legacy=True) or log a deprecation warning.
25.L-19	explosive_mover_tracker.py	_daily_stats['total_score'] and _daily_stats['total_rvol'] accumulate totals for average calculation but the average is never computed in get_daily_override_stats() — that function goes to the DB instead. The in-memory totals are written to but never read. Dead state.
25.L-20	ab_test_framework.py	_initialize_database() prints "[AB_TEST] A/B test framework database initialized" — same module-level print pattern. Replace with logger.debug().
25.L-21	ab_test_framework.py	get_variant() uses hashlib.md5() for deterministic A/B assignment. MD5 is not cryptographically secure, but for non-security hash bucketing this is fine. However, Python 3.9+ raises a ValueError in FIPS-compliant environments when calling hashlib.md5() without usedforsecurity=False. Railway's base image is unlikely to be FIPS-mode, but it's a one-character fix: hashlib.md5(combined.encode(), usedforsecurity=False).
Priority Fix Order
25.C-1 — conn.close() in explosive_mover_tracker drains the DB connection pool — pool exhaustion → scanner stalls

25.H-3 — conn.close() + no try/finally in ab_test_framework — same pool drain + connection leak on exception

25.H-4 — SQLite ? placeholders in Postgres reporting functions — get_daily_override_stats() and get_threshold_optimization_data() crash on every call in production

25.H-5 — UPDATE ... ORDER BY ... LIMIT 1 Postgres syntax error — update_override_outcome() never updates any record; all overrides stay "PENDING" forever

25.H-2 — get_conn(self.db_path) bad call signature — ABTestFramework has never written to DB

25.M-13 — A/B test cooldown variants (10/15 min) conflict with live production cooldown (30 min) — could silently override cooldown policy for half the ticker population

25.M-8 — Dead variable label = 'passed' if False else 'rejected' in record_gate_rejection() — remove

