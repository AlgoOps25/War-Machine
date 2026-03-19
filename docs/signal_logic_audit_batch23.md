All files read. Here is the full Batch 23 audit.

File: docs/signal_logic_audit_batch23.md
text
# Signal Logic Audit — Batch 23

**Date:** 2026-03-18
**Scope:** `app/ai/ai_learning.py`
**Total Findings:** 18 (1 Critical, 4 High, 8 Medium, 5 Low)

---

## 🔴 Criticals (1)

---

### 23.C-1 — `AILearningEngine` is instantiated at module level as `learning_engine = AILearningEngine()`. The constructor calls `_init_learning_table()` (DDL against Postgres) and `load_data()` (SELECT from Postgres) — two DB operations at import time. `ai_learning.py` is imported by `sniper.py` (via `from app.ai.ai_learning import compute_confidence`), which is imported by `scanner.py` at startup. This means **every Railway boot triggers DDL + a DB read before the scanner loop even starts**, while the connection pool may not be fully initialized. More critically: `learning_engine` is a module-level singleton — shared across all threads. `record_trade()` calls `self.data["trades"].append(...)` and `save_data()` with no thread lock. `sniper.py`'s ticker loop runs tickers sequentially via the watchdog executor — but if ever parallelized (the logical next step after fixing 20.C-1), concurrent `record_trade()` calls would corrupt `self.data["trades"]` with a race condition on the list append and the dict mutation in `update_performance_metrics()`.

**File:** `ai_learning.py` → module level, `record_trade()`, `update_performance_metrics()`

```python
learning_engine = AILearningEngine()   # DDL + DB read at import time
Fix (2 parts):

Lazy initialization — don't create learning_engine at import time. Use a get_learning_engine() factory that initializes on first call:

python
_learning_engine = None

def get_learning_engine() -> AILearningEngine:
    global _learning_engine
    if _learning_engine is None:
        _learning_engine = AILearningEngine()
    return _learning_engine
Add a threading.Lock to AILearningEngine and acquire it in record_trade(), update_performance_metrics(), and save_data().

🟡 Highs (4)
23.H-2 — grade_to_label() uses three hardcoded confidence thresholds (0.80, 0.65, 0.50) that do not match the _GRADE_BASE midpoints. According to _GRADE_BASE:
A+ midpoint = 0.90 → after tf_mult=1.05 on 5m = 0.945

A midpoint = 0.85

A- midpoint = 0.80

But grade_to_label(0.80) returns "A+" — an A- base confidence maps to the "A+" label. A signal graded A- with a 5m timeframe (compute_confidence("A-", "5m") = 0.84) will grade_to_label(0.84) → "A+". The label is used in Discord alerts and logging. Every 5m A- signal is reported to Discord as "A+" quality. This creates a persistent false impression of signal quality.

File: ai_learning.py → grade_to_label()

python
if confidence >= 0.80:
    return "A+"    # ← A- base score (0.80) maps here
Fix: Align thresholds with _GRADE_BASE midpoints:

python
def grade_to_label(confidence: float) -> str:
    if confidence >= 0.875:   return "A+"
    elif confidence >= 0.825: return "A"
    elif confidence >= 0.770: return "A-"
    elif confidence >= 0.710: return "B+"
    elif confidence >= 0.650: return "B"
    elif confidence >= 0.590: return "B-"
    elif confidence >= 0.545: return "C+"
    elif confidence >= 0.500: return "C"
    elif confidence >= 0.450: return "C-"
    else:                     return "reject"
23.H-3 — load_data() merges loaded DB data into default_data using {**default_data, **d} — a shallow merge. If the stored d["confirmation_weights"] dict is missing a key (e.g., an old save before "options_flow" was added), {**default_data, **d} replaces the entire confirmation_weights with the stored version, losing the new default key. Example: DB has {"confirmation_weights": {"vwap": 1.2, "prev_day": 0.9}} → merged result is {"confirmation_weights": {"vwap": 1.2, "prev_day": 0.9}} with "institutional" and "options_flow" silently dropped. optimize_confirmation_weights() then only updates the two keys it finds, leaving the others absent. Any code doing self.data["confirmation_weights"]["options_flow"] will raise KeyError.
File: ai_learning.py → load_data()

python
return {**default_data, **d}   # shallow merge — nested dicts replaced entirely
Fix: Deep-merge nested dicts:

python
merged = {**default_data, **d}
for key in default_data:
    if isinstance(default_data[key], dict) and isinstance(d.get(key), dict):
        merged[key] = {**default_data[key], **d[key]}
return merged
23.H-4 — save_data() calls datetime.now().isoformat() (no timezone) for last_update. On Railway (UTC), this stores a UTC-naive timestamp. load_data() reads it back as a plain string and never parses it — so the timezone error is currently inert. But last_update is the only field that could be used for "was the model updated today?" logic — if a future gate uses last_update to skip retraining, the UTC naive string will be compared against ET-aware datetimes and either always match or always mismatch depending on implementation. Should use datetime.now(ZoneInfo("America/New_York")).isoformat() consistent with the rest of the system.
File: ai_learning.py → save_data()

python
self.data["last_update"] = datetime.now().isoformat()   # UTC naive on Railway
23.H-5 — optimize_confirmation_weights() computes a new_weight = win_rate / baseline_wr and stores it with no bounds clamping. If baseline_wr is very low (e.g., a bad losing streak gives baseline_wr = 0.15) and a confirmation type has a high win rate (e.g., win_rate = 0.80), the weight becomes 0.80 / 0.15 = 5.33. This unbounded weight is then stored in confirmation_weights and will be multiplied against confidence values elsewhere in the pipeline. A weight of 5.33x applied to confidence (even multiplied by other sub-1.0 factors) will blow out the confidence ceiling gate and produce nonsensical signal scores during a recovery period after a bad day.
File: ai_learning.py → optimize_confirmation_weights()

python
new_weight = win_rate / baseline_wr   # no bounds — can exceed 5x on bad days
Fix: Clamp to a sane range (e.g., 0.5–2.0):

python
new_weight = round(min(max(win_rate / baseline_wr, 0.5), 2.0), 2)
🟠 Mediums (8)
ID	File	Issue
23.M-6	ai_learning.py	compute_confidence() accepts ticker as a parameter "reserved for future per-ticker tuning" but never uses it. The parameter creates an implicit API contract — every caller in sniper.py passes ticker=ticker expecting per-ticker adjustment to happen. It silently does nothing. Either implement it (use learning_engine.get_ticker_confidence_multiplier(ticker)) or remove the parameter and update call sites.
23.M-7	ai_learning.py	_GRADE_BASE and _TF_MULTIPLIER are module-level constants but identical values are also defined in the now-deleted confidence_model.py shim (per sniper.py comments). If any import still resolves confidence_model.py before it was deleted, it would use that shim's values. The shim was described as importing from ai_learning — verify no stale shim file remains in the repo that could shadow these constants.
23.M-8	ai_learning.py	self.data["trades"] grows unbounded — every record_trade() appends to the list which is persisted to the DB ai_learning_state JSONB column. After 6 months of trading (est. 3-5 trades/day × 252 days ≈ 1,000 trades), the JSONB blob approaches 1MB+. Postgres JSONB has no hard limit but large blobs degrade index performance. optimize_fvg_threshold() already only uses [-100:] (last 100 trades). The full list beyond last 100 is never used for optimization. Should prune to last N (e.g., 500) on each save.
23.M-9	ai_learning.py	get_options_flow_weight() imports options_dm inside the function on every call. In a 50-ticker scan cycle, this is 50 deferred import lookups per cycle. Python's import system caches the module, so it is not 50 disk reads — but the from app.options.options_data_manager import options_dm attribute lookup still executes 50 times. Move to module-level try/except stub.
23.M-10	ai_learning.py	optimize_confirmation_weights() checks len(trades_with_confirmations) < 20 but uses self.data["trades"] (all-time trades) for baseline_wr. After 200 trades, baseline_wr reflects a long-term win rate that may differ significantly from recent performance. The weight optimization should use a rolling window (e.g., last 100 trades) consistent with optimize_fvg_threshold().
23.M-11	ai_learning.py	_init_learning_table() silently returns if not db_connection.USE_POSTGRES — no SQLite/JSON schema initialization. On a local dev environment with USE_POSTGRES=False, the JSON file is used but no schema validation occurs. If the JSON file is malformed or missing a required key, load_data() returns default_data silently. No warning is logged.
23.M-12	ai_learning.py	get_ticker_confidence_multiplier() requires perf["count"] >= 5 before applying a multiplier. With count < 5 it returns 1.0 (neutral). This is correct — but there is no decay over time. A ticker with count=5 trades all from 6 months ago (stale data) gets the same multiplier as one with 5 trades this week. Should apply a recency decay or minimum date filter.
23.M-13	ai_learning.py	AILearningEngine.__init__() calls both _init_learning_table() and load_data() in sequence. If _init_learning_table() raises a non-caught exception (e.g., Postgres connection refused), the exception propagates out of __init__ — but because 23.C-1's fix is not yet applied, learning_engine = AILearningEngine() at module level would cause the entire ai_learning module to fail to import, breaking sniper.py's import of compute_confidence. _init_learning_table() should be wrapped in try/except inside __init__.
🟢 Lows (5)
ID	File	Issue
23.L-14	ai_learning.py	MIN_CONFIDENCE = 0.50 is defined here. Same constant defined in config.py and clamped in sniper.py (Batch 19, 19.M-16). Three definitions — import from config.py.
23.L-15	ai_learning.py	generate_performance_report() builds a string with repeated += in a loop — O(N²) string concatenation. For 200 grade entries, negligible. For future growth, use io.StringIO or "".join([...]).
23.L-16	ai_learning.py	record_trade() prints [AI] Trade recorded: ... to stdout. All other modules use logger. Inconsistent logging pattern — replace with logger.info().
23.L-17	ai_learning.py	load_data() has a commented-out fallback: after the Postgres try/except it falls through to return default_data — but the comment says "Error loading from PostgreSQL" and falls through. This means a Postgres connection error silently produces default data with no retry. Should at minimum log a WARNING so Railway surfaces the degradation.
23.L-18	ai_learning.py	_GRADE_BASE comment says "A+/A/A- midpoints align with original learning_policy values". learning_policy.py was deleted (now consolidated here per the module docstring). The comment references a deleted module — update to self-document the source of these values.
Priority Fix Order
23.C-1 — Module-level learning_engine = AILearningEngine() — DDL + DB read at import time, no thread safety on mutations

23.H-5 — Unbounded confirmation weight (win_rate / baseline_wr) — weight can reach 5x+ during recovery from bad day, blowing out confidence scores

23.H-3 — Shallow merge in load_data() — missing nested keys silently dropped on DB restore, KeyError risk in weight optimization

23.H-2 — grade_to_label() thresholds misaligned — A- signals reported as "A+" in Discord alerts

23.M-6 — ticker parameter in compute_confidence() silently does nothing — callers expect per-ticker adjustment, get none

23.M-8 — self.data["trades"] unbounded growth — JSONB blob degrades over time, prune to last 500

23.M-13 — _init_learning_table() not wrapped in try/except inside __init__ — connection failure kills ai_learning import → breaks compute_confidence in sniper.py

