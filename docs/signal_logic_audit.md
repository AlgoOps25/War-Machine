# War Machine Signal Logic Audit

This document is maintained by the assistant to track the ongoing end-to-end audit of War Machine's signal logic and execution pipeline.

## Scope

- Repository: AlgoOps25/War-Machine
- Focus: Data → Screening → Signals → Risk/Execution → Surrounding services
- Goal: Mathematically clear, invariant-based signal logic with no edge-case failure modes.

## Working Methodology

- Audit is performed in batches, aligned to the live signal pipeline rather than directory layout.
- For each batch we:
  - Document current behaviour and assumptions.
  - Define explicit invariants (what must always be true for correctness).
  - Identify issues, ambiguities, and edge cases.
  - Propose concrete code changes and new/updated tests.
  - Record decisions and rationale here.

## Batches

### Batch 1: Core signal path (in progress)

**Modules**
- app/data/data_manager.py
- ws_feed.py
- app/screening/market_calendar.py
- app/screening/dynamic_screener.py
- app/screening/premarket_scanner.py
- app/screening/volume_analyzer.py
- app/screening/watchlist_funnel.py
- app/risk/position_manager.py

**Objectives**
- Ensure every live signal is based on:
  - Correct and complete bar data (1m + 5m, WS-first with safe REST fallback).
  - A well-defined, time-aware universe and scoring model.
  - A watchlist funnel whose stage transitions and thresholds are consistent with the stated timeline and intent.
  - Execution and risk rules that strictly enforce RTH guard, R:R thresholds, circuit-breaker and max-drawdown limits, and T1/T2 invariants.
- Eliminate race conditions and stale-cache edge cases between WS, REST, screener, and position manager.

**Status**
- Plan agreed with maintainer (Michael) on 2026-03-18.
- Detailed findings and recommendations for each module will be appended in subsequent sections as the audit progresses.

---

_This file will be updated continuously as we work through each batch so it stays in sync with the current understanding and decisions from the audit._
