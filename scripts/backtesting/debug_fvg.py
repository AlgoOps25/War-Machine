import sys
sys.path.insert(0, '.')
import pandas as pd
from scripts.backtesting.walk_forward_backtest import EODHDFetcher, split_into_sessions, bars_to_sniper_format, compute_or_5m
from app.signals.opening_range import detect_breakout_after_or, detect_fvg_after_break
from utils import config
from datetime import datetime, timedelta

fetcher = EODHDFetcher()
end = datetime.now()
df = fetcher.fetch('SPY', end - timedelta(days=30), end)
sessions = split_into_sessions(df)

for s_idx, session in enumerate(sessions[:5]):
    bars = bars_to_sniper_format(session)
    or_high, or_low = compute_or_5m(bars)
    if or_high is None:
        print(f'Session {s_idx}: no OR')
        continue

    direction, brk_idx = detect_breakout_after_or(bars, or_high, or_low)
    if direction is None:
        print(f'Session {s_idx}: no breakout')
        continue

    print(f'\nSession {s_idx} | {bars[0]["datetime"].date()}')
    print(f'  OR: {or_low:.3f}-{or_high:.3f} | Breakout: {direction} @ idx {brk_idx} ({bars[brk_idx]["datetime"].time()})')
    print(f'  Total bars: {len(bars)} | Bars available after brk+3: {len(bars) - brk_idx - 3}')
    print(f'  FVG_MIN_SIZE_PCT: {config.FVG_MIN_SIZE_PCT}')
    print('  Bars from breakout:')
    for i in range(brk_idx, min(brk_idx + 12, len(bars))):
        b = bars[i]
        print(f'    [{i}] {b["datetime"].time()} O:{b["open"]:.3f} H:{b["high"]:.3f} L:{b["low"]:.3f} C:{b["close"]:.3f}')

    # Manually check FVG conditions in the same window
    print('  Manual FVG scan (bull gap = c2.low - c0.high):')
    for i in range(brk_idx + 3, min(brk_idx + 15, len(bars))):
        if i < 2:
            continue
        c0, c2 = bars[i - 2], bars[i]
        if direction == 'bull':
            gap = c2['low'] - c0['high']
            gap_pct = gap / c0['high'] if c0['high'] > 0 else 0
            print(f'    i={i}: gap={gap:.4f} ({gap_pct*100:.3f}%) need>={config.FVG_MIN_SIZE_PCT*100:.3f}% -> {"PASS" if gap > 0 and gap_pct >= config.FVG_MIN_SIZE_PCT else "fail"}')
        else:
            gap = c0['low'] - c2['high']
            gap_pct = gap / c0['low'] if c0['low'] > 0 else 0
            print(f'    i={i}: gap={gap:.4f} ({gap_pct*100:.3f}%) need>={config.FVG_MIN_SIZE_PCT*100:.3f}% -> {"PASS" if gap > 0 and gap_pct >= config.FVG_MIN_SIZE_PCT else "fail"}')

    fvg_low, fvg_high = detect_fvg_after_break(bars, brk_idx, direction)
    print(f'  FVG result: {fvg_low} - {fvg_high}')
