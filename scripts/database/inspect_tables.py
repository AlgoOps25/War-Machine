from dotenv import load_dotenv
load_dotenv()
import psycopg2, os
conn = psycopg2.connect(os.environ['DATABASE_URL'])
cur = conn.cursor()
tables = [
    'bars', 'intraday_bars', 'intraday_bars_5m', 'candle_cache',
    'ml_training_data', 'signal_analytics', 'signal_outcomes',
    'pattern_performance', 'mtf_bias_stats', 'iv_history',
    'smc_signal_context', 'performance_metrics'
]
for t in tables:
    cur.execute(f"SELECT COUNT(*) FROM {t}")
    count = cur.fetchone()[0]
    if count > 0:
        cur.execute(f"SELECT column_name FROM information_schema.columns WHERE table_name='{t}' ORDER BY ordinal_position")
        cols = [r[0] for r in cur.fetchall()]
        print(f"\n{t} ({count} rows)")
        print(f"  {', '.join(cols)}")
