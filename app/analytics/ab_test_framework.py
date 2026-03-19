"""
A/B Test Framework - Filter Parameter Optimization

FIX 13.C-2 (Mar 19 2026): get_conn(self.db_path) raised TypeError at import
  on Railway/Postgres because get_conn() does not accept a positional db_path
  argument when USE_POSTGRES=True. Additionally, ABTestFramework() is
  instantiated at module level (ab_test = ABTestFramework()), so any DB error
  inside __init__ crashed Railway startup before main() ran.
  Fixes:
    1. _initialize_database() wrapped in try/except so import always succeeds.
    2. All get_conn() calls drop the db_path argument (irrelevant on Postgres;
       SQLite fallback still uses the default war_machine.db).
    3. All conn.close() calls replaced with return_conn(conn) in try/finally.
"""
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
from typing import Dict, Optional, Any
from collections import defaultdict
import hashlib

ET = ZoneInfo("America/New_York")


class ABTestFramework:
    """A/B testing framework for signal filter optimization."""

    EXPERIMENTS = {
        'volume_threshold':   {'A': 2.0,  'B': 3.0,  'description': 'RVOL threshold for pre-market scanner'},
        'min_confidence':     {'A': 60,   'B': 70,   'description': 'Minimum confidence to fire signal'},
        'cooldown_minutes':   {'A': 10,   'B': 15,   'description': 'Minutes between signals on same ticker'},
        'atr_stop_multiplier':{'A': 2.0,  'B': 2.5,  'description': 'ATR multiplier for stop loss'},
        'lookback_bars':      {'A': 10,   'B': 15,   'description': 'Lookback period for pattern detection'},
    }

    SAMPLE_SIZE_REQUIRED = 30
    MIN_WIN_RATE_DIFF    = 5.0

    def __init__(self):
        self.variant_cache: Dict[str, str] = {}
        # FIX 13.C-2: wrap DB init so import never crashes on Railway cold start
        try:
            self._initialize_database()
        except Exception as e:
            print(f"[AB_TEST] ⚠️  DB init deferred (non-fatal): {e}")

    def _initialize_database(self):
        """Create ab_test_results table."""
        from app.data.db_connection import get_conn, return_conn, serial_pk
        conn = None
        try:
            conn = get_conn()   # FIX 13.C-2: no db_path arg
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
            print("[AB_TEST] A/B test framework database initialized")
        finally:
            if conn:
                return_conn(conn)

    def _get_session(self) -> str:
        return datetime.now(ET).strftime("%Y-%m-%d")

    def _hash_ticker_date(self, ticker: str, param: str) -> str:
        today = self._get_session()
        return hashlib.md5(f"{ticker}_{param}_{today}".encode()).hexdigest()

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
        return self.EXPERIMENTS[param][self.get_variant(ticker, param)]

    def record_outcome(self, ticker: str, param: str, hit_target: bool):
        if param not in self.EXPERIMENTS:
            return
        from app.data.db_connection import get_conn, return_conn, ph
        conn = None
        try:
            variant     = self.get_variant(ticker, param)
            param_value = self.EXPERIMENTS[param][variant]
            session     = self._get_session()
            p = ph()
            conn = get_conn()
            cursor = conn.cursor()
            cursor.execute(
                f"INSERT INTO ab_test_results"
                f" (ticker,param_name,variant,param_value,outcome,session)"
                f" VALUES ({p},{p},{p},{p},{p},{p})",
                (ticker, param, variant, str(param_value), int(hit_target), session)
            )
            conn.commit()
        except Exception as e:
            print(f"[AB_TEST] record_outcome error: {e}")
        finally:
            if conn:
                return_conn(conn)

    def get_variant_stats(self, param: str, days_back: int = 30) -> Dict[str, Dict]:
        if param not in self.EXPERIMENTS:
            return {}
        from app.data.db_connection import get_conn, return_conn, ph, dict_cursor
        conn = None
        try:
            cutoff_date = (datetime.now(ET) - timedelta(days=days_back)).strftime("%Y-%m-%d")
            p = ph()
            conn = get_conn()
            cursor = dict_cursor(conn)
            cursor.execute(
                f"SELECT variant, COUNT(*) as samples, SUM(outcome) as wins"
                f" FROM ab_test_results"
                f" WHERE param_name={p} AND session>={p}"
                f" GROUP BY variant",
                (param, cutoff_date)
            )
            rows = cursor.fetchall()
            stats = {}
            for row in rows:
                v = row['variant']; s = row['samples'] or 0; w = row['wins'] or 0
                stats[v] = {'samples': s, 'wins': w,
                            'win_rate': round((w / s * 100) if s > 0 else 0, 1)}
            for v in ['A', 'B']:
                if v not in stats:
                    stats[v] = {'samples': 0, 'wins': 0, 'win_rate': 0.0}
            return stats
        except Exception as e:
            print(f"[AB_TEST] get_variant_stats error: {e}")
            return {'A': {'samples': 0, 'wins': 0, 'win_rate': 0.0},
                    'B': {'samples': 0, 'wins': 0, 'win_rate': 0.0}}
        finally:
            if conn:
                return_conn(conn)

    def check_winners(self, days_back: int = 30) -> Dict[str, Dict]:
        winners = {}
        for param in self.EXPERIMENTS:
            stats = self.get_variant_stats(param, days_back)
            a_s, b_s = stats['A']['samples'], stats['B']['samples']
            if a_s < self.SAMPLE_SIZE_REQUIRED or b_s < self.SAMPLE_SIZE_REQUIRED:
                continue
            a_wr, b_wr = stats['A']['win_rate'], stats['B']['win_rate']
            if abs(a_wr - b_wr) < self.MIN_WIN_RATE_DIFF:
                continue
            if a_wr > b_wr:
                wv, wwr, lwr = 'A', a_wr, b_wr
            else:
                wv, wwr, lwr = 'B', b_wr, a_wr
            winners[param] = {
                'winner': wv, 'winner_value': self.EXPERIMENTS[param][wv],
                'winner_win_rate': wwr, 'loser_win_rate': lwr,
                'samples': min(a_s, b_s),
                'description': self.EXPERIMENTS[param]['description']
            }
        return winners

    def get_ab_test_report(self, days_back: int = 30) -> str:
        lines = ["\n" + "="*80, "🧪 A/B TEST RESULTS", "="*80,
                 f"Period: Last {days_back} days\n"]
        winners = self.check_winners(days_back)
        if not winners:
            lines.append("⏳ No clear winners yet (need 30+ samples per variant)\n")
        else:
            lines.append("🏆 CLEAR WINNERS:\n")
            for param, data in winners.items():
                lines += [
                    f"  {param}:",
                    f"    Winner: Variant {data['winner']} = {data['winner_value']}",
                    f"    Win Rate: {data['winner_win_rate']:.1f}% vs {data['loser_win_rate']:.1f}%",
                    f"    Samples: {data['samples']} per variant",
                    f"    {data['description']}\n"
                ]
        lines.append("─"*80)
        lines.append("📊 ALL EXPERIMENTS:\n")
        for param in self.EXPERIMENTS:
            stats = self.get_variant_stats(param, days_back)
            lines += [
                f"  {param}:",
                f"    A ({self.EXPERIMENTS[param]['A']}): "
                f"{stats['A']['win_rate']:.1f}% (n={stats['A']['samples']})",
                f"    B ({self.EXPERIMENTS[param]['B']}): "
                f"{stats['B']['win_rate']:.1f}% (n={stats['B']['samples']})\n"
            ]
        lines.append("="*80 + "\n")
        return "\n".join(lines)

    # Legacy compat
    def record_result(self, variant: str, outcome: str, **kwargs): pass
    def get_summary(self) -> dict: return {}
    def print_report(self): pass
    def reset(self): pass


ab_test = ABTestFramework()
ABTest = ABTestFramework
