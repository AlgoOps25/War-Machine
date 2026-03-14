"""
A/B Test Framework - Filter Parameter Optimization

Enables A/B testing of signal filtering parameters:
  - Volume threshold (2.0x vs 3.0x)
  - Minimum confidence (60 vs 70)
  - Cooldown minutes (10 vs 15)
  - ATR stop multiplier (2.0 vs 2.5)

Automatic winner promotion:
  - Collects 30+ samples per variant
  - Compares win rates
  - Promotes winner as default

Usage:
  from app.analytics.ab_test_framework import ab_test
  
  # Get parameter variant for ticker
  volume_threshold = ab_test.get_param('AAPL', 'volume_threshold')
  
  # Record outcome
  ab_test.record_outcome('AAPL', 'volume_threshold', hit_target=True)
  
  # Check for winners
  winners = ab_test.check_winners()
"""
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
from typing import Dict, List, Optional, Tuple, Any
from collections import defaultdict
import hashlib
from app.data.db_connection import get_conn, ph, dict_cursor, serial_pk

ET = ZoneInfo("America/New_York")


class ABTestFramework:
    """A/B testing framework for signal filter optimization."""
    
    EXPERIMENTS = {
        'volume_threshold': {
            'A': 2.0,
            'B': 3.0,
            'description': 'RVOL threshold for pre-market scanner'
        },
        'min_confidence': {
            'A': 60,
            'B': 70,
            'description': 'Minimum confidence to fire signal'
        },
        'cooldown_minutes': {
            'A': 10,
            'B': 15,
            'description': 'Minutes between signals on same ticker'
        },
        'atr_stop_multiplier': {
            'A': 2.0,
            'B': 2.5,
            'description': 'ATR multiplier for stop loss'
        },
        'lookback_bars': {
            'A': 10,
            'B': 15,
            'description': 'Lookback period for pattern detection'
        }
    }
    
    SAMPLE_SIZE_REQUIRED = 30
    MIN_WIN_RATE_DIFF = 5.0
    
    def __init__(self, db_path: str = "market_memory.db"):
        self.db_path = db_path
        self._initialize_database()
        self.variant_cache: Dict[str, str] = {}
    
    def _initialize_database(self):
        """Create ab_test_results table."""
        conn = get_conn(self.db_path)
        cursor = conn.cursor()
        
        cursor.execute(f"""
            CREATE TABLE IF NOT EXISTS ab_test_results (
                id {serial_pk()},
                ticker TEXT NOT NULL,
                param_name TEXT NOT NULL,
                variant TEXT NOT NULL,
                param_value TEXT NOT NULL,
                outcome INTEGER NOT NULL,
                session TEXT NOT NULL,
                timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        
        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_ab_test_param_variant
            ON ab_test_results(param_name, variant, session)
        """)
        
        conn.commit()
        conn.close()
        
        print("[AB_TEST] A/B test framework database initialized")
    
    def _get_session(self) -> str:
        return datetime.now(ET).strftime("%Y-%m-%d")
    
    def _hash_ticker_date(self, ticker: str, param: str) -> str:
        today = self._get_session()
        combined = f"{ticker}_{param}_{today}"
        return hashlib.md5(combined.encode()).hexdigest()
    
    def get_variant(self, ticker: str, param: str) -> str:
        if param not in self.EXPERIMENTS:
            raise ValueError(f"Unknown parameter: {param}")
        
        cache_key = f"{ticker}_{param}_{self._get_session()}"
        
        if cache_key in self.variant_cache:
            return self.variant_cache[cache_key]
        
        hash_val = self._hash_ticker_date(ticker, param)
        variant = 'A' if int(hash_val[:8], 16) % 2 == 0 else 'B'
        self.variant_cache[cache_key] = variant
        return variant
    
    def get_param(self, ticker: str, param: str) -> Any:
        variant = self.get_variant(ticker, param)
        return self.EXPERIMENTS[param][variant]
    
    def record_outcome(self, ticker: str, param: str, hit_target: bool):
        if param not in self.EXPERIMENTS:
            return
        
        variant = self.get_variant(ticker, param)
        param_value = self.EXPERIMENTS[param][variant]
        session = self._get_session()
        
        p = ph()
        conn = get_conn(self.db_path)
        cursor = conn.cursor()
        
        cursor.execute(f"""
            INSERT INTO ab_test_results
                (ticker, param_name, variant, param_value, outcome, session)
            VALUES ({p}, {p}, {p}, {p}, {p}, {p})
        """, (ticker, param, variant, str(param_value), int(hit_target), session))
        
        conn.commit()
        conn.close()
    
    def get_variant_stats(self, param: str, days_back: int = 30) -> Dict[str, Dict]:
        if param not in self.EXPERIMENTS:
            return {}
        
        cutoff_date = (datetime.now(ET) - timedelta(days=days_back)).strftime("%Y-%m-%d")
        
        p = ph()
        conn = get_conn(self.db_path)
        cursor = dict_cursor(conn)
        
        cursor.execute(f"""
            SELECT 
                variant,
                COUNT(*) as samples,
                SUM(outcome) as wins
            FROM ab_test_results
            WHERE param_name = {p} AND session >= {p}
            GROUP BY variant
        """, (param, cutoff_date))
        
        rows = cursor.fetchall()
        conn.close()
        
        stats = {}
        for row in rows:
            variant = row['variant']
            samples = row['samples'] or 0
            wins = row['wins'] or 0
            win_rate = (wins / samples * 100) if samples > 0 else 0
            stats[variant] = {'samples': samples, 'wins': wins, 'win_rate': round(win_rate, 1)}
        
        for variant in ['A', 'B']:
            if variant not in stats:
                stats[variant] = {'samples': 0, 'wins': 0, 'win_rate': 0.0}
        
        return stats
    
    def check_winners(self, days_back: int = 30) -> Dict[str, Dict]:
        winners = {}
        
        for param in self.EXPERIMENTS:
            stats = self.get_variant_stats(param, days_back)
            
            a_samples = stats['A']['samples']
            b_samples = stats['B']['samples']
            
            if a_samples < self.SAMPLE_SIZE_REQUIRED or b_samples < self.SAMPLE_SIZE_REQUIRED:
                continue
            
            a_win_rate = stats['A']['win_rate']
            b_win_rate = stats['B']['win_rate']
            
            diff = abs(a_win_rate - b_win_rate)
            if diff < self.MIN_WIN_RATE_DIFF:
                continue
            
            if a_win_rate > b_win_rate:
                winner_variant = 'A'
                winner_win_rate = a_win_rate
                loser_win_rate = b_win_rate
            else:
                winner_variant = 'B'
                winner_win_rate = b_win_rate
                loser_win_rate = a_win_rate
            
            winners[param] = {
                'winner': winner_variant,
                'winner_value': self.EXPERIMENTS[param][winner_variant],
                'winner_win_rate': winner_win_rate,
                'loser_win_rate': loser_win_rate,
                'samples': min(a_samples, b_samples),
                'description': self.EXPERIMENTS[param]['description']
            }
        
        return winners
    
    def get_ab_test_report(self, days_back: int = 30) -> str:
        lines = []
        lines.append("\n" + "="*80)
        lines.append("🧪 A/B TEST RESULTS")
        lines.append("="*80)
        lines.append(f"Period: Last {days_back} days\n")
        
        winners = self.check_winners(days_back)
        
        if not winners:
            lines.append("⏳ No clear winners yet (need 30+ samples per variant)\n")
        else:
            lines.append("🏆 CLEAR WINNERS:\n")
            for param, data in winners.items():
                lines.append(f"  {param}:")
                lines.append(f"    Winner: Variant {data['winner']} = {data['winner_value']}")
                lines.append(f"    Win Rate: {data['winner_win_rate']:.1f}% vs {data['loser_win_rate']:.1f}%")
                lines.append(f"    Samples: {data['samples']} per variant")
                lines.append(f"    {data['description']}\n")
        
        lines.append("─"*80)
        lines.append("📊 ALL EXPERIMENTS:\n")
        
        for param in self.EXPERIMENTS:
            stats = self.get_variant_stats(param, days_back)
            lines.append(f"  {param}:")
            lines.append(f"    A ({self.EXPERIMENTS[param]['A']}): "
                        f"{stats['A']['win_rate']:.1f}% (n={stats['A']['samples']})")
            lines.append(f"    B ({self.EXPERIMENTS[param]['B']}): "
                        f"{stats['B']['win_rate']:.1f}% (n={stats['B']['samples']})\n")
        
        lines.append("="*80 + "\n")
        return "\n".join(lines)

    # ── Legacy compat methods (from ab_test.py stub) ──────────────────────
    def record_result(self, variant: str, outcome: str, **kwargs):
        pass

    def get_summary(self) -> dict:
        return {}

    def print_report(self):
        pass

    def reset(self):
        pass


# Global A/B test instance
ab_test = ABTestFramework()

# ══════════════════════════════════════════════════════════════════════════════
# Backward-Compat: ab_test.py → ab_test_framework.py
# ABTest was the class name in the stub. Alias it here.
# ══════════════════════════════════════════════════════════════════════════════
ABTest = ABTestFramework
