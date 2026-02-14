# ============================================
# ⚔️ WAR MACHINE — GOD MODE PRO CONFIG
# Master control for all modules
# ============================================

# ===== SCANNER SPEED =====
SCAN_INTERVAL = 60   # seconds between scans (GOD MODE)
UNIVERSE_SCAN_LIMIT = 25  # tickers per cycle (keeps EODHD fast)

# ===== MARKET FILTERS =====
MARKET_CAP_MIN = 2_000_000_000
MIN_RELATIVE_VOLUME = 1.5
MIN_PRICE = 2
MAX_PRICE = 500

# ===== MOMENTUM SCORE =====
MOMENTUM_THRESHOLD = 6

# ===== BOS / FVG SETTINGS =====
BOS_LOOKBACK = 20
FVG_MIN_GAP_PERCENT = 0.15

# ===== RETEST SETTINGS =====
RETEST_TOLERANCE = 0.003  # 0.3% zone tolerance
MAX_RETEST_WAIT = 20      # candles before expiry

# ===== CONFIRMATION ENGINE =====
# strongest timeframe wins (1,2,3,5 min)

CONFIRM_TIMEFRAMES = [1,2,3,5]

# candle must close this much beyond level
CONFIRM_CLOSE_ABOVE_RATIO = 0.6

# minimum candle body vs full candle size
CONFIRM_CANDLE_BODY_MIN = 0.5

# volume spike requirement
CONFIRM_VOLUME_SPIKE = 1.2

# ===== RISK MODEL =====
RISK_REWARD_RATIO = 2.0

STOP_BUFFER = 0.002  # 0.2% below/above level
STOP_BUFFER_DOLLARS = 0.15
TARGET1_RR = 2.0
TARGET2_RR = 3.0

# ===== DISCORD SETTINGS =====
SEND_SETUP_ALERTS = True
SEND_CONFIRM_ALERTS = True
SEND_RESULT_ALERTS = True

# ===== SYSTEM MODE =====
MODE = "GOD"
