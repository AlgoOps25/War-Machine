"""
scripts/ml/train_historical.py

Moved from app/ml/train_historical.py (Batch B audit, 2026-03-16).
Standalone CLI dev tool — not a runtime module.

CLI entrypoint — Historical ML Pre-Training
============================================
Fetches EODHD OHLCV data, replays War Machine signal logic, labels outcomes,
then trains the ML model and saves it to models/ml_model_historical.pkl.

Usage
-----
    # Daily bars — fast, 2+ years of history, good starting point
    python scripts/ml/train_historical.py --interval d --months 24 --tickers AAPL TSLA NVDA MSFT AMD META SPY QQQ

    # Intraday 5m bars — denser signals, limited to ~120 days on EODHD free tier
    python scripts/ml/train_historical.py --months 6 --tickers AAPL TSLA NVDA MSFT AMD META SPY QQQ

    # Include TIMEOUT signals as LOSS (more conservative):
    python scripts/ml/train_historical.py --interval d --months 36 --include-timeout

Output
------
    models/ml_model_historical.pkl   — trained model bundle (Platt-calibrated)
    models/training_dataset.csv      — full labelled dataset (inspect/audit)

Environment variables required
------------------------------
    EODHD_API_KEY  — your EODHD API key

Changes (Mar 12 2026)
---------------------
    --months default raised from 4 → 6 (more history for 3-fold WF CV).
    train_from_dataframe() now runs 3-fold walk-forward CV internally;
    the explicit walk_forward_split() call is removed.
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
    parser.add_argument('--months',   type=int,   default=6)
    parser.add_argument('--tickers',  nargs='+',  default=DEFAULT_TICKERS)
    parser.add_argument('--interval', type=str,   default='5m')
    parser.add_argument('--rvol-min', type=float, default=None)
    parser.add_argument('--include-timeout', action='store_true')
    parser.add_argument('--model-name', type=str, default='ml_model_historical')
    parser.add_argument('--min-samples', type=int, default=50)
    args = parser.parse_args()

    api_key = os.getenv('EODHD_API_KEY', '')
    if not api_key:
        logger.error("EODHD_API_KEY not set. Export it and retry.")
        sys.exit(1)

    MODELS_DIR.mkdir(parents=True, exist_ok=True)

    from app.backtesting.historical_trainer import RVOL_MIN_DAILY, _INTRADAY_INTERVALS
    is_daily     = args.interval not in _INTRADAY_INTERVALS
    rvol_default = RVOL_MIN_DAILY if is_daily else 2.0
    rvol_min     = args.rvol_min if args.rvol_min is not None else rvol_default

    from app.backtesting.historical_trainer import HistoricalMLTrainer
    trainer = HistoricalMLTrainer(
        eodhd_api_key=api_key,
        interval=args.interval,
        rvol_min=rvol_min,
    )

    print("\n" + "="*62)
    print(" WAR MACHINE  —  Historical ML Pre-Training")
    print("="*62)
    print(f" Tickers  : {', '.join(args.tickers)}")
    print(f" History  : {args.months} months  (interval={args.interval})")
    print(f" RVOL min : {rvol_min}")
    print(f" Splits   : 3-fold walk-forward CV + Platt calibration")
    print("="*62 + "\n")

    df = trainer.build_dataset(
        tickers=args.tickers,
        months_back=args.months,
        include_timeout=args.include_timeout,
        interval_override=args.interval,
    )

    if df.empty:
        logger.error("Dataset is empty — check EODHD key and ticker list.")
        sys.exit(1)

    print("\n" + trainer.summary(df) + "\n")

    csv_path = MODELS_DIR / 'training_dataset.csv'
    df.to_csv(csv_path, index=False)
    print(f" Dataset saved → {csv_path}")

    if len(df) < args.min_samples:
        logger.error(f"Only {len(df)} labelled signals — need {args.min_samples} minimum.")
        sys.exit(1)

    from app.ml.ml_trainer import train_from_dataframe
    model_path = MODELS_DIR / f"{args.model_name}.pkl"

    print("\n Training model — 3-fold walk-forward CV + Platt scaling...")
    model, metrics = train_from_dataframe(
        train_df=df,
        val_df=None,
        model_path=str(model_path),
    )

    if model is None:
        logger.error(f"Training failed: {metrics.get('error')}")
        sys.exit(1)

    print("\n" + "="*62)
    print(" TRAINING RESULTS")
    print("="*62)
    print(f"  CV Accuracy    : {metrics['cv_mean']:.2%} (±{metrics['cv_std']:.2%})")
    print(f"  Final Accuracy : {metrics['accuracy']:.2%}")
    print(f"  Final Precision: {metrics['precision']:.2%}")
    print(f"  Final Recall   : {metrics['recall']:.2%}")
    print(f"  Threshold      : {metrics['threshold']:.3f}")
    print()
    print("  Top features:")
    for feat, imp in sorted(metrics['feature_importance'].items(),
                             key=lambda x: x[1], reverse=True)[:8]:
        print(f"    {feat:<28} {imp:.3f}")
    print(f"\n  Model saved → {model_path}")
    print("="*62)
    print("\n  See app/ml/INTEGRATION.md for wiring steps.\n")


if __name__ == '__main__':
    main()
