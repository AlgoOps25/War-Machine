# Signal Generator Restoration

The signal_generator.py file was accidentally overwritten. 

## Quick Fix:

```powershell
# Get the correct file from main
git checkout main -- signal_generator.py

# Then add the analytics close tracking
# Edit signal_generator.py and find the _close_signal() method (line ~605)
# Add this code block after P&L calculation:

# Log signal outcome to analytics database
if ANALYTICS_ENABLED and signal_tracker and 'signal_id' in signal:
    try:
        outcome = 'win' if pnl > 0 else 'loss'
        signal_tracker.record_signal_closed(
            signal_id=signal['signal_id'],
            exit_price=exit_price,
            outcome=outcome
        )
        print(f"[ANALYTICS] Signal {signal['signal_id']} closed - {outcome.upper()} (${pnl:.2f}, {pnl_pct:+.2f}%)")
    except Exception as e:
        print(f"[ANALYTICS] Close tracking error: {e}")
```

## Commit the fix:

```powershell
git add signal_generator.py
git commit -m "Add analytics close tracking to signal_generator.py"
git push origin feature/analytics-integration
```
