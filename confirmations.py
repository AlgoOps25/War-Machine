import config

CONFIRM_CLOSE_ABOVE_RATIO = config.CONFIRM_CLOSE_ABOVE_RATIO
CONFIRM_CANDLE_BODY_MIN = config.CONFIRM_CANDLE_BODY_MIN


def is_strong_bullish_candle(candle):
    o = candle["open"]
    c = candle["close"]
    h = candle["high"]
    l = candle["low"]

    if c <= o:
        return False

    body = abs(c - o)
    full = h - l

    if full == 0:
        return False

    body_ratio = body / full

    if body_ratio < CONFIRM_CANDLE_BODY_MIN:
        return False

    close_position = (c - l) / full

    return close_position >= CONFIRM_CLOSE_ABOVE_RATIO


def is_strong_bearish_candle(candle):
    o = candle["open"]
    c = candle["close"]
    h = candle["high"]
    l = candle["low"]

    if c >= o:
        return False

    body = abs(c - o)
    full = h - l

    if full == 0:
        return False

    body_ratio = body / full

    if body_ratio < CONFIRM_CANDLE_BODY_MIN:
        return False

    close_position = (h - c) / full

    return close_position >= CONFIRM_CLOSE_ABOVE_RATIO
