with open('scripts/backtesting/walk_forward_backtest.py', 'r', encoding='utf-8') as f:
    src = f.read()

# Revert cap patch back to plain OR stop
old = '''    # Override ATR stop with OR boundary for 5m backtest, capped at $2.00 risk.
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

new = '''    # Override ATR stop with OR boundary for 5m backtest.
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

if old in src:
    src2 = src.replace(old, new, 1)
    with open('scripts/backtesting/walk_forward_backtest.py', 'w', encoding='utf-8') as f:
        f.write(src2)
    print('Reverted to OR stop: done')
else:
    print('Revert: NO MATCH')

# Now patch T1 trailing stop from BE to +1R
with open('scripts/backtesting/walk_forward_backtest.py', 'r', encoding='utf-8') as f:
    src = f.read()

old2 = '''            if not t1_hit and hi >= t1_price:
                t1_hit  = True
                be_stop = actual_entry'''

new2 = '''            if not t1_hit and hi >= t1_price:
                t1_hit  = True
                be_stop = actual_entry + risk  # trail to +1R after T1'''

old3 = '''            if not t1_hit and lo <= t1_price:
                t1_hit  = True
                be_stop = actual_entry'''

new3 = '''            if not t1_hit and lo <= t1_price:
                t1_hit  = True
                be_stop = actual_entry - risk  # trail to +1R after T1'''

src2 = src.replace(old2, new2, 1).replace(old3, new3, 1)
if src2 != src:
    with open('scripts/backtesting/walk_forward_backtest.py', 'w', encoding='utf-8') as f:
        f.write(src2)
    print('T1 trail to +1R: done')
else:
    print('T1 trail: NO MATCH')
