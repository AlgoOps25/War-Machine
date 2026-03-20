import csv
trades = list(csv.DictReader(open('output/wf_orstop/SPY_trades.csv')))
print(f"{'date':<12} {'dir':<5} {'entry':>8} {'stop':>8} {'risk':>6} {'t1':>8} {'t1_dist':>8} {'R':>6} {'exit':>6}")
for t in trades:
    e = float(t['entry_price']); s = float(t['stop_price'])
    t1 = float(t['t1_price']); risk = abs(e-s)
    t1d = abs(t1-e)
    print(f"  {t['date']:<12} {t['direction']:<5} {e:>8.2f} {s:>8.2f} {risk:>6.2f} {t1:>8.2f} {t1d:>8.2f} {t['r_multiple']:>6}")
