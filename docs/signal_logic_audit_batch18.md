Here is the full Batch 18 audit. Ready to copy-paste.

File: docs/signal_logic_audit_batch18.md
text
# Signal Logic Audit — Batch 18

**Date:** 2026-03-18
**Scope:** `app/signals/signal_analytics.py`
**Total Findings:** 17 (0 Critical, 5 High, 7 Medium, 5 Low)

---

## 🔴 Criticals (0)

No critical findings. The module is primarily a lifecycle recorder and analytics reporter — there is no signal logic that can produce incorrect trades.

---

## 🟡 Highs (5)

---

### 18.H-1 — `session_signals` cache uses `ticker` as key — a second GENERATED signal for the same ticker within the same session overwrites the first without warning, silently orphaning the first signal in the DB
**File:** `signal_analytics.py`

```python
self.session_signals[ticker] = {
    'event_id': event_id,
    'stage': 'GENERATED',
    'timestamp': datetime.now(ET)
}
If a ticker generates two signals in the same session (e.g. a morning breakout signal is recorded, armed, traded and closed, then an afternoon breakout fires again), the second record_signal_generated() call overwrites session_signals[ticker]. Subsequent calls to record_validation_result() and record_signal_armed() use cached.get('validation_event_id') / cached.get('armed_event_id'), which now refer to the second signal's IDs — but record_signal_armed() inserts position_id = cached.get('validation_event_id'), linking the ARMED row to the second VALIDATED row's ID. The first signal's GENERATED/VALIDATED rows are orphaned (no ARMED/TRADED rows will ever reference them), corrupting the funnel count: generated = 2, validated = 1, armed = 1, traded = 1 → validation_rate = 50% instead of the correct 100% for actually validated signals.

Fix: Use (ticker, event_id) or a counter-based key so multiple same-day signals for the same ticker are tracked independently. Simpler: use a deque of pending stage chains per ticker:

python
self.session_signals[ticker] = []   # list of stage chains
# append new chain on each GENERATED; pop completed on TRADED
18.H-2 — record_validation_result() inserts position_id = self.session_signals[ticker]['event_id'] — this is the GENERATED event's id, not a positions table position_id — the position_id column is semantically misused as an inter-row link within signal_events
File: signal_analytics.py

python
values = (
    ticker, self.session_signals[ticker]['event_id'],  # ← GENERATED row id
    stage, ...
)
cursor.execute("""
    INSERT INTO signal_events (ticker, position_id, ...)
""", values)
The position_id column in the DDL is described as "Trade linkage" (FK to positions table). But every lifecycle stage except GENERATED uses position_id to store the parent event's id within signal_events itself — creating a self-referencing link. The TRADED stage correctly stores the actual position_id from position_manager. The column is overloaded with two different meanings: intra-table parent link AND FK to positions. Analytics queries that join signal_events.position_id to the positions table will get garbage results for VALIDATED/ARMED rows.

Fix: Add a dedicated parent_event_id INTEGER column for the intra-table lifecycle chain and keep position_id strictly for the positions FK:

sql
ALTER TABLE signal_events ADD COLUMN parent_event_id INTEGER;
18.H-3 — get_funnel_stats() counts rows by stage, but each signal generates N rows (GENERATED + VALIDATED + ARMED + TRADED) — generated is the count of GENERATED-stage rows, not the count of unique signals — double-emitting record_signal_generated() for a ticker inflates generated without inflating validated, artificially deflating validation_rate
File: signal_analytics.py

python
cursor.execute("""
    SELECT stage, COUNT(*) as count
    FROM signal_events
    WHERE session_date = ?
    GROUP BY stage
""", (session_date,))
The funnel design is "one row per lifecycle event" — a single signal that reaches TRADED produces 4 rows. generated = 12 means 12 GENERATED-stage rows were inserted, not 12 unique signals. This is correct as long as every record_signal_generated() call corresponds to exactly one unique signal. The fragility is: if a caller double-calls record_signal_generated() for the same ticker (e.g. scanner loop fires twice before dedup), generated = 13 but validated = 12 → validation_rate = 92.3% instead of 100%. There is no dedup guard in record_signal_generated(). A UNIQUE constraint or a duplicate-check before INSERT would prevent this.

Fix: Add a dedup guard:

python
# Before INSERT in record_signal_generated():
if ticker in self.session_signals and self.session_signals[ticker]['stage'] == 'GENERATED':
    print(f"[ANALYTICS] Duplicate GENERATED signal for {ticker} — skipping")
    return self.session_signals[ticker]['event_id']
18.H-4 — get_rejection_breakdown() and get_hourly_funnel() use days cutoff computed with datetime.now(ET).strftime("%Y-%m-%d") — but session_date is stored without timezone (naive ET string) — on Railway (UTC), datetime.now(ET) correctly gives ET date. However, timedelta(days=days) is calendar-day arithmetic on the cutoff string, but session_date values in the DB use the ET date at signal generation time. If a signal fires at 11:59 PM ET (rare but possible) and Railway processes it at 4:01 AM UTC the next day, the stored session_date might be tomorrow. The cutoff comparison session_date >= cutoff is string comparison on %Y-%m-%d — lexicographic for ISO dates is correct, but only if both sides are ET. Confirmed safe for normal market hours (9:30–4 PM ET). Documented here for awareness.
File: signal_analytics.py

This is a documentation-level finding with no immediate fix required. The session_date column should be annotated in the DDL as -- ET date (America/New_York) to prevent future confusion.

18.H-5 — get_multiplier_impact() uses base_avg = row['base_avg'] or 0.7 — if the actual average base confidence is 0.0 (all signals were generated with 0.0 confidence, which is a misconfiguration), 0.0 or 0.7 evaluates to 0.7 in Python, silently substituting a wrong default
File: signal_analytics.py

python
base_avg  = row['base_avg'] or 0.7    # 0.0 → 0.7 silently
final_avg = row['final_avg'] or 0.7
total_boost_pct = ((final_avg - base_avg) / base_avg * 100) if base_avg > 0 else 0
The or 0.7 pattern substitutes 0.7 when the SQL AVG() returns NULL (no VALIDATED rows) OR when the actual average is 0.0. A more common real-world trigger: confidence values are stored as integers (0–100 scale as used by _calculate_confidence()) but get_multiplier_impact() was written assuming 0.0–1.0 fractional scale (base_avg = 0.7 implies 70%). If base_confidence is stored as 72 (integer), base_avg = 72.0, final_avg = 76.5 → total_boost_pct = 6.25%. The or 0.7 default produces a nonsensical 0.7 fallback against a 0–100 scale.

Fix: Use explicit None check:

python
base_avg  = row['base_avg']  if row['base_avg']  is not None else None
final_avg = row['final_avg'] if row['final_avg'] is not None else None
if base_avg is None:
    return { 'ivr_avg': 1.0, ... }
Also: standardize confidence scale (0–100 integer vs 0.0–1.0 float) across the entire codebase — this is inconsistently used in record_signal_generated() (confidence=0.72 in usage example) vs _calculate_confidence() which returns 0–100.

🟠 Mediums (7)
ID	File	Issue
18.M-6	signal_analytics.py	record_signal_armed() checks cached['stage'] != 'VALIDATED' but record_validation_result() sets stage = 'REJECTED' for failed validations. If a signal is REJECTED, then the scanner re-runs and the same ticker generates another GENERATED event (overwriting session_signals[ticker]), then immediately calls record_signal_armed() before record_validation_result() completes — cached['stage'] is 'GENERATED' not 'VALIDATED' and the guard fires the warning. This is a time-ordering sensitivity that depends on async call sequencing.
18.M-7	signal_analytics.py	get_daily_summary() calls five separate DB queries (funnel, grades, multiplier, rejection, hourly) — each with its own get_conn()/return_conn(). If called at EOD with a busy pool, this is 5 pool checkouts in sequence. Should be wrapped in a single connection and executed as sequential queries on one cursor.
18.M-8	signal_analytics.py	get_discord_eod_summary() calls get_funnel_stats() and get_rejection_breakdown() — both open their own DB connections. These are the same queries already executed by get_daily_summary() if called in the same EOD cycle. No result caching between the two methods.
18.M-9	signal_analytics.py	_initialize_database() creates four indexes on signal_events. The idx_signal_events_hour index on (session_date, hour_of_day, stage) covers the get_hourly_funnel() query. However get_funnel_stats() queries WHERE session_date = ? GROUP BY stage — the idx_signal_events_session index on (session_date, stage) covers this but is a covering index only for PostgreSQL. On SQLite (dev/local), a table scan may occur if the planner doesn't use the index for GROUP BY. Minor but worth noting for future profiling.
18.M-10	signal_analytics.py	signal_tracker = SignalTracker() at module scope calls _initialize_database() on import — runs CREATE TABLE IF NOT EXISTS and 4 CREATE INDEX IF NOT EXISTS statements against the DB every time the module is imported. On Railway with PostgreSQL, each CREATE INDEX IF NOT EXISTS acquires a share lock on the table. In production, the module is imported once per process, so this is benign — but it is still a side-effect import pattern flagged across all batches.
18.M-11	signal_analytics.py	The confidence scale is inconsistent. record_signal_generated() receives confidence as a float and stores it in base_confidence REAL. The usage example passes confidence=0.72 (fractional). But _calculate_confidence() in breakout_detector.py returns an integer 0–100. If the caller passes 72 (integer) instead of 0.72 (float), base_confidence = 72 is stored, and get_multiplier_impact() computes total_boost_pct = (final_avg - 72) / 72 * 100 — off by 100x from the intended fractional math. No validation or normalization of input scale at record time.
18.M-12	signal_analytics.py	get_daily_summary() calls get_rejection_breakdown(days=1) for "today only" — but days=1 means cutoff = today - 1 day = yesterday. The session_date >= cutoff filter includes both today AND yesterday. To get today-only data, the call should be session_date = self._get_session_date() with an equality filter, not days=1. Same issue in get_discord_eod_summary().
🟢 Lows (5)
ID	File	Issue
18.L-13	signal_analytics.py	statistics module is imported but never used — all statistics in the analytics queries are computed in SQL (AVG, COUNT). Remove the unused import.
18.L-14	signal_analytics.py	dtime alias for datetime.time is imported but never referenced in the file. Remove.
18.L-15	signal_analytics.py	self.db_path is stored and passed to every get_conn(self.db_path) call. But get_conn() from db_connection.py is designed to use the global pool — passing db_path directly bypasses the pool manager for non-default paths. This is consistent with how the module is called (always with the default "market_memory.db") but is fragile if a caller passes a custom path.
18.L-16	signal_analytics.py	_get_hour_of_day() returns datetime.now(ET).hour — stores the ET hour correctly. But get_hourly_funnel() presents hours as {hour:02d}:00 — a signal generated at 9:35 AM ET is stored as hour 9 and displayed as 09:00. This is fine but should be documented: the hour label represents the start of the hour, not the exact time.
18.L-17	signal_analytics.py	All print() calls should be logger.*. Same pattern flagged in batches 8–17.
Priority Fix Order
18.H-1 — session_signals[ticker] overwritten by second same-session signal — funnel counts corrupted for multi-signal tickers

18.H-2 — position_id column semantically overloaded as parent-event link AND positions FK — analytics joins to positions table will return wrong data

18.H-3 — No dedup guard in record_signal_generated() — double-emit from scanner loop deflates validation_rate

18.H-5 — or 0.7 default silently substitutes wrong base confidence when actual avg is 0.0 or None; compound issue with 0–100 vs 0.0–1.0 scale inconsistency (18.M-11)

18.M-12 — days=1 cutoff includes yesterday in "today only" queries — funnel and Discord EOD summaries show inflated counts

18.M-7 + 18.M-8 — Five separate DB connections for get_daily_summary(); two more for get_discord_eod_summary() duplicating the same queries

