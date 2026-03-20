with open('scripts/backtesting/walk_forward_backtest.py', 'r', encoding='utf-8') as f:
    src = f.read()

dash = '\u2500'
em   = '\u2014'

old = (
    'Step 2b: Relative volume at breakout ' + dash*31 + '\n'
    '    # Breakout bar must have >= 1.2x the average volume of prior bars\n'
    '    breakout_vol = bars[breakout_idx].get("volume", 0)\n'
    '    prior_vols = [b["volume"] for b in bars[:breakout_idx] if b["volume"] > 0]\n'
    '    if len(prior_vols) >= 3:\n'
    '        avg_vol = sum(prior_vols) / len(prior_vols)\n'
    '        if avg_vol > 0 and breakout_vol < avg_vol * 1.2:\n'
    '            log.debug(f"  RVOL skip {session_date}: {breakout_vol:.0f} < 1.2x avg {avg_vol:.0f}")\n'
    '            return None'
)

new = (
    'Step 2b: Relative volume (recorded only ' + em + ' not used as filter) ' + dash*9 + '\n'
    '    # 1.2x RVOL is 1m-calibrated; on 5m bars volume is spread across the candle\n'
    '    # making all breakout bars appear low vs early-session averages. Not valid here.\n'
    '    breakout_vol = bars[breakout_idx].get("volume", 0)\n'
    '    prior_vols = [b["volume"] for b in bars[:breakout_idx] if b["volume"] > 0]'
)

if old in src:
    src2 = src.replace(old, new, 1)
    with open('scripts/backtesting/walk_forward_backtest.py', 'w', encoding='utf-8') as f:
        f.write(src2)
    print('RVOL patch: done')
else:
    print('RVOL patch: NO MATCH')
    idx = src.find('Step 2b')
    end = src.find('\n', idx)
    print('dash count:', src[idx:end].count(dash))
