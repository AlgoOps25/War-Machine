import json, glob, os

summaries = glob.glob('output/wf_universe/*_summary.json')
results = []
for f in summaries:
    with open(f) as fp:
        d = json.load(fp)
    ticker = os.path.basename(f).replace('_summary.json', '')
    d['ticker'] = ticker
    results.append(d)

results.sort(key=lambda x: x.get('avg_r', 0), reverse=True)
print(f"{'Ticker':<8} {'Trades':>6} {'WR%':>6} {'AvgR':>7} {'PF':>6}")
print("-" * 42)
for d in results:
    wr = d.get('win_rate', 0) * 100
    print(f"{d['ticker']:<8} {d.get('total_trades',0):>6} {wr:>6.1f} {d.get('avg_r',0):>7.3f} {d.get('profit_factor',0):>6.2f}")
