import pandas as pd
import numpy as np

df = pd.read_csv('backtests/results/or_candle_grid_trades.csv')
CHAMPIONS = {'AAPL','AMD','META','MSFT','NVDA','TSLA','AMZN','WMT','BAC','CSCO'}

def summary(label, subset):
    if len(subset) == 0:
        print(f"  {label}: no trades"); return
    wr  = subset['win'].mean() * 100
    avg = subset['r_multiple'].mean()
    tot = subset['r_multiple'].sum()
    print(f"  {label:<22} n={len(subset):>4}  WR={wr:>5.1f}%  AvgR={avg:>+7.3f}  TotalR={tot:>+7.2f}")

print("\n=== 1. CONFIDENCE DECILE AUDIT ===")
df['conf_bucket'] = (df['confidence'] * 10).apply(np.floor) / 10
for bucket in sorted(df['conf_bucket'].unique()):
    subset = df[df['conf_bucket'] == bucket]
    summary(f"conf {bucket:.1f}-{bucket+0.1:.1f}", subset)

print("\n=== 2. RVOL BUCKET BREAKDOWN ===")
bins   = [0, 1.2, 2.0, 3.0, 4.0, 999]
labels = ['<1.2','1.2-2.0','2.0-3.0','3.0-4.0','>=4.0']
df['rvol_bucket'] = pd.cut(df['rvol'], bins=bins, labels=labels, right=False)
for bucket in labels:
    summary(f"RVOL {bucket}", df[df['rvol_bucket'] == bucket])

print("\n=== 3. TIME-OF-DAY SESSION ===")
df['entry_mins'] = df['entry_hour'] * 60 + df['entry_minute']
sessions = [
    ('09:45-10:15', 585, 615),
    ('10:15-11:30', 615, 690),
    ('11:30-14:00', 690, 840),
    ('14:00-15:30', 840, 930),
]
for label, lo, hi in sessions:
    summary(label, df[(df['entry_mins'] >= lo) & (df['entry_mins'] < hi)])

print("\n=== 4. CHAMPION TICKERS vs REST ===")
summary("Champion tickers", df[df['ticker'].isin(CHAMPIONS)])
summary("Other tickers",    df[~df['ticker'].isin(CHAMPIONS)])

print("\n=== 5. DIRECTION SPLIT ===")
for d in ['bull', 'bear']:
    summary(d, df[df['direction'] == d])

print("\n=== 6. EXIT REASON SPLIT ===")
for r in df['exit_reason'].unique():
    summary(r, df[df['exit_reason'] == r])

print()
