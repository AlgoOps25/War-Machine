with open('scripts/backtesting/walk_forward_backtest.py', 'r', encoding='utf-8') as f:
    src = f.read()

old = '''    # Override ATR stop with OR boundary for 5m backtest.
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

new = '''    # Override ATR stop with OR boundary for 5m backtest, capped at $2.00 risk.
    # 5m ATR stops (~$0.40) are too tight; raw OR stops ($4-7) make targets
    # unreachable intraday. Cap at $2.00 to keep T1 ($4) / T2 ($7) reachable.
    MAX_RISK = 2.00
    if direction == "bull":
        or_stop = or_low * 0.999
        raw_stop = min(stop, or_stop)          # widen vs ATR if OR is further
        capped_stop = max(raw_stop, entry_price - MAX_RISK)  # but cap at $2 risk
        stop = capped_stop
    else:
        or_stop = or_high * 1.001
        raw_stop = max(stop, or_stop)          # widen vs ATR if OR is further
        capped_stop = min(raw_stop, entry_price + MAX_RISK)  # but cap at $2 risk
        stop = capped_stop

    # Recompute targets based on capped risk (2R / 3.5R)
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
    print('Risk cap patch: done')
else:
    print('Risk cap patch: NO MATCH')
