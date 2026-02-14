# =============================
# CONFIRMATION ENGINE SETTINGS
# =============================

# How strong candle must close beyond FVG to count as confirmation
CONFIRM_CLOSE_ABOVE_RATIO = 0.6   # 60% body close strength

# Minimum candle body size vs full range
MIN_BODY_RATIO = 0.5

# Allow wick rejection confirmations
ALLOW_WICK_CONFIRM = True

# Higher timeframe priority
CONFIRMATION_TIMEFRAMES = ["5m", "3m", "2m", "1m"]
