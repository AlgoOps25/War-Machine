import config
import targets
import confirmations
import trade_logger

MAX_ARMED = config.MAX_ARMED
RETEST_TIMEOUT_MINUTES = config.RETEST_TIMEOUT_MINUTES

armed_setups = {}


def process_ticker(ticker, candles_1m, candles_5m, discord):
    if len(candles_5m) < 5:
        return

    last = candles_5m[-1]
    prev = candles_5m[-2]

    # Simple BOS detection
    if last["high"] > prev["high"]:
        direction = "CALL"
        bos_level = prev["high"]
    elif last["low"] < prev["low"]:
        direction = "PUT"
        bos_level = prev["low"]
    else:
        return

    key = f"{ticker}_{direction}"

    # Arm setup
    if key not in armed_setups and len(armed_setups) < MAX_ARMED:
        armed_setups[key] = {
            "ticker": ticker,
            "direction": direction,
            "bos_level": bos_level,
            "armed_time": last["datetime"],
            "confirmed": False
        }

        discord.send_message(
            f"⚔️ {ticker} {direction} setup armed at {bos_level:.2f}"
        )

    # Check confirmations
    for k in list(armed_setups.keys()):
        setup = armed_setups[k]

        if setup["confirmed"]:
            continue

        # timeout
        # (simple skip for now)

        # confirmation on 1m
        recent = candles_1m[-1]

        if setup["direction"] == "CALL":
            if confirmations.is_strong_bullish_candle(recent):
                confirm_trade(setup, recent, discord)

        if setup["direction"] == "PUT":
            if confirmations.is_strong_bearish_candle(recent):
                confirm_trade(setup, recent, discord)


def confirm_trade(setup, candle, discord):
    ticker = setup["ticker"]
    direction = setup["direction"]
    entry = candle["close"]

    stop, t1, t2 = targets.calculate_targets(
        direction,
        entry,
        candle["high"],
        candle["low"]
    )

    discord.send_message(
        f"🔥 {ticker} {direction} CONFIRMED\n"
        f"Entry: {entry:.2f}\n"
        f"Stop: {stop:.2f}\n"
        f"T1: {t1:.2f}\n"
        f"T2: {t2:.2f}"
    )

    trade_logger.log_trade(
        ticker,
        direction,
        entry,
        stop,
        t1,
        t2
    )

    setup["confirmed"] = True