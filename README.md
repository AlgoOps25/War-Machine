# WAR MACHINE — God Mode Pro

This repo contains the modular War Machine GOD MODE PRO system:
- Momentum scanner -> Sniper (BOS + FVG) -> Multi-TF confirmations -> Stop/Targets -> Trade Logger
- Data: EODHD intraday (1m/5m) via `EODHD_API_KEY`
- Alerts: Discord webhook via `DISCORD_WEBHOOK`
- Host: Railway (recommended) — Start command: `python main.py`

## Files
See `config.py`, `eodhd_api.py`, `scanner.py`, `sniper.py`, `confirmations.py`, `targets.py`, `trade_logger.py`, `discord_bot.py`, `main.py`.

## Env vars
Set these in Railway (Service Variables):
- EODHD_API_KEY
- DISCORD_WEBHOOK
- LEARNING_DB_PATH (optional)

## Local test
1. `pip install -r requirements.txt`
2. Set env vars locally (export or set in shell)
3. `python main.py` — watch console logs and Discord.

## Deployment
- Commit & push to GitHub
- Railway project -> Deploy from GitHub -> set start command `python main.py`
- Add env vars in Railway -> Redeploy

