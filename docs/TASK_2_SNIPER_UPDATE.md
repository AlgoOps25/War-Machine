# Task 2 Complete - Sniper.py Integration Instructions

## Files Already Pushed to Repo

1. `app/filters/early_session_disqualifier.py` - Gate logic module ✅
2. `utils/config.py` - Updated MIN_OR_RANGE_PCT = 0.03 (3%) ✅

## Remaining Manual Edit Required

**File:** `app/core/sniper.py`

---

## Change #1: Add Import (after line 41)

### Find this section (around line 41):

```python
from utils import config
from app.mtf.bos_fvg_engine import scan_bos_fvg, is_force_close_time

# ══════════════════════════════════════════════════════════════════════════════
# PHASE 4 INTEGRATION - Signal Analytics & Performance Monitoring
# ══════════════════════════════════════════════════════════════════════════════
```

### Insert BEFORE the "PHASE 4 INTEGRATION" comment block:

```python
# ══════════════════════════════════════════════════════════════════════════════
# TASK 2 - EARLY SESSION DISQUALIFIER
# ══════════════════════════════════════════════════════════════════════════════
from app.filters.early_session_disqualifier import should_skip_cfw6_or_early
print("[SNIPER] ✅ Task 2: Early-session CFW6_OR gate enabled (blocks narrow ORs before 9:40 AM)")

```

---

## Change #2: Add Gate Check (in process_ticker, around line 1746)

### Find this exact code block (in the FRESH SCAN section):

```python
            else:
                print(f"[{ticker}] OR: ${or_low:.2f}—${or_high:.2f} ({or_range_pct:.2%})")
                direction, breakout_idx = detect_breakout_after_or(bars_session, or_high, or_low)
                if direction:
```

### Replace with:

```python
            else:
                print(f"[{ticker}] OR: ${or_low:.2f}—${or_high:.2f} ({or_range_pct:.2%})")
                
                # ════════════════════════════════════════════════════════════════════════
                # TASK 2: Early-session CFW6_OR gate - block narrow ORs before 9:40 AM
                # ════════════════════════════════════════════════════════════════════════
                now_et = _now_et()
                if should_skip_cfw6_or_early(or_range_pct, now_et):
                    print(
                        f"[{ticker}] 🚫 EARLY SESSION GATE: OR {or_range_pct:.2%} < "
                        f"{config.MIN_OR_RANGE_PCT:.1%} before 9:40 AM — CFW6_OR blocked, "
                        f"trying intraday BOS"
                    )
                    # Don't return - allow fall-through to intraday BOS path below
                else:
                    # Gate passed or inactive - proceed with OR path
                    direction, breakout_idx = detect_breakout_after_or(bars_session, or_high, or_low)
                    if direction:
```

**IMPORTANT:** Keep ALL the code that follows the `if direction:` line intact (the zone_low/zone_high detection and watching_signals logic).

---

## Verification Checklist

After making changes, verify:

- [ ] Import added after line 41 (before PHASE 4 comment block)
- [ ] Print statement confirms gate is enabled on startup
- [ ] Gate check added in process_ticker around line 1746
- [ ] Gate only blocks CFW6_OR path, allows intraday BOS fallback
- [ ] Original OR breakout detection logic preserved inside else block
- [ ] No syntax errors (check indentation matches surrounding code)

---

## Expected Behavior

### Before 9:40 AM ET:
- OR < 3% → Block CFW6_OR path, try intraday BOS
- OR ≥ 3% → Allow CFW6_OR path normally

### After 9:40 AM ET:
- All OR sizes allowed (gate inactive)

### Log Output Examples:

```
[TICKER] 🚫 EARLY SESSION GATE: OR 2.1% < 3.0% before 9:40 AM — CFW6_OR blocked, trying intraday BOS
[TICKER] OR: $45.20—$46.80 (3.5%) → proceeds to detect_breakout_after_or()
```

---

## Testing

Run the test cases in early_session_disqualifier.py:

```bash
python3 app/filters/early_session_disqualifier.py
```

### Expected output:

```
Test 1 (9:35 AM, OR=2%): Block=True (expected True)
Test 2 (9:35 AM, OR=4%): Block=False (expected False)
Test 3 (9:45 AM, OR=2%): Block=False (expected False)
Test 4 (9:40 AM, OR=2%): Block=False (expected False)
```

---

## Commit Message (after manual edit)

```
Task 2 Complete: Early-session CFW6_OR disqualifier integrated

Final integration of app/filters/early_session_disqualifier.py into sniper.py:
- Added import statement after line 41
- Added gate check in process_ticker() around line 1746
- Gate blocks CFW6_OR signals before 9:40 AM when OR < 3%
- Allows intraday BOS path as fallback when OR path blocked
- All signals allowed after 9:40 AM regardless of OR size

Fixes: Premature CFW6_OR entries during choppy OR formation periods
Status: Task 2 fully integrated and production-ready
```

---

## Implementation Summary

### Gate Logic:

1. **Time Check:** Is current time before 9:40 AM ET?
2. **Range Check:** Is OR range < 3%?
3. **Decision:**
   - YES to both → Block CFW6_OR, allow intraday BOS fallback
   - NO to either → Allow CFW6_OR path normally

### Integration Points:

- **Import:** Line 41 (after MTF imports, before Phase 4)
- **Gate Check:** Line 1746 (in process_ticker, FRESH SCAN section)
- **Config:** MIN_OR_RANGE_PCT = 0.03 (already updated in utils/config.py)

### Files Modified:

- ✅ `app/filters/early_session_disqualifier.py` (NEW)
- ✅ `utils/config.py` (UPDATED)
- ⏳ `app/core/sniper.py` (PENDING - manual edit required)

---

## Contact

Author: Michael Perez  
Date: 2026-03-03  
Task: #2 - Early-session CFW6_OR disqualifier