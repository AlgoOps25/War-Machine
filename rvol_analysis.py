import glob, csv
from collections import defaultdict

all_trades = []
for f in glob.glob('output/wf_tier1/*_trades.csv'):
    with open(f) as fp:
        for row in csv.DictReader(fp):
            all_trades.append(row)

# Bucket by RVOL
buckets = {'<0.5': [], '0.5-1.0': [], '1.0-1.5': [], '1.5-2.0': [], '2.0-3.0': [], '3.0+': []}
for t in all_trades:
    try:
        rv = float(t['rvol'])
        r  = float(t['r_multiple'])
        if rv < 0.5:   buckets['<0.5'].append(r)
        elif rv < 1.0: buckets['0.5-1.0'].append(r)
        elif rv < 1.5: buckets['1.0-1.5'].append(r)
        elif rv < 2.0: buckets['1.5-2.0'].append(r)
        elif rv < 3.0: buckets['2.0-3.0'].append(r)
        else:          buckets['3.0+'].append(r)
    except: pass

print(f"{'RVOL':>10} {'Trades':>7} {'WR%':>6} {'AvgR':>7}")
print("-" * 35)
for k, rs in buckets.items():
    if not rs: continue
    wr = sum(1 for r in rs if r > 0) / len(rs) * 100
    avg = sum(rs) / len(rs)
    print(f"{k:>10} {len(rs):>7} {wr:>6.1f} {avg:>7.3f}")
