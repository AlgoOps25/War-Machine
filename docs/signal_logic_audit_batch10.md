# Signal Logic Audit — Batch 10

**Date:** 2026-03-18
**Scope:** `app/risk/position_manager.py`, `app/risk/risk_manager.py`, `app/risk/trade_calculator.py`
**Total Findings:** 20 (4 Critical, 6 High, 6 Medium, 4 Low)

---

## 🔴 Criticals (4)

---

### 10.C-1 — `has_loss_streak()` uses `datetime.now()` (UTC on Railway) — today's trades are invisible
**File:** `position_manager.py`

```python
today = datetime.now().strftime("%Y-%m-%d")
...
WHERE status = 'CLOSED' AND DATE(exit_time) = {p}
Railway runs UTC. datetime.now() returns UTC. A trade closed at 3:55 PM ET (19:55 UTC) has exit_time with a UTC date of today — but a trade closed at 9:35 AM ET (13:35 UTC) is still "today" in both zones. The real danger: after midnight UTC (8:00 PM ET), datetime.now() rolls to the next calendar day — has_loss_streak() finds zero trades and returns False, clearing the circuit breaker mid-session. This is the same class of bug flagged in 8.C-4.

Fix: Use ET exclusively:

python
from zoneinfo import ZoneInfo
_ET = ZoneInfo("America/New_York")
today = datetime.now(tz=_ET).strftime("%Y-%m-%d")
Apply this fix to get_daily_stats(), get_todays_closed_trades(), get_win_rate(), _close_stale_positions(), and has_loss_streak() — all five use datetime.now() with no timezone.

10.C-2 — close_position() uses datetime.now() for exit_time but writes CURRENT_TIMESTAMP to DB — two different timestamps
File: position_manager.py

python
exit_time = datetime.now()   # Python UTC-naive

cursor.execute(f"""
    UPDATE positions
    SET exit_time = CURRENT_TIMESTAMP,  # DB server time
        ...
""")

# Then immediately passes exit_time to _write_completed_at()
_write_completed_at(ticker, direction, _ml_outcome, exit_price, exit_time)
CURRENT_TIMESTAMP in Postgres/SQLite is the DB server clock (UTC on Railway). datetime.now() is Python's local time (also UTC on Railway, but naive — no tzinfo). The exit_time passed to _write_completed_at() and used to write completed_at to ml_signals is the Python naive datetime — while exit_time in the positions table is the DB timestamp. These can diverge by up to several milliseconds, and will diverge by ±1 hour when DST transitions occur if Railway's TZ config ever changes. Any join or comparison between positions.exit_time and ml_signals.completed_at will silently misalign.

Fix: Use a single Python ET timestamp for everything:

python
from zoneinfo import ZoneInfo
exit_time = datetime.now(tz=ZoneInfo("America/New_York"))
cursor.execute(f"""
    UPDATE positions SET exit_time = {p}, ...
""", (exit_time, ...))
_write_completed_at(..., exit_time=exit_time)
10.C-3 — _update_performance_streak() is called twice in close_position() — streak can be double-incremented
File: position_manager.py

python
# First: manual increment
if final_pnl > 0:
    self.consecutive_wins += 1
    self.consecutive_losses = 0
else:
    self.consecutive_losses += 1
    self.consecutive_wins = 0

# Then immediately: recalculate from DB
closed_trades = self.get_todays_closed_trades()
self._update_performance_streak(closed_trades)
_update_performance_streak() recalculates consecutive_wins / consecutive_losses from scratch using reversed(trades). This completely overwrites the manual increment above — so the manual increment is dead code. However: _update_performance_streak() calls self.performance_multiplier = ... based on streak thresholds. But the thresholds use >= 3 and >= 2 — so a win that pushes the streak from 2→3 wins will set performance_multiplier = 1.25 correctly. The redundancy is currently harmless but becomes dangerous if get_todays_closed_trades() ever returns stale data (e.g., DB replication lag), causing the full recalculation to produce a lower streak than the manual count.

Fix: Remove the manual increment block entirely. Let _update_performance_streak() be the single source of truth. Add a unit test confirming streak is correct after 1, 2, 3, and 4 consecutive wins/losses.

10.C-4 — calculate_stop_loss_by_grade() can return a stop above entry for bull signals when ATR is very high
File: trade_calculator.py

python
atr_mult      = atr_multipliers.get(grade, 2.5)   # A+: 2.0, A: 2.5, A-: 3.0
stop_distance = atr * atr_mult

# Bull:
atr_stop  = entry_price - stop_distance
or_stop   = or_low * 0.999
stop_price = max(atr_stop, or_stop)   # ← takes the HIGHER of the two
max(atr_stop, or_stop) for a bull signal returns the stop closest to entry. If or_low is close to entry (tight OR) and ATR is large (high-vol day), or_stop = or_low * 0.999 ≈ entry_price, so stop_price ≈ entry_price. This means risk ≈ $0, triggering the if risk == 0: return False, 0.0 guard in validate_risk_reward() — every A+ signal on a high-vol tight-OR day is silently rejected. Worse: if or_low > entry_price (which can happen if entry is at the bottom of a wick below OR low), or_stop can exceed entry_price, producing a stop above entry for a bull trade — physically impossible.

Fix: After computing stop_price, assert invariants:

python
if direction == "bull" and stop_price >= entry_price:
    stop_price = entry_price - (atr * atr_mult)  # fall back to pure ATR
    logger.warning(f"[STOP] OR stop above entry for bull — falling back to ATR stop")
if direction == "bear" and stop_price <= entry_price:
    stop_price = entry_price + (atr * atr_mult)
    logger.warning(f"[STOP] OR stop below entry for bear — falling back to ATR stop")
🟡 Highs (6)
10.H-5 — evaluate_signal() duplicates position-count and duplicate-ticker checks already inside can_open_position() — two sources of truth
File: risk_manager.py

evaluate_signal() manually checks len(open_positions) >= max_pos and loops over positions for pos["ticker"] == ticker. can_open_position() (called inside open_position()) does the exact same checks. If the limits ever change, they must be updated in two places. More critically: evaluate_signal() reads max_open_positions from config directly (getattr(_cfg, "MAX_OPEN_POSITIONS", 5)) while can_open_position() reads from self.max_open_positions (set in __init__ from the same config). If the config value ever changes at runtime, the two checks will diverge.

Fix: Remove the position-count and duplicate-ticker checks from evaluate_signal(). Let can_open_position() be the single gate. evaluate_signal() should only handle pre-trade signal quality checks (circuit breaker, VIX, confidence, R:R).

10.H-6 — _load_session_state() silently swallows all exceptions — startup errors are invisible
File: position_manager.py

python
except Exception as e:
    print(f"[RISK] Session state load error: {e}")
If _load_session_state() fails (DB unreachable, schema mismatch, etc.), the constructor continues with self.positions = [] and self.account_size = config.ACCOUNT_SIZE. The scanner starts up, sees no open positions, and opens duplicate positions for anything that was open before the crash. The Phase C1 fix is fully bypassed with no observable error beyond a single print line.

Fix: Re-raise after logging, or set a self._startup_failed = True flag and check it in can_open_position():

python
except Exception as e:
    logger.critical(f"[RISK] FATAL: Session state load failed: {e}")
    self._startup_failed = True
Then in can_open_position():

python
if getattr(self, "_startup_failed", False):
    return False, "Position manager startup failed — trading disabled"
10.H-7 — apply_confidence_decay() returns a floor of 0.50 — a highly decayed signal can still pass a 0.65 threshold
File: trade_calculator.py

python
return max(adjusted_confidence, 0.50)
If a signal with base_confidence=0.90 waits 20+ candles (100+ minutes), the decay formula yields 0.90 * (1 - 0.75) = 0.225, but the floor clamps it to 0.50. The dynamic threshold for most signal/grade combinations is likely around 0.60–0.70 — so 0.50 will still be rejected. But if a threshold is 0.45 (aggressive config), a 100-minute-old signal passes. More fundamentally, the 0.50 floor is undocumented and inconsistent — it should be max_consecutive_losses-aware or at minimum logged clearly.

Fix: Remove the hard floor or make it configurable. Log when the floor is applied:

python
floored = max(adjusted_confidence, 0.0)
if floored != adjusted_confidence:
    logger.warning(f"[DECAY] Confidence floored at 0.0 (was {adjusted_confidence:.2f})")
return floored
Let the dynamic threshold decide the cutoff — don't bake a second gate into the decay function.

10.H-8 — get_adaptive_fvg_threshold() imports watchlist_funnel on every call — repeated module-level work in the hot path
File: trade_calculator.py

python
try:
    from app.screening.watchlist_funnel import get_watchlist_with_metadata
    _wl = get_watchlist_with_metadata(force_refresh=False)
    _rvol = next(...)
except Exception:
    _rvol = 1.0
This runs inside the scanner's per-ticker hot path. get_watchlist_with_metadata(force_refresh=False) still deserializes and returns the entire watchlist dict on every call. With 30 tickers × 5-second cycles, this function is called ~360 times/hour, deserializing the full watchlist each time just to look up one RVOL value.

Fix: Accept rvol: float = 1.0 as a parameter. Let the caller pass the RVOL from the already-fetched watchlist data in scanner.py. Remove the internal import entirely.

10.H-9 — calculate_volume_multiplier() silently returns 1.0 when breakout_idx < 20 — low-count bars produce false "standard volume" signal
File: trade_calculator.py

python
def calculate_volume_multiplier(bars, breakout_idx):
    if breakout_idx < 20 or len(bars) <= breakout_idx:
        return 1.0
Returning 1.0 when there are fewer than 20 prior bars causes get_adaptive_orb_threshold() to silently classify the breakout as "standard volume (1.0x)" and use the 0.10% threshold. In reality, there's no volume data to evaluate. Early-session OR breakouts (9:30–10:00 AM, < 12 bars) will always see breakout_idx < 20 and always get the middle-tier threshold regardless of actual volume. A very high-volume OR breakout at bar 8 would get the same threshold as a low-volume one.

Fix: Return None when insufficient history exists, and let get_adaptive_orb_threshold() handle the None case explicitly (log + use conservative 0.15% threshold, not the middle tier).

10.H-10 — PositionManager is instantiated at module import time as a global singleton — connects to DB on every Railway cold start before env is validated
File: position_manager.py, bottom of file

python
position_manager = PositionManager()
PositionManager.__init__() calls _initialize_database(), _close_stale_positions(), and _load_session_state() — all of which call get_conn(). This runs at import time, before validate_required_env_vars() in scanner.py has a chance to confirm DATABASE_URL is set. If DATABASE_URL is missing or malformed, the import raises OperationalError with a cryptic psycopg2 message instead of the clear env-var validation table.

Same pattern as 9.C-3 (health server). Both should be deferred to explicit initialize() calls.

Fix: Add a lazy-init pattern:

python
_position_manager_instance: Optional[PositionManager] = None

def get_position_manager() -> PositionManager:
    global _position_manager_instance
    if _position_manager_instance is None:
        _position_manager_instance = PositionManager()
    return _position_manager_instance
Import get_position_manager in risk_manager.py and call it lazily rather than importing the singleton.

🟠 Mediums (6)
ID	File	Issue
10.M-11	position_manager.py	generate_report() computes max_dd_pct as (account_size - intraday_high_water_mark) / intraday_high_water_mark. If the session is profitable, account_size > hwm, producing a positive drawdown percentage in the report — misleading. The correct formula is (hwm - account_size) / hwm.
10.M-12	position_manager.py	_scale_out() updates stop_price to entry_price (breakeven) in the DB but does NOT update self.positions cache's "stop" key before _invalidate_caches() is called. The in-memory cache still shows the old stop until the next get_open_positions() DB read. Any code reading self.positions directly between scale-out and the next cache refresh will use a stale stop.
10.M-13	risk_manager.py	_KILL_SWITCH_ACTIVE is read at module import time from os.getenv(). Changing the Railway env var requires a full redeploy to take effect — it cannot be toggled live. Add a _is_kill_switch_active() function that re-reads os.getenv("KILL_SWITCH") on each call so a Railway config change takes effect within the next scan cycle.
10.M-14	trade_calculator.py	get_next_1hour_target() assumes bars are 1-minute resolution (range(0, len(bars), 60)). The system uses 5-minute bars. range(0, len(bars), 60) on a 5m bar list would require 300 bars (25 hours of data) to produce one "hour bar" — this function always returns 0 in practice. It's referenced in the docstring as an "optional alternative" but is silently broken.
10.M-15	position_manager.py	check_circuit_breaker() uses self.session_starting_balance as the denominator for daily_loss_pct. On a Railway restart mid-session, session_starting_balance is re-initialized to config.ACCOUNT_SIZE (flat), not to the actual balance at session open. If the session opened with a $500 profit from yesterday, the denominator is wrong — the breaker fires at a different dollar threshold than intended.
10.M-16	trade_calculator.py	_filter_session_bars() compares dt.time() against SESSION_START/SESSION_END using <= on both ends. Bars timestamped at exactly 16:00:00 are included. A 4:00 PM bar is after-hours and should be excluded. Use t < SESSION_END.
🟢 Lows (4)
ID	File	Issue
10.L-17	position_manager.py	All print() calls should be logger.* — same pattern flagged in batches 8 and 9. The module uses print() exclusively with no structured logging.
10.L-18	risk_manager.py	evaluate_signal() does not check for RTH explicitly — it relies on can_open_position() inside open_position() to catch it. But evaluate_signal() is meant to be a fail-fast pre-gate. RTH check should be step 1.5 (after kill switch, before circuit breaker) so the rejection reason is clearly "Outside RTH" rather than leaking through to the execution layer.
10.L-19	position_manager.py	SECTOR_GROUPS contains "VOLATILITY": ["VIX", ...]. VIX is not a tradeable equity — it's an index. If VIX ever appears in the watchlist (e.g., from a screener returning index symbols), sector exposure math will treat it as a real position. Add a guard in _get_ticker_sector() to skip non-equity symbols.
10.L-20	trade_calculator.py	apply_confidence_decay() step table has a gap: for candles_waited = 11, decay = 0.10 + (11-10)*0.03 = 0.13. For candles_waited = 10, decay = (10-5)*0.02 = 0.10. The transition is smooth. But for candles_waited = 16, decay = 0.25 + (16-15)*0.05 = 0.30. A signal at 16 candles (80 minutes) is penalised 30% — that seems aggressive. Verify this is intentional and document it.
Priority Fix Order
10.C-1 — datetime.now() UTC bug — circuit breaker and streak reset at wrong time

10.C-2 — Dual timestamp sources for exit_time — positions vs ml_signals drift

10.C-4 — Stop above entry possible on bull A+ signals — silent rejection in high-vol tight-OR

10.H-6 — _load_session_state() swallows fatal exceptions — duplicate positions on restart

10.C-3 — Double-update of streak counters — remove dead manual increment

10.H-10 — PositionManager singleton connects to DB at import — blocks env validation

10.M-13 — Kill switch reads env at import — can't be toggled live on Railway

10.M-12 — self.positions cache shows stale stop after scale-out