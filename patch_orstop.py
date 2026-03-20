with open('scripts/backtesting/walk_forward_backtest.py', 'r', encoding='utf-8') as f:
    src = f.read()

old = '''    try:
        stop, t1, t2 = compute_stop_and_targets(
            bars, direction, or_high, or_low, entry_price, grade=grade
        )
    except Exception as e:
        log.debug(f"  Levels failed {session_date}: {e}")
        return None
    if stop is None or t1 is None or t2 is None:
        return None
    if abs(entry_price - stop) < 0.25:  # min $0.25 risk ? filters stop-fallback garbage
        return None'''

new = '''    try:
        stop, t1, t2 = compute_stop_and_targets(
            bars, direction, or_high, or_low, entry_price, grade=grade
        )
    except Exception as e:
        log.debug(f"  Levels failed {session_date}: {e}")
        return None
    if stop is None or t1 is None or t2 is None:
        return None

    # Override ATR stop with OR boundary for 5m backtest.
    # 5m ATR is ~0.05% of price ($0.30-0.45 on SPY) — stops are too tight
    # and get tagged by normal bar noise before the trade has room to breathe.
    # OR high/low is a structural level that 5m entries should respect.
    if direction == "bull":
        or_stop = or_low * 0.999
        if or_stop < stop:  # only widen, never tighten
            stop = or_stop
    else:
        or_stop = or_high * 1.001
        if or_stop > stop:  # only widen, never tighten
            stop = or_stop

    # Recompute targets based on widened stop (maintain 2R / 3.5R ratios)
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
    print('OR stop override: done')
else:
    print('OR stop override: NO MATCH')
