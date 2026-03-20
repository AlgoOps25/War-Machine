with open('scripts/backtesting/walk_forward_backtest.py', 'r', encoding='utf-8') as f:
    src = f.read()

old = '''    # Override ATR stop with OR boundary for 5m backtest.
    # 5m ATR stops (~$0.40) are too tight and get tagged by normal bar noise.
    # OR high/low is the structural level these entries should respect.
    if direction == "bull":
        or_stop = or_low * 0.999
        if or_stop < stop:
            stop = or_stop
    else:
        or_stop = or_high * 1.001
        if or_stop > stop:
            stop = or_stop

    # Recompute targets based on OR-based risk (2R / 3.5R)
    risk = abs(entry_price - stop)
    if risk < 0.25:
        return None
    if direction == "bull":
        t1 = entry_price + risk * 2.0
        t2 = entry_price + risk * 3.5
    else:
        t1 = entry_price - risk * 2.0
        t2 = entry_price - risk * 3.5'''

new = '''    # Override ATR stop with OR boundary for 5m backtest, hard-capped at $2.50 max loss.
    # 5m ATR stops (~$0.40) are too tight and get tagged by normal bar noise.
    # OR high/low is the structural level these entries should respect.
    # Cap prevents asymmetric risk when OR is unusually wide (>$2.50 from entry).
    MAX_STOP = 2.50
    if direction == "bull":
        or_stop = or_low * 0.999
        if or_stop < stop:
            stop = or_stop
        stop = max(stop, entry_price - MAX_STOP)  # hard floor
    else:
        or_stop = or_high * 1.001
        if or_stop > stop:
            stop = or_stop
        stop = min(stop, entry_price + MAX_STOP)  # hard ceiling

    # Recompute targets based on OR-based risk (2R / 3.5R)
    risk = abs(entry_price - stop)
    if risk < 0.25:
        return None
    if direction == "bull":
        t1 = entry_price + risk * 2.0
        t2 = entry_price + risk * 3.5
    else:
        t1 = entry_price - risk * 2.0
        t2 = entry_price - risk * 3.5'''

if old in src:
    src2 = src.replace(old, new, 1)
    with open('scripts/backtesting/walk_forward_backtest.py', 'w', encoding='utf-8') as f:
        f.write(src2)
    print('$2.50 stop cap: done')
else:
    print('$2.50 stop cap: NO MATCH')
