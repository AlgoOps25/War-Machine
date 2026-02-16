# config.py — central configuration (can be checked into repo, override via env if needed)
import os

# External keys (keep secrets out of repo; use envs in Railway)
EODHD_API_KEY = os.getenv("EODHD_API_KEY", "")
DISCORD_WEBHOOK = os.getenv("DISCORD_WEBHOOK", "")

# Scanner / universe
SCAN_INTERVAL = int(os.getenv("SCAN_INTERVAL", "60"))         # seconds between scan cycles
TOP_SCAN_COUNT = int(os.getenv("TOP_SCAN_COUNT", "5"))
MARKET_CAP_MIN = int(os.getenv("MARKET_CAP_MIN", "500000000"))

# Sniper / retest
MAX_ARMED = int(os.getenv("MAX_ARMED", "25"))
RETEST_TIMEOUT_MINUTES = int(os.getenv("RETEST_TIMEOUT_MINUTES", "60"))

# Confirmation tuning
CONFIRM_CLOSE_ABOVE_RATIO = float(os.getenv("CONFIRM_CLOSE_ABOVE_RATIO", "0.5"))
CONFIRM_BODY_REL = float(os.getenv("CONFIRM_BODY_REL", "0.25"))

# Targets / risk
STOP_BUFFER_DOLLARS = float(os.getenv("STOP_BUFFER_DOLLARS", "0.5"))
MIN_RISK_PX = float(os.getenv("MIN_RISK_PX", "0.01"))

# Trade logger
LEARNING_DB_PATH = os.getenv("LEARNING_DB_PATH", "war_machine_trades.db")

# Learning policy file
LEARNING_POLICY_FILE = os.getenv("LEARNING_POLICY_FILE", "policy.json")

# Debug / mode
GOD_MODE_24_7 = os.getenv("GOD_MODE_24_7", "false").lower() in ("1","true","yes")
