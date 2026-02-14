# WAR MACHINE — README (GOD MODE Sniper + Multi-TF Confirmation)

This repo runs the War Machine GOD MODE sniper engine:
- Opening Range (9:30–9:40) → Breakout → FVG after breakout → Retest confirmation
- Multi-timeframe confirmation detection: prefer highest TF (5m → 3m → 2m → 1m)
- Stop/Target auto-calculator: T1 = 2R, T2 = previous 1-hour high/low (used if >=2R)
- Trade/result logger: persists confirmed trades and monitors until T1/T2/Stop
- Alerts delivered to Discord; data via EODHD intraday API; runtime on Railway

---

## File layout (place these files in repo root)

/ (repo root)
│
├─ scanner.py # main orchestrator (imports modules)
├─ targets.py # stop/target calculator (provided)
├─ trade_logger.py # SQLite trade logger + monitor (provided)
├─ scanner_helpers.py # EODHD helper wrappers (provided)
├─ config.py # tuning values (you have)
├─ discord_bot.py # optional bot helper (you may have)
├─ main.py # wrapper to run scanner.py (optional)
├─ requirements.txt # requests, pytz
├─ railway.json # Railway config (optional)
├─ README.md # this file
├─ retest_state.json # runtime (created by scanner)
└─ war_machine_trades.db # created by trade_logger.py


---

## Required environment variables (Railway service variables / local .env)


EODHD_API_KEY # your EODHD API token
DISCORD_WEBHOOK # Discord incoming webhook URL
LEARNING_DB_PATH # optional, defaults to war_machine_trades.db


---

## Install locally (minimal)
1. Create virtualenv:
   ```bash
   python -m venv venv
   source venv/bin/activate   # or venv\Scripts\activate on Windows
   pip install -r requirements.txt


Set environment variables (locally):

export EODHD_API_KEY="your_key"
export DISCORD_WEBHOOK="https://discord.com/api/..."
export LEARNING_DB_PATH="war_machine_trades.db"


Run a single-cycle test (see "Minimal test" below) or run full scanner:

python scanner.py
