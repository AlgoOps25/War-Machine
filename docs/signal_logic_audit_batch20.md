Here is the full Batch 20 audit. Ready to copy-paste.

File: docs/signal_logic_audit_batch20.md
text
# Signal Logic Audit — Batch 20

**Date:** 2026-03-18
**Scope:** `app/core/scanner.py`
**Total Findings:** 21 (1 Critical, 5 High, 9 Medium, 6 Low)

---

## 🔴 Criticals (1)

---

### 20.C-1 — `_run_ticker_with_timeout()` submits each ticker to a `ThreadPoolExecutor(max_workers=1)` — a single-worker executor. The executor serializes all tickers sequentially inside its one thread. The `future.result(timeout=45)` timeout is measured from submission, but the ticker only starts processing after all previously submitted futures complete. If ticker #1 takes 44 seconds, ticker #2's 45-second timeout window begins the moment it's submitted — before ticker #1 even finishes. By the time ticker #2 starts executing, it has ≤1 second left on its timeout, and it will be killed immediately regardless of its actual processing time. For a 30–50 ticker watchlist at OR open (5-second scan interval), this means all tickers after the first slow one are timed out immediately.

**File:** `scanner.py` → `_run_ticker_with_timeout()`

```python
_ticker_executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="ticker_watchdog")
The comment says this is a "watchdog" — but a watchdog must be able to observe an independently running task. With max_workers=1, the watchdog IS the execution thread. There is no concurrency: tickers run in a queue, not in parallel. The timeout on future.result() is a wall-clock deadline from submission, not from execution start, so queued tickers are systematically timed out.

Fix: The ticker loop in start_scanner_loop() already uses a simple for ticker in watchlist sequential loop. The ThreadPoolExecutor wrapping adds overhead with no benefit. Either:

Remove the executor entirely and call process_ticker(ticker) directly with a signal.alarm()-based per-call timeout (Unix), or

Use max_workers=N (e.g., 4) so tickers actually run concurrently and the timeout applies to actual execution, not queue wait time.

The simplest correct fix is removing the executor and using a per-call thread with join(timeout=45):

python
def _run_ticker_with_timeout(process_ticker_fn, ticker: str) -> bool:
    t = threading.Thread(target=process_ticker_fn, args=(ticker,), daemon=True)
    t.start()
    t.join(timeout=TICKER_TIMEOUT_SECONDS)
    if t.is_alive():
        logger.error(f"[WATCHDOG] ⏰ {ticker} timed out after {TICKER_TIMEOUT_SECONDS}s — skipping")
        return False
    return True
🟡 Highs (5)
20.H-2 — analytics_conn is a bare psycopg2 connection created at module-level — separate from the db_connection.py connection pool used by every other module. This creates two parallel DB connection systems: the pool (used by signal_analytics, position_manager, cooldown_tracker, etc.) and this raw connection (used only for AnalyticsIntegration). Under peak load, the pool can be exhausted while analytics_conn is idle. The raw connection also has no max_overflow or pool_size guard — if _get_analytics_conn() creates multiple connections across retries that don't close, the Postgres connection limit is approached. The _get_analytics_conn() reconnect helper closes the old connection before retrying, which is correct, but the initial analytics_conn created at module load is never explicitly closed at process exit.
File: scanner.py → module-level DB block

Fix: Replace the raw psycopg2.connect() with a checkout from db_connection.get_conn() so all DB connections go through the unified pool. If AnalyticsIntegration requires a persistent connection (not a pool checkout), document the reason explicitly and set a statement_timeout to prevent runaway queries.

20.H-3 — The loss streak circuit breaker logic has an operator precedence bug:
python
_has_loss_streak = (
    daily_stats.get("losses", 0) >= 3
    and daily_stats.get("wins", 0) == 0
    or _pm.has_loss_streak(max_consecutive_losses=3)
)
Python operator precedence: and binds tighter than or. This evaluates as:

python
(losses >= 3 AND wins == 0) OR (has_loss_streak)
The intent appears to be: trigger circuit breaker if either condition is true. But has_loss_streak() triggers independently of wins == 0. A day with wins=2, losses=3 (60% win rate) and a current 3-trade loss streak (last 3 losses after the 2 wins) would trigger the circuit breaker via _pm.has_loss_streak() alone. If the intent is "losses >= 3 AND wins == 0 AND loss streak", the current logic may halt trading on a profitable day. If the intent is "either condition alone is sufficient", the parentheses are missing and the code works correctly but is confusing.

Fix: Add explicit parentheses to document intent:

python
_has_loss_streak = (
    (daily_stats.get("losses", 0) >= 3 and daily_stats.get("wins", 0) == 0)
    or _pm.has_loss_streak(max_consecutive_losses=3)
)
Then confirm with a comment whether both conditions are independently sufficient.

20.H-4 — subscribe_and_prefetch_tickers() fires two background threads via _fire_and_forget() using a single lambda: (fn1(), fn2()) — a tuple expression. A tuple of two None returns is evaluated, not two sequential calls. If startup_backfill_with_cache() raises an exception, startup_intraday_backfill_today() never runs, and no error is reported because the exception is inside a lambda inside a daemon thread with only logger.warning() on failure.
File: scanner.py → subscribe_and_prefetch_tickers()

python
_fire_and_forget(
    lambda: (
        data_manager.startup_backfill_with_cache(combined, days=30),
        data_manager.startup_intraday_backfill_today(combined),
    ),
    label=f"prefetch-{','.join(new_tickers[:3])}"
)
Both calls DO execute (Python evaluates all tuple elements), so this is not a functional bug — but the tuple pattern makes exception isolation impossible. If startup_backfill_with_cache() raises, _fire_and_forget's except Exception as e: logger.warning(...) catches only one exception for both calls, and the intraday backfill never runs.

Fix: Split into two separate _fire_and_forget() calls:

python
_fire_and_forget(
    lambda: data_manager.startup_backfill_with_cache(combined, days=30),
    label=f"historical-backfill-{','.join(new_tickers[:3])}"
)
_fire_and_forget(
    lambda: data_manager.startup_intraday_backfill_today(combined),
    label=f"intraday-backfill-{','.join(new_tickers[:3])}"
)
20.H-5 — The EOD block imports from app.core.sniper import _bos_watch_alerted and calls _bos_watch_alerted.clear(). Importing a mutable module-level set by name creates a local reference to the same object — clear() correctly empties the original set. However, this is a private implementation detail of sniper.py being directly manipulated from scanner.py. If sniper.py ever replaces _bos_watch_alerted with a new set (e.g., _bos_watch_alerted = set() instead of _bos_watch_alerted.clear()), the import in scanner.py would hold a reference to the old set, and the clear would have no effect. This is a coupling violation — scanner.py reaching into sniper.py internals.
File: scanner.py → EOD block

Fix: Expose a public reset_session_state() function in sniper.py that clears all session-level state (_bos_watch_alerted, _orb_classifications, _TICKER_WIN_CACHE refresh, etc.), and call that from scanner.py instead.

20.H-6 — get_screener_tickers() is defined at module level in scanner.py but is never called anywhere in this file. It makes a live requests.get() HTTP call to the EODHD screener API. It is also not exported via __init__.py. This is either dead code that should be removed, or a utility function that belongs in app/screening/ rather than scanner.py.
File: scanner.py → get_screener_tickers()

Fix: If unused, delete. If still needed elsewhere, move to app/screening/ and import from there.

🟠 Mediums (9)
ID	File	Issue
20.M-7	scanner.py	start_scanner_loop() imports process_ticker, clear_armed_signals, clear_watching_signals, _orb_classifications from app.core.sniper at function entry — not at module level. This defers the sniper import until start_scanner_loop() is called, which is intentional (Phase 1.30 comment). But _orb_classifications is imported as a local name — if sniper.py reassigns _orb_classifications (e.g., _orb_classifications = {}), the local reference in scanner.py is stale. The same issue as 20.H-5.
20.M-8	scanner.py	_get_stale_tickers() calls candle_cache.get_bars(ticker, limit=1) for every ticker at startup — this is N DB/filesystem reads executed synchronously before the WS feeds start. For a 50-ticker watchlist, this is 50 cache reads blocking startup. Should be parallelized or batched.
20.M-9	scanner.py	The startup banner prints 35+ print() lines with flush=True at every boot. This is purely cosmetic and creates noise in Railway logs. After Phase 1.33 (latest), these lines are permanent history — the Phase status is now stable. Consider collapsing to a single multi-line block or gating behind DEBUG flag.
20.M-10	scanner.py	is_market_hours() checks now.weekday() >= 5 for weekend detection but does not check US market holidays (Memorial Day, July 4th, etc.). On a holiday, is_market_hours() returns True at 10 AM, should_scan_now() returns True, and the scanner runs a full cycle against a closed market — every process_ticker() call will get empty bars and fail silently. No holiday calendar integration.
20.M-11	scanner.py	calculate_optimal_watchlist_size() uses fixed time windows (9:30–9:40: 30, 9:40–10:30: 30, 10:30–15:00: 50, 15:00–16:00: 35) but these are not derived from measured performance data — they are hand-tuned constants with no config entry and no backtest reference. Hardcoded in the middle of a function with no documentation. Should be in config.py as WATCHLIST_SIZE_WINDOWS.
20.M-12	scanner.py	send_regime_discord() is called on every cycle with no rate limit beyond whatever market_regime_context.py implements internally. If REGIME_DISCORD_AVAILABLE = True and the internal rate limit in market_regime_context.py is off or misconfigured, a Discord message fires every 5 seconds during OR window. The call site should enforce a minimum send interval.
20.M-13	scanner.py	The premarket watchlist refresh logic (if not premarket_built / elif funnel.should_update()) is duplicated: both branches call get_watchlist_with_metadata(force_refresh=True), extract premarket_watchlist, compute new_tickers, and call subscribe_and_prefetch_tickers(). The only difference is the metadata/volume_signals extraction in the first branch. These should be unified into a single _build_or_refresh_watchlist() helper.
20.M-14	scanner.py	The EOD block accesses watchlist_data and metadata variables inside get_watchlist_with_metadata() calls that are scoped to the if not premarket_built branch. If the premarket build fails (exception path), premarket_watchlist = list(EMERGENCY_FALLBACK) but metadata and volume_signals are never assigned. Later logger.info(f"[FUNNEL] Stage: {metadata['stage'].upper()} ...") in the elif funnel.should_update() branch would raise NameError: name 'metadata' is not defined if triggered after a failed initial build.
20.M-15	scanner.py	_extract_premarket_metrics() is defined but never called in scanner.py. The function computes explosive_count, avg_rvol, avg_score, and top_3_summary from watchlist data. It is likely intended for the Discord premarket broadcast but the call site was removed or never wired. Dead code.
🟢 Lows (6)
ID	File	Issue
20.L-16	scanner.py	start_health_server() is called at module level (Phase 1.27) AND the banner prints "Health HTTP: ✅ ENABLED". If start_health_server() raises at module load, the entire scanner.py import fails before start_scanner_loop() even runs — Railway sees an import error rather than a clean startup failure. Should be wrapped in try/except at module level.
20.L-17	scanner.py	The startup banner hardcodes v1.33 in two places: the print statement and the Discord send_simple_message() call. Version number is not derived from a __version__ variable or config.py constant. Every phase bump requires a manual find-and-replace.
20.L-18	scanner.py	ANALYTICS_AVAILABLE and analytics_conn are module-level globals mutated inside _get_analytics_conn() via global analytics_conn, ANALYTICS_AVAILABLE. The global mutation pattern is flagged across all batches — use a class or a connection state object.
20.L-19	scanner.py	data_update_counter, data_update_symbols, and last_data_summary_time are initialized at module level but never updated anywhere in scanner.py. These appear to be remnants of a removed data-update callback system. Dead variables — remove.
20.L-20	scanner.py	_now_et() is defined locally in scanner.py as datetime.now(ZoneInfo(...)). The same function is defined in sniper.py and in utils/time_helpers.py. Three definitions of the same helper. Import from utils.time_helpers everywhere.
20.L-21	scanner.py	get_adaptive_scan_interval() and calculate_optimal_watchlist_size() both use global _last_logged_* variables to suppress duplicate log lines. The globals are reset across function calls but only when the value changes — they are never cleared at EOD reset. If the watchlist size changes at EOD and then returns to the same size on the new day, the log line is suppressed on day 2 even though it's a new session. Should be reset in the EOD cleanup block alongside cycle_count and loss_streak_alerted.
Priority Fix Order
20.C-1 — Single-worker executor systematically times out tickers #2–N after any slow ticker #1 — entire watchlist effectively runs on a 45-second shared budget

20.H-3 — Circuit breaker operator precedence bug — may halt trading on profitable days due to has_loss_streak() triggering independently

20.H-2 — Raw psycopg2 connection parallel to pool — connection resource contention under load

20.H-5 — scanner.py directly imports and mutates sniper.py private state (_bos_watch_alerted) — coupling violation, fragile to refactors

20.M-14 — NameError: metadata not defined if watchlist build fails then funnel.should_update() fires

20.H-4 — Lambda tuple pattern masks per-call exceptions in background backfill

20.H-6 — get_screener_tickers() is dead code with a live HTTP call — remove or relocate

