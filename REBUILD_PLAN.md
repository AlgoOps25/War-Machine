# War Machine — Signal Rebuild Plan
> **Session started: 2026-03-26**
> **This document is the living audit and build spec for the FVG+BOS+CRT rebuild.**
> Update after every session. Never delete completed sections — append ✅ and date.

---

## 1. Goal

Build a **perfect, production-ready FVG+BOS and CRT signal system** for live intraday trading using:
- **EODHD All-World Extended + US Options API** (already paid for — maximize usage)
- **Multi-timeframe scanning**: 1m, 2m, 3m, 5m — 5m signal > 1m signal in confidence
- **EODHD Technical Indicators** pulled live (ADX, RSI, MACD, EMA) as confidence modifiers
- **EODHD US Options chain** for full contract recommendation per signal
- **Manual execution on Robinhood** — system is alert-only, no auto-execution
- **Discord alert** shows: direction, entry, stop, targets, confirmation grade, options contract, all confidence factors

---

## 2. EODHD API Audit — What You Have vs. What's Used

You own the **EOD+Intraday All-World Extended + US Stock Options** plan.

| EODHD Endpoint | Current Status | Action Needed |
|---|---|---|
| `/api/intraday/{ticker}.US` (1m bars) | ✅ Used — WS-first, REST fallback | Keep. 2m/3m resampled from 1m in-process. |
| `/api/eod/{ticker}.US` (daily OHLC) | ✅ Used — prior-day context | Keep. |
| `/api/real-time/{ticker}.US` (snapshots) | ✅ Used — bulk 50-ticker quotes | Keep. |
| WebSocket feed (`ws_feed.py`) | ✅ Used — live bar stream | Keep. |
| **`/api/technical/{ticker}.US`** (RSI, MACD, ADX, etc.) | ❌ **NOT used live** | **Build `eodhd_indicators.py`** — fetch live per signal |
| **`/api/options/{ticker}.US`** (US Options chain + Greeks) | ❌ **NOT used** | **Build `eodhd_options.py`** — replace Tradier dependency |
| `/api/fundamentals/{ticker}.US` | ❌ Not used | Optional future use (float, sector) |

**Key finding:** The EODHD Technical Indicator API and Options API are unused on a plan already paid for.
All indicators (RSI, MACD, ADX, EMA) are currently computed locally from raw bars in `app/indicators/`.
Options were planned for Tradier but EODHD provides this natively on the current plan.

---

## 3. Full File Audit — All 4 Core Files

### 3.1 `scanner.py` — ✅ NO CHANGES NEEDED

**What it does:** Outer scan loop. Builds watchlist, manages WS subscriptions, calls `process_ticker(ticker)` serially for each ticker in the watchlist each cycle.

**Key findings:**
- Scan intervals are correct: 5s (9:30–9:40 OR window), 45s (9:40–11:00), 180s (midday), 60s (14:00–15:30), 45s (power hour)
- Watchlist sizes are correct: 30 at open, 50 mid-session, 35 close
- `ThreadPoolExecutor(max_workers=1)` with 45s watchdog timeout per ticker — serial, correct
- WS feeds, backfill, EOD tasks all wired correctly
- **Zero changes needed to scanner.py**

---

### 3.2 `sniper.py` — ❌ NEEDS FIXES + NEW WIRING

**What it does:** `process_ticker(ticker)` — the per-ticker signal engine. Three scan paths:
- **Path A (ORB):** Opening range breakout → FVG after break → `_run_signal_pipeline()`
- **Path B (Intraday BOS+FVG):** `scan_bos_fvg()` → `get_full_mtf_analysis()` → `_run_signal_pipeline()`
- **Path C (VWAP Reclaim):** `detect_vwap_reclaim()` → `_run_signal_pipeline()`

**Bugs found:**

| # | Bug | Location | Severity |
|---|---|---|---|
| B1 | `get_full_mtf_analysis(bars_5m=bars_session)` passes 1m session bars as `bars_5m` parameter | sniper.py ~line 300 | 🔴 Critical — MTF analysis is completely broken |
| B2 | `_resample_bars()` exists in sniper.py (~line 175) but is never called | sniper.py | 🟡 Dead code — needed for 2m/3m bars |
| B3 | No CRT scan anywhere in process_ticker() | sniper.py | 🔴 Missing feature |
| B4 | No EODHD indicator fetch anywhere in process_ticker() | sniper.py | 🟡 Missing feature |
| B5 | `options_rec` is always None passed to `_run_signal_pipeline()` | sniper.py | 🟡 Missing feature |

**Changes needed:**
1. Fix B1: resample bars correctly before calling `get_full_mtf_analysis()`
2. Use `_resample_bars()` to build 2m and 3m bar lists
3. Call `scan_bos_fvg()` on 1m, 2m, 3m, 5m bars; apply TF weight multipliers; pick highest-confidence signal
4. Call `scan_crt()` (new) on 1m, 2m, 3m, 5m bars; same TF weight logic
5. Merge BOS+FVG and CRT signals (same direction = confluence boost)
6. Call `eodhd_indicators.get_indicators(ticker)` (new) and compute confidence delta
7. Pass `options_rec` from `eodhd_options.get_options_rec(ticker, direction)` (new) into `_run_signal_pipeline()`

---

### 3.3 `bos_fvg_engine.py` — ✅ FULLY TIMEFRAME-AGNOSTIC, NO CHANGES NEEDED

**What it does:** `scan_bos_fvg(ticker, bars, fvg_min_pct, require_confirmation)` — takes any list of OHLCV bar dicts and detects the BOS+FVG pattern on that bar list.

**Critical finding: The engine is 100% bar-list agnostic.** It does not hardcode 1m anywhere. Every function (`find_swing_points`, `detect_bos`, `find_fvg_after_bos`, `check_fvg_entry`) takes a `List[Dict]` with keys `open/high/low/close/volume/datetime`. If you pass 5m bars, it runs on 5m bars. If you pass 2m bars, it runs on 2m bars.

**The only time-aware function is `is_valid_entry_time(bar)`** which checks `bar["datetime"].time()` against `9:30–15:45 ET`. This works correctly on any timeframe because the datetime is preserved in resampled bars.

**The full signal dict returned by `scan_bos_fvg()` includes:**
```python
{
    "ticker":       str,
    "direction":    "bull" | "bear",
    "bos_idx":      int,          # bar index in the provided bar list
    "entry":        float,        # current bar open
    "stop":         float,        # just beyond FVG extreme
    "t1":           float,        # 1.5R
    "t2":           float,        # 2.5R
    "risk":         float,
    "fvg_low":      float,
    "fvg_high":     float,
    "fvg_size_pct": float,
    "bos_price":    float,
    "bos_strength": float,        # % strength of break
    "entry_type":   "BOS+FVG",
    "signal_time":  datetime,
    "confirmed_at": datetime,
    "entry_at":     datetime,
    "confirmation": "A+" | "A" | "A-" | None,
    "conf_score":   100 | 85 | 70 | 0,
    "candle_type":  str
}
```

**Confirmation grading (Nitro Trades 3-tier model already implemented):**
- **A+ (100pts):** Strong directional candle, minimal wick (<20% of body)
- **A (85pts):** Opens counter-trend then flips back with wick ≥ 30% of range
- **A- (70pts):** Rejection wick ≥ 50% of range but doesn't flip

**Conclusion:** `scan_bos_fvg()` can be called directly on 1m, 2m, 3m, and 5m bar lists today with zero modifications. **Do not touch this file.**

---

### 3.4 `sniper_pipeline.py` — ✅ MOSTLY READY, MINOR ADDITIONS NEEDED

**What it does:** `_run_signal_pipeline()` — the 14-gate validation and arming pipeline. Called after a signal is detected in `sniper.py`.

**Gate sequence (confirmed):**
1. RVOL fetch
2. TIME gate (blocks after 11:00 AM — **note: will need to review if CRT/BOS on 5m should trade later**)
3. RVOL floor gate
4. RVOL ceiling gate
5. VWAP gate
6. Dead zone gate
7. GEX pin zone gate
8. Cooldown gate
9. CFW6 confirmation (skippable via `skip_cfw6_confirmation=True`)
10. MTF trend bias (builds 15m bars internally via `_resample_bars()` — **note: `_resample_bars` is duplicated here too, exists in both sniper.py AND sniper_pipeline.py**)
11. SMC enrichment (sd_zone, liquidity_sweep, order_block)
12. SignalScorecard — `build_scorecard()` accepts `options_rec` parameter already
13. compute_stop_and_targets()
14. `arm_ticker()` — accepts `options_rec` parameter already

**Key findings:**

| # | Finding | Impact |
|---|---|---|
| F1 | `options_rec` parameter already exists in `_run_signal_pipeline()` signature (FIX B) | ✅ Just need to pass a real value from sniper.py instead of None |
| F2 | `options_rec` is already forwarded to `build_scorecard()` and `arm_ticker()` | ✅ Pipeline is options-rec ready end-to-end, just starved of real data |
| F3 | `_resample_bars()` is **duplicated** here AND in sniper.py | 🟡 Cleanup: move to a shared util or use sniper.py’s copy |
| F4 | TIME gate hard-blocks at 11:00 AM — all signals after 11 AM are dropped | 🔲 Decision needed: should CRT/BOS 5m signals trade in PM session? |
| F5 | `arm_ticker()` is called with `options_rec=options_rec` — options_rec flows all the way through | ✅ Confirmed: just need to build eodhd_options.py and pass rec in |
| F6 | SMC enrichment is a try/except import — graceful no-op if modules missing | ✅ Safe |

**Changes needed to sniper_pipeline.py:**
- None required for the CRT/BOS MTF rebuild — the pipeline already accepts `options_rec`
- Optional cleanup: remove duplicate `_resample_bars()` and import from shared location
- Optional: make TIME gate configurable (or extend to 13:00 for PM session CRT signals)

---

## 4. Signal Architecture — Current vs. Target

### Current State (broken)
```
scanner.py:start_scanner_loop()
  → for ticker in watchlist:
      process_ticker(ticker)                       [sniper.py]
        → Path A: ORB path
            detect_breakout_after_or()             [opening_range.py] ← OR high/low breakout
            detect_fvg_after_break()               [opening_range.py] ← 1m bars only
            _run_signal_pipeline(options_rec=None) [sniper_pipeline.py]
        → Path B: Intraday BOS+FVG
            scan_bos_fvg(bars_1m)                  [bos_fvg_engine.py] ✔ correct
            get_full_mtf_analysis(bars_5m=bars_1m) [mtf_fvg_priority.py] ❌ BUG: 1m bars labeled as 5m
            _run_signal_pipeline(options_rec=None) [sniper_pipeline.py] ❌ options_rec always None
        → Path C: VWAP reclaim
            detect_vwap_reclaim()                  [vwap_reclaim.py]
            _run_signal_pipeline(options_rec=None) [sniper_pipeline.py]
```

### Target State (correct)
```
scanner.py:start_scanner_loop()                    [UNCHANGED]
  → for ticker in watchlist:
      process_ticker(ticker)                        [sniper.py — MODIFIED]

        → STEP 0: Build all timeframe bar lists
            bars_1m = bars_session (already have)
            bars_2m = _resample_bars(bars_1m, 2)   [already in sniper.py — just call it]
            bars_3m = _resample_bars(bars_1m, 3)
            bars_5m = get_today_session_bars_5m()   [from data_manager] OR _resample_bars(bars_1m, 5)

        → STEP 1: Fetch live indicators (cached, TTL=5m)
            indicators = eodhd_indicators.get_indicators(ticker)  [NEW]
            ind_boost  = _compute_indicator_boost(indicators, direction)

        → Path A: ORB path                          [UNCHANGED — keep exactly as-is]

        → Path B: MTF BOS+FVG (FIXED)
            sig_1m = scan_bos_fvg(ticker, bars_1m)  score * 1.00
            sig_2m = scan_bos_fvg(ticker, bars_2m)  score * 1.15
            sig_3m = scan_bos_fvg(ticker, bars_3m)  score * 1.25
            sig_5m = scan_bos_fvg(ticker, bars_5m)  score * 1.50
            bos_signal = _pick_best_mtf_signal([sig_1m, sig_2m, sig_3m, sig_5m])
            # confluence boost if 2+ TFs agree on same direction: +0.10

        → Path D: MTF CRT scan (NEW)
            crt_1m = scan_crt(ticker, bars_1m)      score * 1.00  [crt_engine.py]
            crt_2m = scan_crt(ticker, bars_2m)      score * 1.15
            crt_3m = scan_crt(ticker, bars_3m)      score * 1.25
            crt_5m = scan_crt(ticker, bars_5m)      score * 1.50
            crt_signal = _pick_best_mtf_signal([crt_1m, crt_2m, crt_3m, crt_5m])

        → STEP 2: Merge signals
            If both bos_signal and crt_signal fire same direction:
              use higher conf_score + 0.05 confluence bonus
              signal_source = "BOS+FVG+CRT"
            Elif only bos_signal: use bos_signal, source = "BOS+FVG"
            Elif only crt_signal: use crt_signal, source = "CRT"
            Elif neither: return (no signal)
            Elif conflict (opposite directions): return (no signal)

        → STEP 3: Apply indicator boost
            final_signal["conf_score"] += ind_boost  (capped at +0.15 / -0.10)

        → STEP 4: Fetch options rec
            options_rec = eodhd_options.get_options_rec(ticker, direction)  [NEW]

        → Path C: VWAP reclaim                      [UNCHANGED]

        → _run_signal_pipeline(..., options_rec=options_rec)  [sniper_pipeline.py — already accepts it]
            → arm_ticker(..., options_rec=options_rec)
                → discord alert with full options rec  [discord_helpers.py — UPDATED]
```

---

## 5. CRT (Candle Range Theory) — Strategy Specification

### Source
Nitro Trades YouTube series:
- [This ONE Candle Will Change Your Trading | CRT](https://youtu.be/v-Au32NSfS8?si=jWvlO3Lh2AxVKl-r)
- [The ONLY Trading Strategy You Need For Futures | CRT](https://youtu.be/MJsEFxo1Apg?si=Uq7TFZxt-xbDhW-Q)
- [The "ONE CANDLE" Trading Strategy That Works Everyday | CRT](https://youtu.be/rQzxUldYKuk?si=6t3c7gyygZx7pu3Z)

### CRT Pattern Rules (Nitro Trades / Community Consensus)

CRT is a **3-candle AMD sequence** (Accumulation → Manipulation → Distribution):

#### Candle 1 — The Range Candle
- Establishes the range: defines `C1_HIGH` and `C1_LOW`
- This is the "parent candle" whose extremes will be swept
- Can be any size; larger range = larger potential move

#### Candle 2 — The Manipulation Candle (Sweep)
- **MUST** breach one extreme of Candle 1 (sweep the high OR low)
- **MUST** close BACK INSIDE Candle 1's range (body closes within C1_HIGH–C1_LOW)
- If close is OUTSIDE C1 range → legitimate breakout, NOT a CRT → discard
- The sweep = stop hunt / liquidity grab
- **Sweep direction determines trade direction:**
  - Sweep HIGH → bearish CRT
  - Sweep LOW  → bullish CRT

#### Candle 3 — The Distribution / Entry Candle
- Price moves toward the **opposite** extreme of C1
- **Entry trigger (preferred):** FVG on lower timeframe after C2 sweep closes back inside C1
- **Stop:** Beyond the C2 sweep wick extreme
- **T1:** Opposite extreme of C1
- **T2:** Extension beyond C1

#### Validity Rules
- C2 close MUST be within C1 range — hard invalidation if not
- FVG left by C2 sweep increases probability significantly
- Nested CRT (higher TF pattern + lower TF entry) = highest probability
- CRT without imbalance = weak — lower confidence score

#### Relationship to BOS+FVG
- CRT is the **setup** (identifies manipulation + direction)
- FVG is the **entry mechanism** (precise entry into the imbalance after the sweep)
- Both complementary — run both engines, merge scores

---

## 6. Multi-Timeframe Signal Scoring

### Bar Construction
- 1m bars: native from EODHD WebSocket + REST (already in `bars_session`)
- 2m bars: `_resample_bars(bars_1m, 2)` — **already in sniper.py, just call it**
- 3m bars: `_resample_bars(bars_1m, 3)` — same
- 5m bars: already materialized in `intraday_bars_5m` table in DB; fallback to `_resample_bars(bars_1m, 5)`

### Signal Confidence Weight by Timeframe
| Timeframe | BOS+FVG Weight | CRT Weight | Notes |
|---|---|---|---|
| 1m | 1.00× | 1.00× | Base |
| 2m | 1.15× | 1.15× | Minor noise filter |
| 3m | 1.25× | 1.25× | Good intraday |
| 5m | 1.50× | 1.50× | Strongest signal |

**Confluence rule:** Same direction signal on 2+ timeframes simultaneously → +0.10 boost.
**BOS+FVG + CRT same direction:** additional +0.05 boost.

---

## 7. EODHD Indicator Integration — Live Confidence Modifiers

### Endpoint
`GET https://eodhd.com/api/technical/{ticker}.US?function={indicator}&period={n}&api_token={key}&fmt=json`

### Indicators to Pull Per Signal

| Indicator | EODHD Function | Purpose | Confidence Rule |
|---|---|---|---|
| ADX | `adx` | Trend strength | ADX > 25 → +0.05; ADX < 20 → −0.03 |
| RSI (14) | `rsi` | Momentum | Bull: RSI 40–65 → +0.03; RSI > 75 → −0.05; Bear: RSI 35–60 → +0.03; RSI < 25 → −0.05 |
| MACD | `macd` | Momentum alignment | Crossover aligns with direction → +0.04 |
| EMA 9/21 | `ema` | Trend bias | Price > EMA9 > EMA21 for bull → +0.03; inverse for bear |

**Max total boost: +0.15. Max penalty: −0.10. Never hard-block a signal.**

---

## 8. Options Recommendation — EODHD Options API

### Endpoint
`GET https://eodhd.com/api/options/{ticker}.US?api_token={key}&fmt=json`

### Contract Selection Logic (per signal)
1. Direction: Bull → CALL; Bear → PUT
2. DTE target: 0–2 DTE (0DTE preferred)
3. Delta: 0.40–0.60
4. OI > 100; bid/ask spread < 15% of mid
5. Flag if IV rank > 80
6. Output: strike, expiration, delta, gamma, IV, bid/ask, mid price

### Discord Alert Format (confirmed target)
```
🔴 BEAR SIGNAL — TSLA [A+ Confirmation]
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
📊 SIGNAL: BOS+FVG+CRT [5m] — Confluence
⏱ Timeframes: 5m 🟢 | 3m 🟢 | 1m 🟡
📈 Entry: $287.40 | Stop: $289.80 | T1: $283.20 | T2: $280.00
⚡ Conf Score: 87/100

🧠 SMC Context: CHoCH:REVERSAL | OB@289.00-290.50 | PHASE:MARKDOWN
📉 Indicators: ADX 31.2 (trending) | RSI 62.1 (aligned) | MACD bearish cross

🎯 OPTIONS RECOMMENDATION
   PUT $287.50 exp 2026-03-26 (0DTE)
   Delta: -0.48 | Gamma: 0.12 | IV: 42.3%
   Bid/Ask: $1.85 / $1.95 | Mid: $1.90
   OI: 1,842 | Spread: 5.1% ✅
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
⚠️ Manual execution on Robinhood
```

---

## 9. Files to Build / Modify

### New Files (3)
| File | Purpose |
|---|---|
| `app/data/eodhd_indicators.py` | EODHD live indicator fetcher. Calls `/api/technical/` for ADX, RSI, MACD, EMA. Per-ticker TTL cache (5 min). Returns normalized dict. |
| `app/signals/crt_engine.py` | CRT pattern detector. Takes any `List[Dict]` OHLCV bars (timeframe-agnostic like bos_fvg_engine). Scans last N bars for valid C1/C2/C3 AMD pattern. Returns signal dict matching bos_fvg_engine output schema. |
| `app/options/eodhd_options.py` | EODHD options chain fetcher. Calls `/api/options/`. Selects best contract by DTE, delta, OI, spread. Returns `options_rec` dict consumed by arm_ticker + discord. |

### Modified Files (2)
| File | Changes |
|---|---|
| `app/core/sniper.py` | (1) Fix MTF bug (pass correct bars to `get_full_mtf_analysis`); (2) Call `_resample_bars()` for 2m/3m; (3) Call `scan_bos_fvg()` on all 4 TFs; (4) Call `scan_crt()` on all 4 TFs; (5) Merge BOS+FVG + CRT with confluence scoring; (6) Fetch indicators + compute boost; (7) Fetch options_rec; (8) Pass all to `_run_signal_pipeline()` |
| `app/notifications/discord_helpers.py` | Update signal alert embed to include: signal source (BOS+FVG/CRT/both), active timeframes, indicator values, full options_rec block |

### Files NOT to touch (confirmed)
| File | Reason |
|---|---|
| `scanner.py` | Scan loop is correct. Zero changes. |
| `bos_fvg_engine.py` | Fully timeframe-agnostic, all logic correct. Zero changes. |
| `sniper_pipeline.py` | Already accepts and forwards `options_rec`. Zero changes required. |
| `smc_engine.py` | SMC enrichment is correct. Zero changes. |
| All `filters/` modules | Correct and well-tested. Zero changes. |
| All `validation/` modules | Correct. Zero changes. |
| `data_manager.py` | `_resample_bars()` already in sniper.py. Zero changes needed. |

---

## 10. Build Order (Sequence)

> **Rule:** Each item must be independently testable before wiring into the live pipeline.

- [ ] **Step 1:** `app/data/eodhd_indicators.py`
  - Fetch ADX, RSI(14), MACD, EMA(9), EMA(21) from EODHD `/api/technical/`
  - Per-ticker in-memory cache with 5-min TTL
  - `get_indicators(ticker) -> dict` returns all values or None on API failure
  - `compute_indicator_boost(indicators, direction) -> float` returns confidence delta
  - Unit test: mock EODHD response, assert correct boost values

- [ ] **Step 2:** `app/signals/crt_engine.py`
  - `scan_crt(ticker, bars) -> Optional[Dict]` — same signature as `scan_bos_fvg()`
  - Output dict matches bos_fvg_engine schema (compatible with downstream pipeline)
  - Added fields: `crt_sweep_direction`, `c1_high`, `c1_low`, `c2_sweep_price`, `has_fvg`
  - Validity rules strictly from spec in Section 5
  - Unit tests: known C1/C2/C3 bar sequences — bullish sweep, bearish sweep, invalid (close outside C1)

- [ ] **Step 3:** `app/options/eodhd_options.py`
  - `get_options_rec(ticker, direction, current_price) -> Optional[Dict]`
  - Fetch chain from EODHD `/api/options/{ticker}.US`
  - Filter by DTE (0–2), delta (0.40–0.60), OI (>100), spread (<15%)
  - Return: `{strike, expiration, dte, delta, gamma, iv, bid, ask, mid, oi, spread_pct, iv_warning}`
  - Unit test: mock chain response, assert correct contract selection

- [ ] **Step 4:** `app/core/sniper.py` — wire all three new modules + fix MTF bug
  - Import eodhd_indicators, crt_engine, eodhd_options
  - Fix `get_full_mtf_analysis()` call (pass correct bars)
  - Add 4-TF scan loop for BOS+FVG and CRT
  - Add signal merge logic with confluence scoring
  - Add indicator boost application
  - Fetch options_rec and pass to `_run_signal_pipeline()`

- [ ] **Step 5:** `app/notifications/discord_helpers.py` — update alert embed
  - Add signal source label (BOS+FVG / CRT / BOS+FVG+CRT)
  - Add timeframe badges (5m 🟢 / 3m 🟢 / 1m 🟡)
  - Add indicator line (ADX / RSI / MACD)
  - Add full OPTIONS RECOMMENDATION block from options_rec dict

- [ ] **Step 6:** End-to-end test in paper mode on 3–5 known symbols
- [ ] **Step 7:** Deploy to Railway — monitor first live session

---

## 11. Open Questions / Decisions

| # | Question | Status |
|---|---|---|
| Q1 | Does EODHD `/api/technical/` return intraday (current session) values or only EOD? Must test during market hours. | 🔲 Test needed |
| Q2 | Does EODHD `/api/options/` return 0DTE contracts during RTH? | 🔲 Test needed |
| Q3 | **TIME GATE in sniper_pipeline.py blocks after 11:00 AM.** Should CRT/BOS signals on 5m bars also be limited to pre-11:00? Or extend PM session to 13:00? | 🔲 Decision needed |
| Q4 | Is there a `get_today_session_bars_5m()` method on data_manager, or should we always resample 1m→5m? | 🔲 Check data_manager |
| Q5 | Is `ENABLE_WEBSOCKET_FEED=True` on Railway? | 🔲 Verify env |

---

## 12. Session Log

| Date | Work Done |
|---|---|
| 2026-03-26 | Session 1: Full system audit — identified unused EODHD endpoints, confirmed BOS+FVG engine state, confirmed CRT does not exist, documented full CRT spec from Nitro Trades, defined MTF scoring model, designed options alert format, created REBUILD_PLAN.md |
| 2026-03-26 | Session 2: Read sniper.py + scanner.py in full. Found critical MTF bug (1m bars passed as 5m). Found `_resample_bars()` is dead code in sniper.py. Confirmed scanner.py needs zero changes. Updated architecture diagram. |
| 2026-03-26 | Session 3: Read bos_fvg_engine.py + sniper_pipeline.py in full. **bos_fvg_engine is 100% timeframe-agnostic — zero changes needed.** sniper_pipeline already has `options_rec` param wired end-to-end to arm_ticker — just needs a real value passed in. `_resample_bars` is duplicated in both sniper.py AND sniper_pipeline.py. Finalized file list: 3 new files, 2 modified files, 6 files confirmed untouched. Build order finalized: 7 steps. |
