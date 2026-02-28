"""
Super Indicator Combo - All 7+ signals must align
Filters: RSI + SuperTrend + Volume + VWAP + 200EMA + ATR + Price Action + Time
"""

SUPER_INDICATOR = {
    "name": "Super Indicator (7-Way Confluence)",
    "filters": [
        "rsi_threshold",          # RSI must be in tradeable zone
        "supertrend_alignment",   # NEW: Price above/below SuperTrend
        "volume_surge",           # Volume >= 2.0x average
        "vwap_position",          # NEW: Price relative to VWAP
        "ema_200_alignment",      # NEW: Price above/below 200 EMA
        "atr_threshold",          # ATR for volatility
        "price_action_strength",  # NEW: Candle body% filter
        "time_filter"             # NEW: Market hours/session filter
    ],
    "description": "Ultra-selective: All 7 indicators must align simultaneously"
}

# Advanced version with options data
SUPER_INDICATOR_PLUS = {
    "name": "Super Indicator PLUS (10-Way Confluence)",
    "filters": [
        "rsi_threshold",
        "supertrend_alignment",
        "volume_surge",
        "vwap_position",
        "ema_200_alignment",
        "atr_threshold",
        "price_action_strength",
        "time_filter",
        "put_call_ratio",         # NEW: Options sentiment
        "unusual_options_flow"    # NEW: Smart money tracking
    ],
    "description": "Ultimate filter: Combines price + volume + options flow"
}
