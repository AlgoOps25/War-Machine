# ⚔️ War Machine — Algorithmic Day Trading System

> **CFW6 Signal Engine** | Gap Movers + 0DTE Options | Railway-Deployed | Discord Alerts

![Python](https://img.shields.io/badge/Python-3.11+-blue) ![Platform](https://img.shields.io/badge/Platform-Railway-purple) ![Status](https://img.shields.io/badge/Status-Production-green)

---

## 🧠 What It Does

War Machine is a production algorithmic trading system that:

1. **Scans** pre-market gap movers and volume leaders (6:00–9:30 AM ET)
2. **Detects** Opening Range breakouts (CFW6_OR) and Intraday BOS+FVG patterns (CFW6_INTRADAY)
3. **Filters** signals through 11 quality gates: Options pre-gate → Volume → VIX Regime → MTF Convergence → Candle Quality → Hourly Gate → Validator → ML Confidence → Dynamic Threshold → Explosive Override → Grade Gate
4. **Alerts** via Discord with entry price, stop loss, take profit, grade, and confidence score
5. **Persists** watch/armed state across Railway restarts via PostgreSQL

---

## 🗂️ Project Structure

```
war-machine/
├── app/
│   ├── core/
│   │   ├── sniper.py          # ⚡ Main CFW6 signal engine (1,500+ lines)
│   │   ├── scanner.py         # Market scanner & watchlist builder
│   │   ├── error_recovery.py  # Exponential backoff & circuit breaker
│   │   └── thread_safe_state.py
│   ├── data/
│   │   ├── data_manager.py    # Central data orchestration (EODHD)
│   │   ├── candle_cache.py    # OHLCV cache (reduces API calls ~90%)
│   │   ├── ws_feed.py         # Real-time WebSocket feed
│   │   ├── db_connection.py   # PostgreSQL connection pool
│   │   └── unusual_options.py # Whale activity detection
│   ├── signals/
│   │   ├── bos_fvg_detector.py  # ✅ CANONICAL BOS/FVG detector (use this)
│   │   ├── opening_range.py
│   │   ├── signal_analytics.py
│   │   └── signal_generator.py  # ⚠️ DEPRECATED — sniper.py is active
│   ├── filters/               # VIX, hourly gate, cooldown
│   ├── indicators/            # RSI, MACD, ATR, VWAP
│   ├── ml/                    # Confidence model
│   ├── mtf/                   # Multi-timeframe FVG priority
│   ├── options/               # Greeks & chain analysis
│   ├── risk/                  # Position sizing, dynamic thresholds
│   └── validation/            # Multi-indicator validator
├── utils/
│   └── config.py              # All system constants (module-level)
├── migrations/                # PostgreSQL schema migrations
├── models/
│   └── signal_predictor.pkl   # Trained ML confidence model
├── scripts/                   # Dev/ops utilities (not production)
├── tests/
├── railway.toml
├── nixpacks.toml
└── requirements.txt
```

---

## ⚡ Signal Pipeline (CFW6)

```
Step 1:  Watchlist Scan (gap movers, volume leaders)
Step 2:  Opening Range Build (9:30–9:45 ET)
Step 3:  Options Pre-Gate (OI, volume, spread, delta)
Step 4:  BOS Detection → Watch Alert → Discord
Step 5:  FVG Confirmation (candle pattern)
Step 6:  Volume Profile Gate
Step 7:  VIX Regime Filter
Step 8:  MTF Convergence (1m / 5m / 15m alignment)
Step 8.5: Multi-Indicator Validator
Step 9:  ML Confidence Score
Step 10: Explosive Mover Override (RVOL > 4x)
Step 11: Dynamic Threshold Gate
Step 11b: Grade Gate (A/B/C grading)
Step 12: Armed Signal → Discord Alert
```

---

## 🚀 Setup & Deployment

### Prerequisites
- Python 3.11+
- PostgreSQL (Railway provides this)
- EODHD API key
- Discord webhook URL

### Environment Variables
```env
EODHD_API_KEY=your_key_here
DISCORD_WEBHOOK_URL=https://discord.com/api/webhooks/...
DATABASE_URL=postgresql://...
```

### Local Development
```bash
git clone https://github.com/AlgoOps25/War-Machine.git
cd War-Machine
pip install -r requirements.txt
cp .env.example .env  # fill in your keys
python -m app.core
```

### Railway Deployment
```bash
# Push to main triggers automatic Railway redeploy
git push origin main

# Or use the PowerShell deploy script
.\scripts\deploy.ps1
```

### Health Check
```bash
python app/health_check.py
```

---

## 📊 Key Configuration (`utils/config.py`)

| Parameter | Default | Description |
|-----------|---------|-------------|
| `ACCOUNT_SIZE` | 5000 | Trading account size USD |
| `MIN_CONFIDENCE_OR` | 0.75 | Min confidence for OR signals |
| `MIN_CONFIDENCE_INTRADAY` | 0.70 | Min confidence for intraday |
| `OR_END_TIME` | 9:45 AM | Opening range window close |
| `FORCE_CLOSE_TIME` | 3:50 PM | All positions closed EOD |
| `MAX_OPEN_POSITIONS` | 5 | Concurrent position limit |
| `MAX_VIX_LEVEL` | 35.0 | Regime filter ceiling |

---

## 🗄️ Database Tables

| Table | Purpose |
|-------|---------|
| `candle_cache` | OHLCV history (reduces API calls) |
| `watching_signals_persist` | BOS watch state (survives restarts) |
| `armed_signals_persist` | Armed signal state (survives restarts) |
| `signal_outcomes` | Trade tracking & P&L |
| `system_state` | App-level persistence |

---

## ⚠️ Known Architecture Notes

- **`signal_generator.py` is deprecated** — `sniper.py` is the active pipeline
- **`bos_fvg_detector.py` is canonical** — do not add logic to the retired detector files
- **`production` branch** trails `main` — always deploy from `main`
- Railway redeploys on every push to `main`

---

## 📄 License

MIT — see [LICENSE](LICENSE)

---

## 🤝 Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md)
