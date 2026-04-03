# War Machine → Discord Signal Architecture

**Last updated:** 2026-04-03  
**Status:** ACTIVE  

> **Start every session here.** This is the canonical reference for how War Machine
> generates, formats, and dispatches entry and exit signals to Discord.

---

## 1. Goal

War Machine sends entry and exit signals to Discord as rich embeds.  
You execute trades **manually** on TradingView, placing orders into Tradovate via the connected prop account.  
War Machine does **NOT** send orders to any broker automatically.

---

## 2. Architecture Overview

```
FuturesORBScanner.scan()
        │
        ├─ Gates 1–8 pass
        │
        ├─ _persist(signal)          ← writes armed_signals_persist + futures_signals table
        │
        └─ _discord_alert(signal)    ← sends rich embed to #signals channel
                │
                └─ send_futures_orb_alert()   ← discord_helpers.py
                         │
                         └─ _send_to_discord()        ← daemon thread, rate-limited
                                  │
                                  └─ POST → DISCORD_SIGNALS_WEBHOOK_URL
```

Exit alerts are **not** fired automatically.  
Call `scanner._discord_exit()` (or `send_futures_exit_alert()` directly) when you decide
to close the trade or when your position monitor detects stop/target has been reached.

---

## 3. Discord Webhook Environment Variables

| Variable | Channel | Purpose |
|---|---|---|
| `DISCORD_SIGNALS_WEBHOOK_URL` | #signals | Entry alerts (futures + equity BOS/FVG) |
| `DISCORD_WATCHLIST_WEBHOOK_URL` | #watchlist | Pre-market watchlist (equity only) |
| `DISCORD_ANNOTATIONS_WEBHOOK_URL` | #chart-annotations | Annotation bot signals (BUG-DH-6) |

Set these in **Railway → War Machine → Variables** (or `.env` for local dev).  
Optional: add `DISCORD_FUTURES_WEBHOOK_URL` for a dedicated `#futures-signals` channel (see Next Steps).

---

## 4. Entry Signal: `send_futures_orb_alert(signal)`

**File:** `app/notifications/discord_helpers.py`  
**Added:** DIS-FUT-1 (Apr 3 2026)  
**Called from:** `FuturesORBScanner._discord_alert()` in `app/futures/futures_orb_scanner.py`

### Embed format

```
⬜ FUTURES ORB — MNQ  ✅ LONG
Grade A  •  78.0% conf  •  Entry type: FVG

📐 Price Levels
  Entry : 19410.00
  Stop  : 19392.75  (Risk 17.25 pts / $34 on 1 contract)
  T1    : 19444.50  (2.0R)
  T2    : 19470.38  (3.5R)

📊 Opening Range
  OR High : 19430.00
  OR Low  : 19390.00
  OR Range: 40.00 pts  •  ATR: 12.50 pts

⚡ Execution Note
  Place trade manually on TradingView / Tradovate.
  Set stop at 19392.75 immediately after entry.
```

### Signal dict keys consumed

| Key | Source |
|---|---|
| `ticker` | `FuturesORBScanner.symbol` |
| `direction` | `"BULL"` or `"BEAR"` |
| `entry_price` | `_resolve_entry()` |
| `stop_price` | `_compute_levels()` |
| `t1`, `t2` | `_compute_levels()` |
| `confidence` | `_score()` (0.0–1.0 float) |
| `grade` | `"A"` / `"B"` / `"C"` |
| `validation_data.or_high/low/range` | OR locking logic |
| `validation_data.entry_type` | `"FVG"` or `"MOMENTUM_CONTINUATION"` |
| `validation_data.atr` | `_compute_atr()` |
| `validation_data.risk_pts` | `abs(entry - stop)` |
| `validation_data.dollar_risk` | `risk_pts × point_value × contracts` |
| `validation_data.contracts` | env `FUTURES_CONTRACTS` (default 1) |
| `validation_data.point_value` | 20.0 (NQ) / 2.0 (MNQ) |

---

## 5. Exit Signal: `send_futures_exit_alert()`

**File:** `app/notifications/discord_helpers.py`  
**Added:** DIS-FUT-2 (Apr 3 2026)

### How to fire it

**Option A — via scanner instance (preferred):**
```python
scanner._discord_exit(
    symbol="MNQ",
    direction="BULL",
    exit_price=19444.50,
    reason="T1_HIT",
    entry_price=19410.0,
    pnl_pts=34.5,
)
```

**Option B — direct import (from any module or Railway shell):**
```python
from app.notifications.discord_helpers import send_futures_exit_alert
send_futures_exit_alert(
    symbol="MNQ",
    direction="BULL",
    exit_price=19444.50,
    reason="T1_HIT",
    entry_price=19410.0,
    pnl_pts=34.5,
    contracts=1,
    point_value=2.0,
)
```

### `reason` values

| reason | Meaning | Embed color |
|---|---|---|
| `STOP_HIT` | Price hit stop loss | 🛑 Red |
| `T1_HIT` | First target reached | 🎯 Green |
| `T2_HIT` | Full target reached | 🏆 Green |
| `EOD_CLOSE` | End-of-day manual close | 🕐 Green/Red |
| Any string | Manual / custom reason | 📌 Green/Red |

---

## 6. Dispatch Path (`_send_to_discord`)

All Discord POSTs share a single internal helper:

- Runs in a **daemon thread** — never blocks the scan loop
- **Rate-limited:** min 0.5 s between POSTs (`_RATE_LIMIT_INTERVAL`)
- Payload truncated to 1900 chars per field (`_truncate_payload`)
- Errors caught and logged; caller always returns immediately

Signal delivery is **fire-and-forget**. If Discord is down, the alert is dropped
(logged at INFO level). The trade signal is still persisted to the database.

---

## 7. All Discord Alert Functions (Reference)

| Function | When called | Channel |
|---|---|---|
| `send_equity_bos_fvg_alert(signal)` | BOS/FVG equity entry | #signals |
| `send_options_signal_alert(...)` | Options entry | #signals |
| `send_scaling_alert(...)` | T1 hit, scaling 50% | #signals |
| `send_exit_alert(...)` | Full equity position close | #signals |
| `send_premarket_watchlist(...)` | Pre-market funnel | #watchlist |
| `send_daily_summary(stats)` | EOD | #signals |
| `send_simple_message(msg)` | Plain text / fallback | #signals |
| **`send_futures_orb_alert(signal)`** | **Futures ORB entry** | **#signals** |
| **`send_futures_exit_alert(...)`** | **Futures ORB exit** | **#signals** |

---

## 8. Files Changed (Apr 3 2026)

| File | Change |
|---|---|
| `app/notifications/discord_helpers.py` | Added `send_futures_orb_alert()` and `send_futures_exit_alert()` (DIS-FUT-1/2) |
| `app/futures/futures_orb_scanner.py` | `_discord_alert()` upgraded to rich embed; added `_discord_exit()` static method |
| `docs/DISCORD_SIGNALS.md` | This file — created as canonical session-resume reference |

---

## 9. Next Steps / Open Items

- [ ] **Position monitor loop** — poll live price via `tradier_futures_feed` against
      armed stop/target levels and auto-fire `_discord_exit()` so you get the exit
      alert even if you forget to call it manually.
- [ ] **Dedicated futures channel** — add `DISCORD_FUTURES_WEBHOOK_URL` env var so
      futures alerts post to `#futures-signals` instead of sharing `#signals`.
- [ ] **Move-to-BE alert** — embed that fires automatically when price touches T1
      so you know to trail the stop to breakeven.
