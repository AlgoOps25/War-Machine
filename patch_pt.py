with open('scripts/backtesting/walk_forward_backtest.py', 'r', encoding='utf-8') as f:
    src = f.read()

# Add $2 fixed profit exit for bull after stop check, before T1 check
old_bull = '''            if not t1_hit and hi >= t1_price:
                t1_hit  = True
                be_stop = actual_entry + risk  # trail to +1R after T1'''

new_bull = '''            if hi >= actual_entry + 2.00:  # $2 fixed profit exit
                pnl = actual_entry + 2.00 - actual_entry
                return {"exit_price": round(actual_entry + 2.00, 4), "exit_reason": "PT",
                        "exit_time": t, "entry_time": entry_time,
                        "pnl_pts": round(pnl, 4), "r_multiple": round(pnl / risk, 2) if risk else 0.0}
            if not t1_hit and hi >= t1_price:
                t1_hit  = True
                be_stop = actual_entry + risk  # trail to +1R after T1'''

old_bear = '''            if not t1_hit and lo <= t1_price:
                t1_hit  = True
                be_stop = actual_entry - risk  # trail to +1R after T1'''

new_bear = '''            if lo <= actual_entry - 2.00:  # $2 fixed profit exit
                pnl = actual_entry - (actual_entry - 2.00)
                return {"exit_price": round(actual_entry - 2.00, 4), "exit_reason": "PT",
                        "exit_time": t, "entry_time": entry_time,
                        "pnl_pts": round(pnl, 4), "r_multiple": round(pnl / risk, 2) if risk else 0.0}
            if not t1_hit and lo <= t1_price:
                t1_hit  = True
                be_stop = actual_entry - risk  # trail to +1R after T1'''

src2 = src.replace(old_bull, new_bull, 1).replace(old_bear, new_bear, 1)
if src2 != src:
    with open('scripts/backtesting/walk_forward_backtest.py', 'w', encoding='utf-8') as f:
        f.write(src2)
    print('$2 profit target patch: done')
else:
    print('$2 profit target patch: NO MATCH')
