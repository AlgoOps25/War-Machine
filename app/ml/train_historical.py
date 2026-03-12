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
    python -m app.ml.train_historical --months 6 --tickers AAPL TSLA NVDA MSFT AMD META SPY QQQ

    # Include TIMEOUT signals as LOSS (more conservative):
    python -m app.ml.train_historical --interval d --months 36 --include-timeout

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
    the explicit walk_forward_split() call is removed — the full df is
    passed directly so the trainer controls the splits chronologically.
    Results output extended with per-fold CV breakdown.
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
    parser.add_argument('--months',   type=int,   default=6,
                        help='Months of history to fetch (default: 6)')
    parser.add_argument('--tickers',  nargs='+',  default=DEFAULT_TICKERS,
                        help='Space-separated ticker list')
    parser.add_argument('--interval', type=str,   default='5m',
                        help="Bar interval: '5m' intraday or 'd' daily (default: 5m)")
    parser.add_argument('--rvol-min', type=float, default=None,
                        help='Min RVOL to trigger signal (default: 2.0 intraday / 1.3 daily)')
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
    print(f" Splits   : 3-fold walk-forward CV + Platt calibration")
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

    # ── Train model (3-fold WF-CV + Platt scaling inside train_from_dataframe)
    from app.ml.ml_trainer import train_from_dataframe

    model_path = MODELS_DIR / f"{args.model_name}.pkl"

    print("\n Training model — 3-fold walk-forward CV + Platt scaling...")
    # Pass the full df directly; train_from_dataframe handles chronological splits
    model, metrics = train_from_dataframe(
        train_df   = df,
        val_df     = None,
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
    print(f"  Val samples    : {metrics['n_val']}  (last WF fold)")
    print(f"  Calibrated     : {'✅ Yes (Platt/sigmoid)' if metrics.get('calibrated') else '❌ No'}")
    print()
    print("  Walk-forward fold breakdown:")
    for fm in metrics.get('fold_metrics', []):
        print(
            f"    Fold {fm['fold']}  train={fm['n_train']:>4}  val={fm['n_val']:>4}  "
            f"Prec={fm['precision']:.2%}  Rec={fm['recall']:.2%}  F1={fm['f1']:.2%}"
        )
    print()
    print(f"  CV Accuracy    : {metrics['cv_mean']:.2%} (±{metrics['cv_std']:.2%})")
    print(f"  CV Precision   : {metrics.get('cv_precision_mean', 0):.2%}")
    print(f"  CV Recall      : {metrics.get('cv_recall_mean', 0):.2%}")
    print(f"  Final Accuracy : {metrics['accuracy']:.2%}")
    print(f"  Final Precision: {metrics['precision']:.2%}")
    print(f"  Final Recall   : {metrics['recall']:.2%}")
    print(f"  Threshold      : {metrics['threshold']:.3f}")
    print()
    print("  Top features by importance:")
    for feat, imp in sorted(metrics['feature_importance'].items(),
                             key=lambda x: x[1], reverse=True)[:8]:
        bar_str = '█' * max(1, int(imp * 40))
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
