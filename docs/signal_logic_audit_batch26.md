All three files read. Full Batch 26 audit below.

File: docs/signal_logic_audit_batch26.md
text
# Signal Logic Audit — Batch 26

**Date:** 2026-03-18
**Scope:** `app/data/db_connection.py`, `app/data/sql_safe.py`, `app/data/database.py`
           (directory listing also catalogued for future batches)
**Total Findings:** 18 (0 Critical, 4 High, 8 Medium, 6 Low)

---

## 🔴 Criticals (0)

Clean. No critical findings. The core pool machinery is well-engineered — the FIX #7 and FIX #8 comments show active hardening. No data-loss or pool-drain bugs in the DB layer itself.

---

## 🟡 Highs (4)

---

### 26.H-1 — `get_conn()` docstring says **"Caller must close the connection when done! Better to use `with get_connection() as conn:`"** — yet the recommended pattern throughout the entire codebase (Batches 17–25) is `get_conn()` / `return_conn()`, not `get_connection()`. The `get_connection()` context manager exists and is correct, but **zero modules in `app/analytics/`, `app/signal/`, or `app/orders/` use it**. Every module manually calls `get_conn()` + `finally: return_conn(conn)` — sometimes forgetting the `finally` (25.H-3), sometimes forgetting the `if conn:` guard (24.H-1). The safer pattern is literally built into the module but never adopted. The docstring should say: **use `get_connection()` context manager everywhere; `get_conn()` / `return_conn()` is internal API only**. Better still: deprecate `get_conn()` as public API and enforce `get_connection()` for all callers. This is the root cause of the entire class of connection-leak and double-release bugs across 9 prior batches.

---

### 26.H-2 — `check_pool_health()` computes "leaked" connections as `checkouts - returns`. This is a cumulative lifetime counter, not a snapshot of currently-checked-out connections. After 10,000 checkouts and 9,997 returns (3 legitimately in-flight), `leaked = 3` — that looks fine. But after 10,000 checkouts and 9,995 returns (where 5 were leaked via `conn.close()` from `explosive_mover_tracker`), `leaked = 5` — exactly at the threshold where the health check says `"healthy": True` (condition is `leaked < 5`). So a system that has leaked exactly 5 connections is still marked healthy. The threshold should be `<= 2` or the metric should be "currently checked out" (which is `len(_checked_out_connections)`, already computed as `checked_out_copy`) not the cumulative delta. The `_checked_out_connections` dict is the correct source for in-flight count — use it.

---

### 26.H-3 — `force_close_stale_connections()` calls `_db_semaphore.release()` **for every stale entry cleared from `_checked_out_connections`** — but these connections were obtained via `conn.close()` (as in `explosive_mover_tracker`) and their semaphore slots were never returned at close time. So `force_close_stale_connections()` is correct to release stale semaphore slots. However, Python's `threading.Semaphore.release()` has no upper bound by default — it can be released beyond its initial count. If this function is called repeatedly (e.g., scheduled every 5 minutes), it will release slots for the same already-cleared entries — except they were already removed from `_checked_out_connections` on the first call. On the second call, `stale` is empty, so no double-release there. But if the caller holds a reference to a stale `conn_id` list from outside, or if two threads call `force_close_stale_connections()` concurrently, the semaphore can be over-released. Protect with `_stats_lock` across the entire pop + release sequence.

---

### 26.H-4 — `sql_safe.SafeQueryBuilder.order_by()` takes a raw string and interpolates it directly into SQL with no sanitization:

```python
if self._order_by:
    query += f" ORDER BY {self._order_by}"
The table and where_in column names are sanitized via sanitize_table_name(), but order_by(), limit(), and offset() values are not validated. limit and offset are typed int so they are safe, but order_by accepts any string. If a caller passes user-controlled data to order_by() (e.g., from a web request), this is SQL injection in the query builder that is supposed to prevent SQL injection. order_by should accept a column name + direction enum (ASC/DESC) only, with sanitize_table_name() on the column.

🟠 Mediums (8)
ID	File	Issue
26.M-5	db_connection.py	_pool_stats["semaphore_waiters"] is incremented on every successful semaphore acquire (_pool_stats["semaphore_waiters"] += 1). The naming implies "how many threads are currently waiting" — but it is a cumulative counter (never decremented), so it actually means "total semaphore acquisitions since startup". The name is misleading. Rename to "semaphore_acquires" or document the semantics clearly.
26.M-6	db_connection.py	get_conn() has a sqlite_path parameter (sqlite_path: str = "war_machine.db") that is ignored when USE_POSTGRES = True. This was the parameter that ab_test_framework.py (25.H-2) was trying to use via get_conn(self.db_path). The parameter name sqlite_path makes it look like it accepts an alternate SQLite file — but it silently does nothing on Postgres. Document explicitly: "this parameter is ignored when USE_POSTGRES=True" or remove it (breaking the SQLite fallback).
26.M-7	db_connection.py	return_conn() calls _db_semaphore.release() inside a bare try/except Exception: pass in the finally block. If _db_semaphore.release() raises ValueError (released too many times — a real scenario given 25.C-1 and 25.H-3 bugs), the exception is silently swallowed. At minimum, log the error: print("[DB] WARNING: semaphore over-release detected").
26.M-8	db_connection.py	check_pool_health() accesses _db_semaphore._value — a private attribute of threading.Semaphore. This is not part of the public API and could break on CPython version changes. Use _db_semaphore._Semaphore__value (Python 3.x) or maintain a separate atomic counter. The ._value access pattern is already in use across several monitoring tools in the Python ecosystem, but it should be documented as CPython-internal.
26.M-9	db_connection.py	close_pool() is guarded by _pool_lock but _connection_pool is set to None inside the lock after closeall(). If get_conn() is called concurrently while close_pool() is executing, get_conn() sees _connection_pool is not None (before the None assignment), calls getconn() on a pool that is mid-shutdown, and gets an exception. The _pool_lock is described as "Only used for close_pool() shutdown guard" but get_conn() does not acquire it before checking _connection_pool. The shutdown guard doesn't actually guard get_conn().
26.M-10	sql_safe.py	build_insert(), build_update(), build_delete() all accept a placeholder: str = "?" parameter — SQLite default. Any caller that passes these to a Postgres cursor without changing the placeholder will get a Postgres psycopg2.errors.SyntaxError. The default should use ph() from the module: placeholder: str = None with placeholder = placeholder or ph() inside. This is the exact mistake that caused 25.H-4.
26.M-11	sql_safe.py	safe_execute() silently executes a parameterized query with params only if if params: — a falsy check. If params = (0,) (a tuple containing a single zero), if params: evaluates to True (non-empty tuple). But if params = (None,) — also truthy. Edge case: params = () (empty tuple) is falsy, so it calls cursor.execute(query) without params — correct. But params = (0,) → truthy → correct. This is fine for the current codebase. No bug, but the intent is if params is not None for robustness.
26.M-12	sql_safe.py	sanitize_table_name() blocks SQL keywords: {'select', 'insert', 'update', 'delete', 'drop', 'create', 'alter', 'truncate', 'union', 'where', 'from', 'join'}. Missing common injection vectors: 'exec', 'execute', 'cast', 'convert', 'declare', 'xp_', 'sp_'. The list is also static — Postgres has additional keywords not in this list. For War Machine's internal use (table names come from code, not user input), this is low risk. But the function is documented as a security control — incomplete keyword blocking creates false confidence. Better to allowlist known table names explicitly rather than deny-list SQL keywords.
🟢 Lows (6)
ID	File	Issue
26.L-13	db_connection.py	Multiple print() calls at module level during pool init ("[DB] Testing PostgreSQL connection...", "[DB] Initializing connection pool...", etc.) — not logger.info(). This continues the pattern flagged in every batch. In this file, startup prints are arguably useful for Railway deployment log visibility, but should still use logging so they can be suppressed in tests.
26.L-14	db_connection.py	CONNECTION_TIMEOUT_SECONDS = 300 (5 minutes). The health check warns if a connection is held > 5 min. With POOL_MAX = 15 and DB_SEMAPHORE_LIMIT = 12, a 5-minute checkout means up to 12 connections can be tied up for 5 minutes each before the leak warning fires. With the 30s semaphore timeout in get_conn(), the system would deadlock 2 minutes before the leak warning even appears. The timeout should be much shorter — 30–60 seconds — and should match the semaphore timeout.
26.L-15	db_connection.py	get_pool_stats() just delegates to check_pool_health(). It is an alias with no additional behavior. Either remove it or document that it is a stable public API alias for check_pool_health().
26.L-16	sql_safe.py	get_placeholder(conn) exists as a compat shim that calls ph() ignoring its conn argument. The docstring says it "delegates to ph() which reads USE_POSTGRES at module level — safe for pooled connections". This is correct. But the function signature still accepts conn — any caller passing conn to it is silently correct. The conn parameter should be deprecated with a warning, since it implies connection-type detection that no longer happens.
26.L-17	sql_safe.py	SafeQueryBuilder hardcodes placeholder: str = "?" in __init__. Same issue as build_insert() (26.M-10) — should default to ph().
26.L-18	db_connection.py	The FIX comment history (FIX #2 through FIX #8) in the module docstring is invaluable context. Consider moving it to CHANGELOG.md or a docs/db_architecture.md rather than growing the module docstring indefinitely. At current rate, the docstring will be longer than the code within 3–4 more fixes.
app/data/ File Inventory (For Future Batches)
Files catalogued but not yet audited:

File	Size	Batch
candle_cache.py	19.4 KB	→ Batch 27
data_manager.py	43.1 KB	→ Batch 27–28
database.py	1.8 KB	→ Batch 27
unusual_options.py	15.4 KB	→ Batch 27
ws_feed.py	22.9 KB	→ Batch 28
ws_quote_feed.py	20.2 KB	→ Batch 28
Priority Fix Order
26.H-1 — Root cause architectural fix: deprecate get_conn() / return_conn() as public API; enforce get_connection() context manager everywhere — eliminates the entire class of connection-leak bugs from Batches 17–25

26.H-4 — SafeQueryBuilder.order_by() unsanitized string injection in the SQL injection prevention module

26.H-2 — check_pool_health() "healthy" threshold allows 5 leaked connections before alarm — use len(_checked_out_connections) instead of cumulative delta

26.M-10 — build_insert/update/delete() default to SQLite ? placeholder — any Postgres caller without explicit placeholder="%s" will produce broken SQL

26.M-9 — close_pool() shutdown guard doesn't protect get_conn() concurrent path

26.L-14 — CONNECTION_TIMEOUT_SECONDS = 300 too long — deadlock before leak warning fires; reduce to 30–60s

**26.H-1 is the systemic root cause** of the entire connection management bug class that has appeared in every batch since Batch 17. The `get_connection()` context manager is already written, already correct, already in the module — it just has zero adoption. A single enforced refactor replacing all `get_conn()` / `return_conn()` call sites with `with get_connection() as conn:` would retroactively close 25.C-1, 25.H-3, 24.H-1, and every similar finding across prior batches simultaneously.

**26.M-10** is the direct cause of 25.H-4 — `sql_safe.build_*` functions default to `?` (SQLite) instead of calling `ph()`, which is why `explosive_mover_tracker` reporting functions produced Postgres syntax errors.
