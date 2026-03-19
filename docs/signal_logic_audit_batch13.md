# Signal Logic Audit — Batch 13

**Date:** 2026-03-18
**Scope:** `app/analytics/funnel_analytics.py`, `app/analytics/explosive_mover_tracker.py`, `app/analytics/ab_test_framework.py`
**Total Findings:** 16 (2 Critical, 5 High, 5 Medium, 4 Low)

---

## 🔴 Criticals (2)

---

### 13.C-1 — `explosive_mover_tracker` uses `conn.close()` instead of `return_conn()` — leaks pooled connections
**File:** `explosive_mover_tracker.py`

```python
conn = get_conn()
cursor = conn.cursor()
...
conn.commit()
conn.close()   # ← closes the socket; does NOT return to pool
Every function in this module — _ensure_explosive_override_table(), track_explosive_override(), update_override_outcome(), get_daily_override_stats(), get_threshold_optimization_data() — calls conn.close() directly instead of return_conn(conn). In the connection pool (db_connection.py), return_conn() is the correct way to release a connection back to the pool. conn.close() hard-closes the underlying socket, permanently shrinking the pool by 1 per call. Over a session with 30 tickers × hourly explosive override checks, this can exhaust the pool entirely, causing get_conn() to block or raise PoolExhausted. Additionally, none of these uses have a try/finally guard — any exception before conn.close() leaks the connection permanently.

Fix: Replace all conn.close() with return_conn(conn) inside try/finally blocks, matching the pattern used in cooldown_tracker.py.

13.C-2 — ABTestFramework._initialize_database() passes db_path to get_conn() — get_conn() takes no positional argument
File: ab_test_framework.py

python
def __init__(self, db_path: str = "market_memory.db"):
    self.db_path = db_path
    self._initialize_database()

def _initialize_database(self):
    conn = get_conn(self.db_path)   # ← get_conn() signature: get_conn() → Connection
get_conn() in db_connection.py takes no arguments — it connects to the Railway DATABASE_URL pool. Passing self.db_path raises TypeError: get_conn() takes 0 positional arguments but 1 was given on the first import. The ab_test = ABTestFramework() singleton at module level means this TypeError fires at import time on every Railway startup, crashing any module that imports ab_test_framework. Because the exception is not caught, any scanner.py import chain that includes this module will fail to start entirely.

Fix: Remove the db_path parameter — it's a legacy SQLite artifact. Call get_conn() with no arguments, exactly like every other module in the codebase.

🟡 Highs (5)
13.H-3 — FunnelTracker._initialize_database() called in __init__() at module import — DB connection on import before env validation
File: funnel_analytics.py

python
class FunnelTracker:
    def __init__(self):
        self._initialize_database()  # ← DB connect at import time

funnel_tracker = FunnelTracker()     # ← instantiated at module scope
Same pattern as 10.H-10, 12.H-7. _initialize_database() calls get_conn() synchronously at module import, before DATABASE_URL is validated. Additionally, _initialize_database() creates three schema objects (one table + two indexes) on every startup — even when the table already exists. While CREATE TABLE IF NOT EXISTS is safe, the double index creation adds unnecessary DDL round-trips on every Railway cold start.

Fix: Lazy-init via _initialized flag, same as recommended in Batches 10 and 12.

13.H-4 — get_daily_report() calls get_stage_conversion() in a loop — 7 separate DB queries for one report
File: funnel_analytics.py

python
for stage in self.STAGES:   # 7 iterations
    stats = self.get_stage_conversion(stage, session)   # 1 DB query each
get_daily_report() makes 7 sequential DB round-trips — one per stage — to build a single report. Each get_stage_conversion() opens a connection from the pool, executes a SELECT COUNT with GROUP BY effectively computed inline, then returns the connection. At 5ms/query this is 35ms of DB overhead for a display-only function called every ~5 minutes. More importantly, each call also opens and returns a connection, creating 7 pool checkout/return cycles.

Fix: Replace with a single aggregated query:

sql
SELECT stage,
       COUNT(*) AS total,
       SUM(CASE WHEN passed = 1 THEN 1 ELSE 0 END) AS passed,
       SUM(CASE WHEN passed = 0 THEN 1 ELSE 0 END) AS failed
FROM funnel_events
WHERE session = %s
GROUP BY stage
Build the report dict in Python from the single result set.

13.H-5 — update_override_outcome() uses ORDER BY timestamp DESC LIMIT 1 in an UPDATE — not valid on Postgres
File: explosive_mover_tracker.py

python
cursor.execute(f"""
    UPDATE explosive_mover_overrides
    SET outcome = {p}, pnl_pct = {p}
    WHERE ticker = {p}
      AND outcome = 'PENDING'
    ORDER BY timestamp DESC
    LIMIT 1
""", (outcome, pnl_pct, ticker))
ORDER BY and LIMIT in a UPDATE statement is a SQLite extension. Postgres does not support it — this raises SyntaxError on Railway. If a ticker has multiple PENDING rows (e.g., same ticker traded twice intraday), this UPDATE is also logically ambiguous on SQLite: it will update the most recent PENDING row, but there's no guarantee of ordering without an explicit ORDER BY id DESC subquery.

Fix: Use a subquery:

sql
UPDATE explosive_mover_overrides
SET outcome = %s, pnl_pct = %s
WHERE id = (
    SELECT id FROM explosive_mover_overrides
    WHERE ticker = %s AND outcome = 'PENDING'
    ORDER BY timestamp DESC
    LIMIT 1
)
13.H-6 — get_daily_override_stats() and get_threshold_optimization_data() use SQLite ? placeholders — break on Postgres
File: explosive_mover_tracker.py

python
cursor.execute(
    "SELECT COUNT(*) FROM explosive_mover_overrides WHERE DATE(timestamp) = ?",
    (today,)
)
All queries in these two functions use hardcoded ? instead of ph(). Same issue as 11.H-8. On Railway (Postgres), these raise ProgrammingError. These functions are used in EOD reporting and threshold optimization analysis — both will silently fail on every Railway deploy.

Fix: Use p = ph() and f-string substitution consistently, matching the pattern in track_explosive_override() which already uses _ph() correctly.

13.H-7 — ABTestFramework.get_param() is not called anywhere in the codebase — A/B test is entirely passive
File: ab_test_framework.py

ab_test.get_param(ticker, param) should be called at each decision point (volume threshold check, confidence gate, cooldown check, ATR stop calculation) to return the variant value. A search of the codebase shows ab_test.get_param() is never called. The A/B test framework records outcomes via ab_test.record_outcome() (also never called), determines winners via check_winners() (never called), but never actually varies any parameters. All tickers receive the same production values regardless of their assigned variant. The framework has been built but never wired in.

This is not a bug — it's unfinished integration. Flag for implementation roadmap.

🟠 Mediums (5)
ID	File	Issue
13.M-8	funnel_analytics.py	_reset_daily_if_needed() compares today != self.last_reset using datetime.now(ET).date(). On a Railway restart mid-session, self.last_reset is re-initialized to today in __init__. This correctly re-queries DB for the current session. However, daily_counters and rejection_counts are reset to empty — they are not re-loaded from DB. The in-memory counters will under-count for the remainder of the session after any restart.
13.M-9	ab_test_framework.py	_hash_ticker_date() uses hashlib.md5() for variant assignment. MD5 produces uniform hex output but the truncation int(hash_val[:8], 16) % 2 only uses the first 8 hex chars (32 bits). For the 30-ticker watchlist, the 32-bit hash space is more than sufficient for collision-free assignment, but MD5 is deprecated for security use. Use hashlib.sha256() and document that this is for deterministic bucketing, not security.
13.M-10	explosive_mover_tracker.py	_daily_stats['total_score'] and _daily_stats['total_rvol'] accumulate across the session for average calculation, but get_daily_override_stats() queries the DB for AVG(score) and AVG(rvol) instead of using these accumulators. The in-memory totals are written to but never read. Dead accumulators — remove them or use them.
13.M-11	funnel_analytics.py	get_daily_report() calculates from_prev_pct as stats['passed'] / prev_passed * 100 — the conversion rate to the next stage from the previous stage's passed count. But it formats this as f"({from_prev_pct:>5.1f}% of {STAGES[index-1]})" using self.STAGES.index(stage) - 1. Calling .index() inside a loop on a list is O(n) per iteration. With 7 stages this is trivial, but replace with enumerate(self.STAGES) for clarity.
13.M-12	ab_test_framework.py	record_result(), get_summary(), print_report(), and reset() are defined as no-ops (pass or return {}) labeled "Legacy compat methods". These are dead stubs that appear in the public API but do nothing. If they are truly deprecated, add a deprecation warning; if needed, implement them properly.
🟢 Lows (4)
ID	File	Issue
13.L-13	funnel_analytics.py	print("[FUNNEL] Funnel analytics database initialized") fires at module import via FunnelTracker.__init__(). Move to lazy init.
13.L-14	ab_test_framework.py	print("[AB_TEST] A/B test framework database initialized") fires at module import. Same fix.
13.L-15	explosive_mover_tracker.py	ExplosiveMoverTracker.record_override() passes direction="unknown", grade="N/A", confidence=0.0 to track_explosive_override(). These placeholder values pollute the explosive_mover_overrides table and skew AVG(confidence) in get_daily_override_stats(). The legacy shim should either be removed or accept the missing fields as optional with NULL defaults.
13.L-16	All three files	All print() calls should be logger.*. Same pattern flagged in batches 8–12.
Priority Fix Order
13.C-2 — get_conn(db_path) call raises TypeError at import — crashes entire import chain on Railway

13.C-1 — conn.close() throughout explosive_mover_tracker — pool exhaustion over session

13.H-5 — ORDER BY / LIMIT in UPDATE — Postgres syntax error on Railway

13.H-6 — SQLite ? placeholders in reporting functions — break on Postgres

13.H-4 — 7 sequential DB queries per report — consolidate to single query

13.H-3 — FunnelTracker DB init at import — blocks env validation

13.H-7 — A/B test parameters never actually varied — wire get_param() into decision points