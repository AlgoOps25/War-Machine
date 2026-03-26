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

## 3. Signal Architecture — Current vs. Target

### Current State
```
scanner.py:start_scanner_loop()
  → for ticker in watchlist:
      process_ticker(ticker)                      [sniper.py]
        → Path A: ORB path
            detect_breakout_after_or()            [opening_range.py]  ← OR high/low breakout
            detect_fvg_after_break()              [opening_range.py]  ← 1m bars only
            _run_signal_pipeline()                [sniper_pipeline.py]
        → Path B: Intraday BOS+FVG fallback
            scan_bos_fvg()                        [bos_fvg_engine.py]  ← 1m bars only
            get_full_mtf_analysis()               [mtf_fvg_priority.py]  ← called, BUT passes bars_5m=bars_session (1m bars!)
            _run_signal_pipeline()                [sniper_pipeline.py]
        → Path C: VWAP reclaim
            detect_vwap_reclaim()                 [vwap_reclaim.py]
            _run_signal_pipeline()                [sniper_pipeline.py]
```

**Critical bugs found in sniper.py:**
1. **MTF analysis is broken:** `get_full_mtf_analysis(bars_5m=bars_session)` is passing 1m session bars as if they were 5m bars. The MTF engine is receiving the wrong data and doing nothing useful.
2. **`_resample_bars()` already exists in sniper.py** (line ~175) but is NEVER called. Dead code.
3. **No CRT engine** anywhere in the repo.
4. **No EODHD Technical API calls** anywhere in the live pipeline.
5. **No options recommendation** in the live alert path (options_intelligence exists but options chain source is broken).

**Critical bugs found in scanner.py:**
1. `scanner.py` calls `process_ticker(ticker)` serially with a 45s timeout — one ticker at a time. This is fine.
2. Scan intervals: 5s (9:30-9:40), 45s (9:40-11:00), 180s (11:00-14:00), 60s (14:00-15:30), 45s (15:30-16:00). CRT needs ≤ 60s scan interval to catch 3-candle patterns on 1m bars.
3. Watchlist size: 30 tickers at open, 50 mid-session, 35 close. Acceptable.
4. `_run_ticker_with_timeout()` uses a `ThreadPoolExecutor(max_workers=1)` — only 1 concurrent ticker possible. Fine for serial execution.

### Target State
```
scanner.py:start_scanner_loop()    [NO CHANGES needed to scanner.py]
  → for ticker in watchlist:
      process_ticker(ticker)                      [sniper.py — MODIFIED]
        → Fetch EODHD indicators (cached 5m TTL)  [eodhd_indicators.py — NEW]
        → Resample: 1m → 2m, 3m (using _resample_bars already in sniper.py)
        → Path A: ORB path                        [NO CHANGES — keep as-is]
        → Path B: MTF BOS+FVG                     [FIXED: pass correct TF bars]
            scan_bos_fvg(bars_1m)  → score * 1.0x
            scan_bos_fvg(bars_2m)  → score * 1.15x
            scan_bos_fvg(bars_3m)  → score * 1.25x
            scan_bos_fvg(bars_5m)  → score * 1.50x
            merge_mtf_signals()    → best TF + confluence boost
        → Path D: MTF CRT scan                   [NEW — crt_engine.py]
            scan_crt(bars_1m)  → score * 1.0x
            scan_crt(bars_2m)  → score * 1.15x
            scan_crt(bars_3m)  → score * 1.25x
            scan_crt(bars_5m)  → score * 1.50x
        → Merge BOS+FVG + CRT signals             [same direction = best score wins + +0.05 confluence]
        → Apply indicator confidence modifiers    [eodhd_indicators.py]
        → _run_signal_pipeline()                  [sniper_pipeline.py — pass enriched signal_data]
            → eodhd_options.py                   [NEW — fetch chain + select contract]
            → discord_helpers.py                 [UPDATED — full options alert format]
```

---

## 4. CRT (Candle Range Theory) — Strategy Specification

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
- Wick extension beyond C1 extreme = inducement; close back inside = manipulation confirmed
- **Sweep direction determines trade direction:**
  - Sweep HIGH → bearish CRT (price went up to grab stops, now reverses down)
  - Sweep LOW  → bullish CRT (price went down to grab stops, now reverses up)

#### Candle 3 — The Distribution / Entry Candle
- Price moves toward the **opposite** extreme of C1 from the sweep direction
  - Bullish CRT: price swept low of C1 → C3 targets C1_HIGH
  - Bearish CRT: price swept high of C1 → C3 targets C1_LOW
- **Entry trigger options (in order of quality):**
  1. **FVG entry (BEST):** After the C2 sweep closes back inside C1, wait for an FVG to form on the lower timeframe (e.g. 1m FVG on a 5m CRT), enter at the FVG zone
  2. **MSS entry:** Wait for a Market Structure Shift on the lower timeframe confirming reversal, enter on confirmation candle close
  3. **Break of C2 wick:** Enter when price breaks back through the C2 sweep level (riskier — breakout style)

#### Stop Loss
- **Bullish CRT:** Stop below the C2 sweep wick low (a few ticks below the liquidity grab)
- **Bearish CRT:** Stop above the C2 sweep wick high

#### Take Profit
- **T1 (primary):** Opposite extreme of C1 (the untouched end)
- **T2 (runner):** Extension beyond C1 if trend phase supports it

#### Validity Rules
- C2 close MUST be within C1 range — hard invalidation if not
- An FVG left behind by the C2 sweep candle increases probability significantly
- Nested CRT (same pattern on higher TF + confirmation on lower TF) = highest probability
- More inside bars between C1 and C2 = more liquidity accumulated = stronger move
- Must create an imbalance (FVG or displacement wick) — CRT without imbalance is weak

#### Relationship to BOS+FVG
- CRT is the **setup** (identifies manipulation + direction)
- FVG is the **entry mechanism** (precise entry into the imbalance after the sweep)
- A CRT that also creates a BOS on the next higher timeframe = highest confidence signal
- They are complementary, not competing — run both engines and merge scores

#### Timeframe Hierarchy (Nitro Trades model)
- CRT pattern observed on **higher timeframe** (5m, 15m, 1h)
- Entry confirmation on **lower timeframe** (1m, 5m)
- For intraday 0DTE: observe CRT on 5m → enter via 1m FVG

---

## 5. Multi-Timeframe Signal Scoring

### Bar Construction
- 1m bars: native from EODHD WebSocket + REST
- 2m bars: `_resample_bars(bars_1m, 2)` — **function already exists in sniper.py, just not called**
- 3m bars: `_resample_bars(bars_1m, 3)` — same
- 5m bars: already materialized in `intraday_bars_5m` table; fetch via `data_manager.get_today_session_bars_5m(ticker)` (or resample from 1m as fallback)

### Signal Confidence Weight by Timeframe
| Timeframe | BOS+FVG Weight | CRT Weight | Notes |
|---|---|---|---|
| 1m | Base (1.0×) | Base (1.0×) | Fastest, most noise |
| 2m | 1.15× | 1.15× | Filters minor noise |
| 3m | 1.25× | 1.25× | Good intraday signal |
| 5m | 1.50× | 1.50× | Highest intraday confidence |

**Confluence rule:** If the same direction signal fires on 2+ timeframes simultaneously → additional +0.10 confidence boost.

---

## 6. EODHD Indicator Integration — Live Confidence Modifiers

### Endpoint
`GET https://eodhd.com/api/technical/{ticker}.US?function={indicator}&period={n}&api_token={key}&fmt=json`

### Indicators to Pull Per Signal (called once per signal event, not per bar)

| Indicator | EODHD Function | Purpose | Confidence Rule |
|---|---|---|---|
| ADX | `adx` | Trend strength | ADX > 25 = trending = +0.05 boost; ADX < 20 = choppy = −0.03 |
| RSI (14) | `rsi` | Momentum / not overbought | Bull signal: RSI 40–65 = +0.03; RSI > 75 = −0.05 (overbought); Bear: RSI 35–60 = +0.03; RSI < 25 = −0.05 |
| MACD | `macd` | Momentum alignment | Signal line crossover aligns with trade direction = +0.04 |
| EMA 9/21 | `ema` | Trend bias confirmation | Price above EMA9 + EMA9 > EMA21 for bull = +0.03; inverse for bear |
| VWAP | Local calc | Already in system | Existing gate — keep |

**Design principle:** Indicators are **additive confidence modifiers only** — they never hard-block a signal (that is the filter layer's job). Maximum total indicator boost = +0.15; maximum penalty = −0.10.

---

## 7. Options Recommendation — EODHD Options API

### Endpoint
`GET https://eodhd.com/api/options/{ticker}.US?api_token={key}&fmt=json`

Returns: full chain with strikes, expiration dates, bid/ask, OI, IV, delta, gamma, theta, vega.

### Contract Selection Logic (per signal)
1. **Direction:** Bull signal → CALL; Bear signal → PUT
2. **DTE target:** 0–2 DTE for intraday (0DTE preferred during RTH)
3. **Delta filter:** Target 0.40–0.60 delta (at-the-money, maximum gamma)
4. **Liquidity filter:** OI > 100, bid/ask spread < 15% of mid price
5. **IV check:** Flag if IV rank > 80 (premium too expensive for buyer)
6. **Strike selection:** Closest strike to current price with delta in target range
7. **Output:** Strike, expiration, delta, gamma, IV, bid/ask, suggested entry mid-price

### Discord Alert Format (target)
```
🔴 BEAR SIGNAL — TSLA [A+ Confirmation]
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
📊 SIGNAL: BOS+FVG [5m] + CRT Sweep Confirmed
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

## 8. Files to Build / Modify

### New Files
| File | Module | Purpose |
|---|---|---|
| `app/data/eodhd_indicators.py` | data | Live EODHD technical indicator fetcher with caching (TTL = 5 min per ticker) |
| `app/signals/crt_engine.py` | signals | CRT pattern detector — 3-candle AMD scan, all 4 timeframes |
| `app/options/eodhd_options.py` | options | EODHD options chain fetcher + contract selector |

### Modified Files
| File | Change |
|---|---|
| `app/mtf/bos_fvg_engine.py` | Verify `scan_bos_fvg()` is timeframe-agnostic (just takes a list of bars) — it likely already is |
| `app/core/sniper.py` | **Fix MTF bug** (pass correct TF bars to `get_full_mtf_analysis`); wire `_resample_bars()` for 2m/3m; add CRT scan loop; add indicator boost; pass options rec to pipeline |
| `app/core/sniper_pipeline.py` | Accept `options_rec` in signal_data dict; pass to discord_helpers |
| `app/notifications/discord_helpers.py` | Update alert embed to include CRT context, MTF scores, indicators, full options rec |
| `utils/config.py` | Add `CRT_MIN_SWEEP_PCT`, `MTF_CONFLUENCE_BOOST`, `EODHD_INDICATOR_CACHE_TTL` |

### Files NOT to touch
| File | Reason |
|---|---|
| `scanner.py` | Scan loop, timing, watchlist are all correct. Zero changes needed. |
| `app/mtf/smc_engine.py` | SMC enrichment is correct and additive. Keep untouched. |
| `app/data/data_manager.py` | `_resample_bars()` is already in sniper.py. No changes needed to data_manager. |
| All filter modules | `filters/` layer is correct and well-tested. Do not touch. |
| All validation modules | `validation/` layer is correct. Do not touch. |

---

## 9. Build Order (Sequence)

> **Rule:** Each item must be independently testable before wiring into the live pipeline.

- [ ] **Step 1:** `app/data/eodhd_indicators.py` — EODHD indicator fetcher with 5m TTL cache + unit test
- [ ] **Step 2:** `app/signals/crt_engine.py` — full CRT engine from spec above, with unit tests on known bar sequences
- [ ] **Step 3:** `app/options/eodhd_options.py` — live options chain fetcher + contract selector + unit test
- [ ] **Step 4:** `app/core/sniper.py` — wire all three: fix MTF bug, add CRT loop, add indicator boost, pass options_rec
- [ ] **Step 5:** `app/core/sniper_pipeline.py` — accept + forward options_rec in signal_data dict
- [ ] **Step 6:** `app/notifications/discord_helpers.py` — update alert format to full spec
- [ ] **Step 7:** End-to-end test in paper mode — validate all components fire correctly on known symbols
- [ ] **Step 8:** Deploy to Railway — monitor first live session

---

## 10. Decisions Made This Session (2026-03-26)

| Decision | Detail |
|---|---|
| Execution model | Manual on Robinhood — system is alert-only, no order routing |
| Options source | EODHD `/api/options/` — already on plan, replaces Tradier dependency |
| CRT source | Nitro Trades 3-video series — AMD 3-candle sweep pattern |
| CRT entry method | FVG entry on lower TF preferred over MSS or breakout |
| Timeframes | 1m (base), 2m, 3m, 5m — 5m signal = 1.5× confidence weight |
| Bar resampling | `_resample_bars()` already in sniper.py — use it, don't rebuild |
| Indicator source | EODHD `/api/technical/` for live values; local calcs remain for backtesting |
| Indicator role | Confidence modifiers only — no hard blocks from indicator values |
| BOS+FVG engine | Existing `bos_fvg_engine.py` logic is correct — extend, don't rewrite |
| SMC engine | Existing `smc_engine.py` is correct and additive — keep untouched |
| CRT + BOS+FVG | Complementary signals — both can fire, merge into single signal_data dict with combined score |
| scanner.py | **No changes needed** — scan timing, watchlist, loop structure are all correct |

---

## 11. Open Questions / Blockers

| # | Question | Status |
|---|---|---|
| 1 | Does EODHD `/api/technical/` return live intraday values or only EOD? Need to verify response for `function=rsi&period=14` during market hours | 🔲 Needs test |
| 2 | Does EODHD `/api/options/` return same-day 0DTE contracts during RTH? | 🔲 Needs test |
| 3 | Does `bos_fvg_engine.scan_bos_fvg()` accept any bar list regardless of timeframe, or is it hardcoded to 1m? | 🔲 Read next |
| 4 | What does `sniper_pipeline.py` look like? Need to see how signal_data dict is built before wiring options_rec | 🔲 Read next |
| 5 | Is `ENABLE_WEBSOCKET_FEED` set to True on Railway currently? | 🔲 Verify env |

---

## 12. Session Log

| Date | Work Done |
|---|---|
| 2026-03-26 | Full system audit — identified unused EODHD endpoints, confirmed BOS+FVG engine state, confirmed CRT does not exist, documented full CRT spec from Nitro Trades, defined MTF scoring model, designed options alert format, created this document |
| 2026-03-26 | Read sniper.py + scanner.py in full. Found critical MTF bug: `get_full_mtf_analysis(bars_5m=bars_session)` is passing 1m bars as 5m bars — MTF analysis is broken. Found `_resample_bars()` already exists in sniper.py but is dead code. Confirmed scanner.py needs zero changes. Updated build plan: 8 steps, 3 new files, 5 modified files. |
