import pandas as pd
import numpy as np
import glob

dfs = [pd.read_csv(f) for f in glob.glob('output/wf_railway60/*_trades.csv')]
df = pd.concat(dfs)

df['stop_dist']       = abs(df['entry_price'] - df['stop_price'])
df['or_range_dollar'] = df['or_high'] - df['or_low']
df['fvg_size_dollar'] = df['fvg_high'] - df['fvg_low']
df['entry_mins']      = df['entry_hour'] * 60 + df['entry_minute']

numeric_cols = [
    'or_range_pct', 'or_range_dollar', 'fvg_size_pct', 'fvg_size_dollar',
    'stop_dist', 'rvol', 'entry_hour', 'entry_mins', 'confidence'
]

wins   = df[df['win'] == 1]
losses = df[df['win'] == 0]

print('=' * 65)
print(f'TOTAL: {len(df)} | WINS: {len(wins)} | LOSSES: {len(losses)}')
print('=' * 65)

print('\nCORRELATION WITH WIN & AVG R')
print('-' * 65)
corr = df[[c for c in numeric_cols if c in df.columns] + ['win','r_multiple']].corr()
print(corr[['win','r_multiple']].drop(['win','r_multiple']).round(3).sort_values('win', ascending=False))

print('\nTHRESHOLD SCAN')
print('-' * 65)
for col in [c for c in numeric_cols if c in df.columns and c != 'confidence']:
    pcts = np.percentile(df[col].dropna(), [10, 25, 50, 75, 90])
    print(f'\n{col}  (baseline n={len(df)}, wr={df["win"].mean()*100:.1f}%, avgR={df["r_multiple"].mean():.3f})')
    print(f'  {"Threshold":>10}  {"n":>5}  {"WR%":>6}  {"AvgR":>6}')
    for v in pcts:
        sub = df[df[col] >= v]
        if len(sub) >= 5:
            print(f'  {round(v,3):>10}  {len(sub):>5}  {sub["win"].mean()*100:>6.1f}  {sub["r_multiple"].mean():>6.3f}')

print('\nDIRECTION SPLIT')
print('-' * 65)
print(df.groupby('direction')[['win','r_multiple']].agg({'win':['mean','count'],'r_multiple':'mean'}).round(3))

print('\nTICKER SPLIT')
print('-' * 65)
print(df.groupby('ticker')[['win','r_multiple']].agg({'win':['mean','count'],'r_multiple':'mean'}).round(3).sort_values(('r_multiple','mean'),ascending=False))

print('\nENTRY HOUR SPLIT')
print('-' * 65)
print(df.groupby('entry_hour')[['win','r_multiple']].agg({'win':['mean','count'],'r_multiple':'mean'}).round(3))

print('\nGRADE SPLIT')
print('-' * 65)
if 'grade' in df.columns:
    print(df.groupby('grade')[['win','r_multiple']].agg({'win':['mean','count'],'r_multiple':'mean'}).round(3).sort_values(('r_multiple','mean'),ascending=False))

print('\nWINS vs LOSSES — FEATURE MEANS')
print('-' * 65)
print(f'{"Feature":>20}  {"WINS":>8}  {"LOSSES":>8}  {"DIFF":>8}')
for c in [col for col in numeric_cols if col in df.columns]:
    wm = wins[c].mean()
    lm = losses[c].mean()
    print(f'{c:>20}  {wm:>8.3f}  {lm:>8.3f}  {lm-wm:>+8.3f}')

print('\nLOSSES — EXIT REASON')
print('-' * 65)
print(losses.groupby('exit_reason')[['r_multiple']].agg(['mean','count']).round(3))

print('\nLOSSES — BY TICKER')
print('-' * 65)
print(losses.groupby('ticker')[['r_multiple']].agg(['mean','count']).round(3))

print('\nLOSSES — FULL DETAIL (sorted worst first)')
print('-' * 65)
detail_cols = ['ticker','date','entry_hour','entry_minute','or_range_pct',
               'fvg_size_pct','stop_dist','rvol','entry_price','stop_price',
               'exit_reason','r_multiple','confidence']
print(losses[[c for c in detail_cols if c in df.columns]].sort_values('r_multiple').to_string())

