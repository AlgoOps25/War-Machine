Full Batch 35 audit below.

File: docs/signal_logic_audit_batch35.md
text
# Signal Logic Audit — Batch 35

**Date:** 2026-03-18
**Scope:** `app/signals/signal_analytics.py` (32 KB)
**Total Findings:** 17 (0 Critical, 3 High, 8 Medium, 6 Low)

---

## `signal_analytics.py`

The docstring notes a Mar 10 fix: "All get_conn() calls now use
try/finally: return_conn(conn) — no leaks." Verified — every method
follows the `conn = None / try / finally: if conn: return_conn(conn)`
pattern correctly. This is the cleanest DB access pattern in the
entire codebase so far. The `get_rejection_breakdown()` and
`get_hourly_funnel()` additions from Mar 16 are well-structured.
Zero criticals.

---

## 🔴 Criticals (0)

---

## 🟡 Highs (3)

---

### 35.H-1 — **Signal lifecycle tracking has a one-ticker-per-session constraint that silently drops real signals.** `session_signals` is keyed by `ticker` only — not `(ticker, signal_id)`. If the same ticker fires two signals in one session (e.g., NVDA fires a BOS at 9:45 and again at 11:30 after a retest), the second `record_signal_generated('NVDA', ...)` call overwrites the first entry in `session_signals`:

```python
self.session_signals[ticker] = {
    'event_id': event_id,
    'stage': 'GENERATED',
    ...
}
The subsequent record_validation_result('NVDA', ...) then checks cached['stage'] != 'GENERATED' — but the cached stage is 'VALIDATED' from the first signal still in flight. The warning "No GENERATED signal found for NVDA" fires and the validation event returns -1. The second signal's validation, arming, and trade execution are all lost from analytics. On an active ticker like NVDA that can fire 3–5 signals per session, the analytics funnel undercounts significantly. Fix: key session_signals as {(ticker, event_id): ...} or use a list of in-flight signals per ticker.

35.H-2 — record_validation_result() uses position_id column for the wrong semantic. The VALIDATED stage INSERT maps self.session_signals[ticker]['event_id'] (the GENERATED event ID) into the position_id column:
python
values = (
    ticker, self.session_signals[ticker]['event_id'],  # ← this is a signal event ID
    stage, ...
)
cursor.execute(f"""
    INSERT INTO signal_events
        (ticker, position_id, ...)   # ← but column is named position_id
""", values)
position_id is defined in the schema as position_id INTEGER and is semantically the trade's position ID (filled in by record_trade_executed()). Using it as a "parent event ID" foreign key in VALIDATED and ARMED events is a schema misuse. Any query joining position_id across stages will conflate signal event IDs with actual broker position IDs. The VALIDATED and ARMED rows should use a dedicated parent_event_id column or a separate signal_id linking column. Same misuse in record_signal_armed().

35.H-3 — get_daily_summary() makes 5 separate DB queries (funnel, grades, multipliers, rejections, hourly), each acquiring a pool connection:
python
funnel    = self.get_funnel_stats(session_date)       # conn 1
grades    = self.get_grade_distribution(session_date) # conn 2
mults     = self.get_multiplier_impact(session_date)  # conn 3
rejections = self.get_rejection_breakdown(days=1)      # conn 4
hourly    = self.get_hourly_funnel(days=1)             # conn 5
get_daily_summary() is called from eod_reporter.py at EOD. By itself this is acceptable. However, get_discord_eod_summary() also calls get_funnel_stats() and get_rejection_breakdown() independently — if both are called at EOD in sequence, that's 7 pool connections. More importantly, if a dashboard loop calls get_daily_summary() every 5 minutes, that's 5 connections × 12 calls/hour = 60 pool connections/hour for dashboard reporting alone. Fix: consolidate all 5 queries into a single get_daily_summary() DB session using one connection and multiple cursor executes, or at minimum cache the result with a 5-minute TTL.

🟠 Mediums (8)
ID	Issue
35.M-4	record_signal_generated() has a Postgres/SQLite branch for RETURNING id detection: if 'postgres' in str(type(cursor)). This pattern appears in all 4 record_* methods. As noted in prior batches (26.M-8 equivalent), str(type(cursor)) returning "<class 'psycopg2.extensions.cursor'>" contains "psycopg2" not "postgres". The string "postgres" does not appear in the default psycopg2 cursor type name. This check always evaluates False on Railway Postgres — the else branch (SQLite's cursor.lastrowid) always runs. On Postgres, cursor.lastrowid is None after an INSERT without RETURNING. All 4 record_* methods return event_id = None, which is stored in session_signals and passed as position_id in subsequent INSERTs. The analytics event chain is broken: every VALIDATED/ARMED row has position_id = None instead of the parent signal's ID. Fix: use ph() to detect Postgres (as established in Batch 26) or use RETURNING id unconditionally and always call cursor.fetchone().
35.M-5	session_signals is never reset between trading days unless clear_session_cache() is explicitly called. If eod_reporter.py fails to call clear_session_cache() before midnight, stale entries from the prior session remain. The next day's first record_validation_result('AAPL', ...) finds a cached stage of 'TRADED' from yesterday and logs "No GENERATED signal found for AAPL", suppressing today's first AAPL validation event. Should auto-reset when _get_session_date() returns a date different from session_start.date().
35.M-6	get_funnel_stats() counts rows by stage with GROUP BY stage. The funnel rates assume each row represents a unique signal: validation_rate = validated / generated. But due to 35.H-1 (same-ticker overwrite) and 35.H-2 (position_id misuse), the VALIDATED count may include duplicate rows from the same signal being re-recorded. The funnel denominators are row counts, not unique signal counts. A COUNT(DISTINCT ticker) or a proper signal_id FK would give accurate unique-signal funnel rates.
35.M-7	get_rejection_breakdown() groups by rejection_reason as a raw string. rejection_reason is stored as a comma-joined string: checks_str = ','.join(checks_passed) in record_validation_result(). Wait — rejection_reason is actually the rejection_reason parameter, not checks_str. But if rejection_reason can be multi-word (e.g., "ADX below threshold" vs "ADX_BELOW_THRESHOLD"), case and formatting inconsistencies across callers will fragment the breakdown. Should normalize to uppercase with underscores before storing.
35.M-8	get_multiplier_impact() queries WHERE stage = 'VALIDATED' for multiplier averages. But multipliers (IVR, UOA, GEX, MTF) are recorded in the VALIDATED row. The base_confidence is recorded in the GENERATED row. The query fetches AVG(base_confidence) from VALIDATED rows, but base_confidence is only set in GENERATED rows — it's NULL in all VALIDATED rows. AVG(base_confidence) from VALIDATED rows is always NULL → falls back to row['base_avg'] or 0.7 (hardcoded 0.7 default). The base_avg in the multiplier impact report is always 0.7 regardless of actual base confidence values. Fix: join GENERATED and VALIDATED rows via the position_id FK (once 35.H-2 is fixed) or query the GENERATED rows for base_confidence.
35.M-9	get_hourly_funnel() builds hourly: Dict[int, Dict[str, int]] as a defaultdict(lambda: defaultdict(int)). defaultdict(int) is not serializable with json.dumps(). If any caller attempts to serialize the result (e.g., for a REST endpoint or Discord payload), this raises TypeError. Should convert to plain dict before returning.
35.M-10	signal_tracker = SignalTracker() at module level triggers _initialize_database() on import — same eager-init anti-pattern as Batch 31/32. With try/except around _initialize_database(), a DB error is caught and logged rather than crashing — better than most other files. However, _initialize_database() creates 4 indexes on the signal_events table. On a cold start against an empty Railway Postgres, this is fine. But CREATE INDEX IF NOT EXISTS acquires an AccessShareLock on the table for each index. If 4 indexes are created simultaneously with other connections running at startup, there's a brief lock contention window. Not a production blocker, but worth noting.
35.M-11	get_daily_summary() calls get_rejection_breakdown(days=1) and get_hourly_funnel(days=1) to report "today only." But both methods compute cutoff = (datetime.now(ET) - timedelta(days=1)).strftime(...) — yesterday's date. The filter is session_date >= cutoff. For a session that started today, session_date = '2026-03-18' and cutoff = '2026-03-17' — the query includes yesterday's data. To get "today only," days=0 or cutoff = today is needed. The days=1 arg means "last 1 day" but actually returns 2 days of data. Should use days=0 or pass session_date as the cutoff directly.
🟢 Lows (6)
ID	Issue
35.L-12	_initialize_database() prints "[ANALYTICS] Signal tracking database initialized" on every startup including cold restarts. Should be logger.info. All 4 record_* methods print warnings on error. All should be logger.warning.
35.L-13	record_signal_generated() takes confidence: float and stores it as base_confidence. The confidence values in the __main__ example are passed as 0.72 (fractional). _calculate_confidence() in breakout_detector.py returns integers (50–100). If callers pass fractional (0.0–1.0) confidences and breakout_detector passes integers (50–100), the base_confidence column stores mixed scales. get_multiplier_impact() would average 0.72 and 72 in the same column producing meaningless results. Should enforce a consistent scale (recommend 0–100 integer) and validate on insert.
35.L-14	get_discord_eod_summary() calls get_funnel_stats() and get_rejection_breakdown() — 2 DB connections — even if the session had 0 signals. The check if funnel['rejected'] > 0 guards the rejection section, but both queries still run. Should gate on if funnel['generated'] == 0: return "📊 No signals generated today." before querying rejections.
35.L-15	clear_session_cache() resets session_start = datetime.now(ET). This is used for nothing — session_start is set in __init__ and clear_session_cache() but never read anywhere in the class. Dead state. Should be removed or used in 35.M-5's auto-reset guard.
35.L-16	get_grade_distribution() iterates hardcoded grades ['A+', 'A', 'A-', 'B+', 'B'] for the summary. If the system ever generates a 'B-' or 'C' grade signal, those rows are silently excluded from the printed distribution (though they're in grade_counts dict returned). The hardcoded grade list should match the actual grade enum from signal_validator.py.
35.L-17	The __main__ block is a clean, well-structured integration test that correctly exercises all 4 lifecycle stages in sequence. No issues — this is a good pattern to replicate in test files.
app/signals/ Layer — Complete Audit Summary (Batches 33–35)
Consolidated Finding Counts
Batch	File	C	H	M	L	Total
33	breakout_detector.py	0	5	9	6	20
34	opening_range.py	0	5	10	7	22
35	signal_analytics.py	0	3	8	6	17
Total	3 files	0	13	27	19	59
Top 10 Priority Fixes — app/signals/ (All Batches)
Rank	ID	Fix	Impact
1	35.M-4	'postgres' in str(type(cursor)) always False — all record_* return None event IDs; analytics event chain is fully broken on Railway	All analytics silently broken
2	35.H-1	session_signals keyed by ticker only — multi-signal tickers overwrite each other; funnel undercounts	Data loss on active tickers
3	33.H-2	PDH/PDL can lower resistance below rolling intraday high — false bull breakout signals	Signal quality
4	34.H-1	get_session_levels() hits DB on every call — 600+ queries/min with no cache	Pool/DB load
5	33.H-4	Confidence gate < 50 unreachable — every signal passes scoring regardless of quality	Signal filter dead
6	35.H-2	position_id column used as parent event FK — semantic schema corruption	Schema integrity
7	35.M-8	base_confidence always returns 0.7 hardcoded default — multiplier impact report is meaningless	Analytics accuracy
8	34.M-6	_calculate_atr() uncached — 50 uncached DB queries per 9:40 OR classification burst	DB load
9	33.H-3	EMA volume with < 5 bars at session open — unstable volume ratios in first 5 minutes	Early signal quality
10	35.M-11	days=1 cutoff includes yesterday — "today only" sections in daily summary show 2 days of data	Reporting accuracy


**35.M-4 is the single highest-impact finding in the entire `app/signals/` layer** — the Postgres cursor type string check has never evaluated `True` on Railway, meaning every `record_signal_generated()` has returned `None` as the event ID since day one. Every subsequent VALIDATED/ARMED/TRADED row has `position_id = NULL` instead of the parent event ID, making the entire signal chain unlinkable. The analytics funnel reports row counts correctly (the INSERTs succeed), but the event linkage is silently broken. The fix is one line: use `RETURNING id` unconditionally and always call `cursor.fetchone()` — since `ph()` already gates Postgres vs SQLite behavior correctly everywhere else.

**`app/signals/` is now fully audited — 59 total findings, zero criticals, 13 highs.** The combined `app/analytics/` + `app/signals/` audit total now stands at **119 findings across 13 files, zero criticals, 25 highs.**
