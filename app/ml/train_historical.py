"""
app/ml/train_historical.py

CLI entrypoint — Historical ML Pre-Training
============================================
Fetches EODHD OHLCV data, replays War Machine signal logic, labels outcomes,
then trains the ML model and saves it to models/ml_model_historical.pkl.

Usage
-----
    # Daily bars — fast, 2+ years of history, good starting point
    python -m app.ml.train_historical --interval d --months 24 --tickers AAPL TSLA NVDA MSFT AMD META SPY QQQ

    # Intraday 5m bars — denser signals, limited to ~120 days on EODHD free tier
    python -m app.ml.train_historical --months 4 --tickers AAPL TSLA NVDA MSFT AMD META SPY QQQ

    # Include TIMEOUT signals as LOSS (more conservative):
    python -m app.ml.train_historical --interval d --months 36 --include-timeout

Output
------
    models/ml_model_historical.pkl   — trained model bundle
    models/training_dataset.csv      — full labelled dataset (inspect/audit)

Environment variables required
------------------------------
    EODHD_API_KEY  — your EODHD API key

Bug fixes (Mar 11 2026)
-----------------------
    --rvol-min now wired through to HistoricalMLTrainer constructor.
    Daily mode uses RVOL_MIN_DAILY (1.3) automatically unless --rvol-min
    is explicitly supplied, generating many more labelled signals.
"""
from __future__ import annotations

import argparse
import logging
import os
import sys
from pathlib import Path

root = Path(__file__).parent.parent.parent
if str(root) not in sys.path:
    sys.path.insert(0, str(root))

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(name)s: %(message)s',
)
logger = logging.getLogger(__name__)

DEFAULT_TICKERS = ['AAPL', 'TSLA', 'NVDA', 'MSFT', 'AMZN',
                    'META', 'GOOGL', 'AMD',  'SPY',  'QQQ']
MODELS_DIR = root / 'models'


def main():
    parser = argparse.ArgumentParser(
        description='Pre-train War Machine ML model on EODHD historical data'
    )
    parser.add_argument('--months',   type=int,   default=12,
                        help='Months of history to fetch (default: 12)')
    parser.add_argument('--tickers',  nargs='+',  default=DEFAULT_TICKERS,
                        help='Space-separated ticker list')
    parser.add_argument('--interval', type=str,   default='5m',
                        help="Bar interval: '5m' intraday or 'd' daily (default: 5m)")
    parser.add_argument('--rvol-min', type=float, default=None,
                        help='Min RVOL to trigger signal (default: 2.0 intraday / 1.3 daily)')
    parser.add_argument('--val-frac', type=float, default=0.25,
                        help='Validation fraction for walk-forward split (default: 0.25)')
    parser.add_argument('--include-timeout', action='store_true',
                        help='Include TIMEOUT signals as LOSS in training')
    parser.add_argument('--model-name', type=str, default='ml_model_historical',
                        help='Output model filename (without .pkl)')
    parser.add_argument('--min-samples', type=int, default=50,
                        help='Minimum labelled signals required before training (default: 50)')
    args = parser.parse_args()

    # ── Validate env ──────────────────────────────────────────────────────────
    api_key = os.getenv('EODHD_API_KEY', '')
    if not api_key:
        logger.error("EODHD_API_KEY not set. Export it and retry.")
        sys.exit(1)

    MODELS_DIR.mkdir(parents=True, exist_ok=True)

    # ── Determine effective RVOL min ─────────────────────────────────────────
    from app.backtesting.historical_trainer import RVOL_MIN_DAILY, _INTRADAY_INTERVALS
    is_daily     = args.interval not in _INTRADAY_INTERVALS
    rvol_default = RVOL_MIN_DAILY if is_daily else 2.0
    rvol_min     = args.rvol_min if args.rvol_min is not None else rvol_default

    # ── Build dataset ─────────────────────────────────────────────────────────
    from app.backtesting.historical_trainer import HistoricalMLTrainer

    trainer = HistoricalMLTrainer(
        eodhd_api_key = api_key,
        interval      = args.interval,
        rvol_min      = rvol_min,
    )

    print("\n" + "="*62)
    print(" WAR MACHINE  —  Historical ML Pre-Training")
    print("="*62)
    print(f" Tickers  : {', '.join(args.tickers)}")
    print(f" History  : {args.months} months  (interval={args.interval})")
    print(f" RVOL min : {rvol_min}  {'[daily calibrated]' if is_daily and args.rvol_min is None else ''}")
    print(f" Val split: {args.val_frac*100:.0f}% held out for validation")
    print("="*62 + "\n")

    df = trainer.build_dataset(
        tickers          = args.tickers,
        months_back      = args.months,
        include_timeout  = args.include_timeout,
        interval_override = args.interval,
    )

    if df.empty:
        logger.error("Dataset is empty — check EODHD key and ticker list.")
        sys.exit(1)

    print("\n" + trainer.summary(df) + "\n")

    csv_path = MODELS_DIR / 'training_dataset.csv'
    df.to_csv(csv_path, index=False)
    print(f" Dataset saved → {csv_path}")

    if len(df) < args.min_samples:
        logger.error(
            f"Only {len(df)} labelled signals — need {args.min_samples} minimum.\n"
            "  Tips:\n"
            "    • Add more tickers: --tickers AAPL TSLA NVDA MSFT AMD META GOOGL AMZN SPY QQQ\n"
            "    • Use daily bars:   --interval d --months 36\n"
            "    • Include timeouts: --include-timeout\n"
            "    • Lower threshold:  --min-samples 30"
        )
        sys.exit(1)

    train_df, val_df = trainer.walk_forward_split(df, val_fraction=args.val_frac)

    # ── Train model ───────────────────────────────────────────────────────────
    from app.ml.ml_trainer import train_from_dataframe

    model_path = MODELS_DIR / f"{args.model_name}.pkl"

    print("\n Training model on historical dataset...")
    model, metrics = train_from_dataframe(
        train_df   = train_df,
        val_df     = val_df,
        model_path = str(model_path),
    )

    if model is None:
        logger.error(f"Training failed: {metrics.get('error')}")
        sys.exit(1)

    # ── Print results ─────────────────────────────────────────────────────────
    print("\n" + "="*62)
    print(" TRAINING RESULTS")
    print("="*62)
    print(f"  Train samples  : {metrics['n_train']}")
    print(f"  Val samples    : {metrics['n_val']}")
    print(f"  Accuracy       : {metrics['accuracy']:.2%}")
    print(f"  Precision      : {metrics['precision']:.2%}")
    print(f"  Recall         : {metrics['recall']:.2%}")
    print(f"  CV Score       : {metrics['cv_mean']:.2%} (±{metrics['cv_std']:.2%})")
    print()
    print("  Top features by importance:")
    for feat, imp in sorted(metrics['feature_importance'].items(),
                             key=lambda x: x[1], reverse=True)[:8]:
        bar_str = '█' * int(imp * 40)
        print(f"    {feat:<28} {imp:.3f}  {bar_str}")
    print()
    print(f"  Model saved → {model_path}")
    print("="*62)
    print()
    print(" NEXT STEPS")
    print("  See app/ml/INTEGRATION.md for the exact wiring steps.")
    print()


if __name__ == '__main__':
    main()
