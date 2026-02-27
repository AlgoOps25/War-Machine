#!/usr/bin/env python3
"""Fast optimization with pre-computed indicators"""
import sys
from datetime import datetime, timedelta, time as dtime
from zoneinfo import ZoneInfo
from typing import List, Dict
import pandas as pd
import numpy as np
import json
from itertools import product
import time as time_module

from data_manager import DataManager
from db_connection import get_conn, ph, dict_cursor

ET = ZoneInfo("America/New_York")

TICKERS = ["SPY", "QQQ", "AAPL", "MSFT", "NVDA", "TSLA", "META", "AMD",
           "GOOGL", "AMZN", "NFLX", "INTC", "PLTR", "COIN", "SOFI"]

class FastOptimizer:
    def __init__(self, db_path: str = "market_memory.db", days: int = 10):
        self.db_path = db_path
        now_et = datetime.now(ET)
        self.end_date = now_et.date()
        self.start_date = (now_et - timedelta(days=days)).date()
        
        print(f"\n{'='*70}\nFAST OPTIMIZATION\n{'='*70}")
        print(f"Period: {self.start_date} to {self.end_date}\n{'='*70}\n")
        
        print("Loading bars...")
        self.ticker_data = {}
        for ticker in TICKERS:
            bars = self._load_bars(ticker)
            if bars:
                ind = self._precompute(bars)
                self.ticker_data[ticker] = {'bars': bars, 'ind': ind}
                print(f"   {ticker}: {len(bars):,} bars")
        print(f"\n Cached {len(self.ticker_data)} tickers\n")
    
    def _load_bars(self, ticker: str) -> List[Dict]:
        try:
            conn = get_conn(self.db_path)
            cur = dict_cursor(conn)
            query = f"""SELECT datetime, open, high, low, close, volume
                       FROM intraday_bars WHERE ticker = {ph()} 
                       AND datetime >= {ph()} AND datetime <= {ph()} ORDER BY datetime"""
            cur.execute(query, (ticker, self.start_date, self.end_date))
            rows = cur.fetchall()
            conn.close()
            
            bars = []
            for row in rows:
                dt = row["datetime"]
                if isinstance(dt, str):
                    dt = datetime.fromisoformat(dt)
                if hasattr(dt, "tzinfo") and dt.tzinfo:
                    dt = dt.replace(tzinfo=None)
                bars.append({"datetime": dt, "open": float(row["open"]),
                           "high": float(row["high"]), "low": float(row["low"]),
                           "close": float(row["close"]), "volume": int(row["volume"])})
            return bars
        except:
            return []
    
    def _precompute(self, bars: List[Dict]) -> Dict:
        n = len(bars)
        closes = np.array([b['close'] for b in bars])
        highs = np.array([b['high'] for b in bars])
        lows = np.array([b['low'] for b in bars])
        volumes = np.array([b['volume'] for b in bars])
        times = [b['datetime'].time() for b in bars]
        
        atr = np.zeros(n)
        for i in range(14, n):
            tr_list = []
            for j in range(i-14, i):
                tr = max(highs[j] - lows[j], abs(highs[j] - closes[j-1]), 
                        abs(lows[j] - closes[j-1]))
                tr_list.append(tr)
            atr[i] = np.mean(tr_list)
        
        vol_ratio = np.zeros(n)
        for i in range(20, n):
            avg = np.mean(volumes[i-20:i])
            if avg > 0:
                vol_ratio[i] = volumes[i] / avg
        
        momentum = np.zeros(n)
        for i in range(5, n):
            if closes[i-5] != 0:
                momentum[i] = (closes[i] - closes[i-5]) / closes[i-5]
        
        structures = {}
        for lb in [12, 16, 20]:
            res = np.zeros(n)
            sup = np.zeros(n)
            tup = np.zeros(n, dtype=bool)
            tdn = np.zeros(n, dtype=bool)
            for i in range(lb, n):
                res[i] = np.max(highs[i-lb:i])
                sup[i] = np.min(lows[i-lb:i])
                tup[i] = highs[i] > res[i]
                tdn[i] = lows[i] < sup[i]
            structures[lb] = {'res': res, 'sup': sup, 'tup': tup, 'tdn': tdn}
        
        return {'closes': closes, 'highs': highs, 'lows': lows, 'times': times,
                'atr': atr, 'vol_ratio': vol_ratio, 'momentum': momentum, 'struct': structures}
    
    def test(self, params: Dict) -> Dict:
        trades = []
        lb = params['lookback']
        
        for ticker, data in self.ticker_data.items():
            ind = data['ind']
            st = ind['struct'][lb]
            n = len(data['bars'])
            
            i = max(20, lb)
            while i < n:
                t = ind['times'][i]
                if params['time_filter'] == 'morning' and not (dtime(9,30) <= t <= dtime(11,0)):
                    i += 1
                    continue
                elif params['time_filter'] == 'power' and not (dtime(15,0) < t <= dtime(16,0)):
                    i += 1
                    continue
                
                if ind['vol_ratio'][i] < params['volume_mult']:
                    i += 1
                    continue
                
                close = ind['closes'][i]
                sig = None
                
                if close > st['res'][i] > 0:
                    if params['momentum_filter'] == 'weak' and ind['momentum'][i] <= 0:
                        i += 1
                        continue
                    if params['trend_filter'] and not st['tup'][i]:
                        i += 1
                        continue
                    sig = 'long'
                elif close < st['sup'][i] and st['sup'][i] > 0:
                    if params['momentum_filter'] == 'weak' and ind['momentum'][i] >= 0:
                        i += 1
                        continue
                    if params['trend_filter'] and not st['tdn'][i]:
                        i += 1
                        continue
                    sig = 'short'
                
                if not sig or ind['atr'][i] == 0:
                    i += 1
                    continue
                
                entry = close
                atr_val = ind['atr'][i]
                stop = entry - (atr_val * params['atr_stop_mult']) if sig == 'long' else entry + (atr_val * params['atr_stop_mult'])
                target = entry + (atr_val * params['atr_stop_mult'] * params['risk_reward']) if sig == 'long' else entry - (atr_val * params['atr_stop_mult'] * params['risk_reward'])
                
                exit_price = None
                for j in range(i+1, min(i+30, n)):
                    if sig == 'long':
                        if ind['lows'][j] <= stop:
                            exit_price = stop
                            break
                        if ind['highs'][j] >= target:
                            exit_price = target
                            break
                    else:
                        if ind['highs'][j] >= stop:
                            exit_price = stop
                            break
                        if ind['lows'][j] <= target:
                            exit_price = target
                            break
                
                if exit_price is None:
                    exit_price = ind['closes'][min(i+30, n-1)]
                
                pnl = (exit_price - entry) if sig == 'long' else (entry - exit_price)
                trades.append({'pnl': pnl})
                i += 15
        
        if not trades:
            return {'params': params, 'trades': 0, 'wr': 0, 'pf': 0, 'pnl': 0}
        
        wins = [t for t in trades if t['pnl'] > 0]
        loss = [t for t in trades if t['pnl'] <= 0]
        wr = (len(wins) / len(trades)) * 100
        total_pnl = sum(t['pnl'] for t in trades)
        avg_win = np.mean([t['pnl'] for t in wins]) if wins else 0
        avg_loss = np.mean([t['pnl'] for t in loss]) if loss else 0
        pf = abs((len(wins) * avg_win) / (len(loss) * avg_loss)) if loss and avg_loss != 0 else (999 if wins else 0)
        
        return {'params': params, 'trades': len(trades), 'wins': len(wins), 'loss': len(loss),
                'wr': wr, 'pf': pf, 'pnl': total_pnl, 'avg_win': avg_win, 'avg_loss': avg_loss}
    
    def run(self) -> pd.DataFrame:
        print(f"{'='*70}\nPARAMETER GRID\n{'='*70}\n")
        grid = {'volume_mult': [2.0, 2.5, 3.0], 'atr_stop_mult': [1.5, 2.0, 2.5],
                'risk_reward': [2.0, 2.5, 3.0], 'lookback': [12, 16, 20],
                'momentum_filter': ['none', 'weak'], 'trend_filter': [False, True],
                'time_filter': ['all', 'morning', 'power']}
        combos = [dict(zip(grid.keys(), v)) for v in product(*grid.values())]
        print(f" {len(combos)} combinations\n{'='*70}\nTESTING\n{'='*70}\n")
        
        results = []
        start = time_module.time()
        for idx, p in enumerate(combos, 1):
            r = self.test(p)
            results.append(r)
            eta = ((len(combos) - idx) * ((time_module.time() - start) / idx)) / 60
            if r['trades'] > 0:
                print(f"[{idx}/{len(combos)}] V={p['volume_mult']:.1f} A={p['atr_stop_mult']:.1f} R={p['risk_reward']:.1f} L={p['lookback']} | T={r['trades']} W={r['wr']:.1f}% P={r['pf']:.2f} $={r['pnl']:.0f} | ETA={eta:.1f}m")
        
        print(f"\n{'='*70}\n DONE\n{'='*70}\n")
        return pd.DataFrame(results)

def main():
    opt = FastOptimizer(days=10)
    df = opt.run()
    df.to_csv("fast_results.csv", index=False)
    print(" Saved fast_results.csv\n")
    
    good = df[df['trades'] >= 20]
    top = (good[good['pnl'] > 0].nlargest(20, 'pnl') if len(good[good['pnl'] > 0]) > 0 
           else (good.nlargest(20, 'pnl') if len(good) > 0 else df.nlargest(20, 'pnl')))
    
    print(f"{'='*70}\nTOP 20\n{'='*70}\n")
    for i, row in enumerate(top.iterrows(), 1):
        r = row[1]
        p = r['params']
        print(f"#{i} V={p['volume_mult']:.1f} A={p['atr_stop_mult']:.1f} R={p['risk_reward']:.1f} L={p['lookback']} | T={r['trades']} W={r['wr']:.1f}% P={r['pf']:.2f} $={r['pnl']:.2f}\n")
    
    with open('top_configs.json', 'w') as f:
        json.dump([{'rank': i+1, 'params': row[1]['params'], 
                   'metrics': {'trades': int(row[1]['trades']), 'wr': float(row[1]['wr']), 
                              'pf': float(row[1]['pf']), 'pnl': float(row[1]['pnl'])}}
                  for i, row in enumerate(top.iterrows())], f, indent=2, default=str)
    print(" Saved top_configs.json\n COMPLETE!\n")

if __name__ == "__main__":
    main()
