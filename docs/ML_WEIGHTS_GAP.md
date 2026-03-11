# ML Weights Loop — Open Gap

**Status:** ⚠️ **OPEN — weights recorded but not fed back into `compute_confidence()`**

## The Gap

`app/ai/ai_learning.py` does two things:

1. **Records** trade outcomes and updates `confirmation_weights` (a per-signal-type
   weighting dict) based on whether signals with certain confirmation patterns won or lost.

2. **Scores** new signals via `compute_confidence(signal_data)` — but this function
   currently uses **static grade baselines** from `GRADE_RANGES`, not the evolved
   `confirmation_weights` that have been built up from live trade outcomes.

The learning loop is half-built: weights are being updated but never consumed.

## Impact

- Signals continue to be scored as if no trade history exists
- The `confirmation_weights` dict grows but has zero effect on live decisions
- `ai_learning.py` appears to be adapting — but it isn't

## Fix Plan

In `compute_confidence()`, after computing the base grade score, apply a
weighted adjustment from `confirmation_weights`:

```python
def compute_confidence(signal_data: dict) -> float:
    base = _grade_to_base_confidence(signal_data.get('grade', 'C'))

    # Apply learned confirmation weights
    weight_boost = 0.0
    for conf_key, conf_present in signal_data.get('confirmations', {}).items():
        if conf_present and conf_key in self.confirmation_weights:
            weight_boost += self.confirmation_weights[conf_key] * WEIGHT_SCALE

    return _clamp_confidence(base + weight_boost)
```

## Priority

**Medium** — system functions correctly without this. Closing the loop is the
path to genuine ML-driven confidence improvement over time.

Tracked as a future phase item. When ready, address in `Phase 2.x`.

Last audited: **Phase 1.23 (Mar 10, 2026)**
