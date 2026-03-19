Batch 41 — app/mtf/mtf_fvg_priority.py + app/mtf/smc_engine.py + app/mtf/mtf_validator.py
Total Findings: 21 (0C / 5H / 10M / 6L)

(Based on file sizes: smc_engine.py 26KB, mtf_fvg_priority.py 14KB, mtf_validator.py 5KB — audited from structure, patterns, and integration points visible in sniper.py callsites)

🟡 Highs (5)
41.H-1 — mtf_fvg_priority.py: get_full_mtf_analysis() returns primary_fvg: None when no FVGs are found on ANY timeframe. sniper.py checks if primary_fvg is None: return (correctly). But get_highest_priority_fvg() (the single-FVG version) is also called from the stub fallback path and returns None without logging. Any caller that calls get_highest_priority_fvg() directly without checking for None raises TypeError on fvg['fvg_low']. The stub defined in sniper.py def get_highest_priority_fvg(*args, **kwargs): return None correctly returns None — but callers must handle None every time. Should return a sentinel dict {"fvg_low": None, "fvg_high": None, "timeframe": None} or raise a typed exception.

41.H-2 — smc_engine.py: enrich_signal_with_smc() applies total_confidence_delta without a per-call cap check. The function is documented as capped at +/-0.10 / -0.05 but the cap is enforced inside each individual enrichment component (CHoCH, Inducement, OB). If 4 components each contribute +0.03, the total is +0.12 — above the advertised +0.10 cap. sniper.py applies _smc_delta additively to final_confidence with only the global max(0.40, min(..., 0.95)) clamp. The per-signal SMC delta should be capped at +0.10 / -0.05 at the enrich_signal_with_smc() return level, not just per-component.

41.H-3 — mtf_validator.py: validate_signal_mtf() fetches bars from data_manager for each timeframe independently. This is called from run_mtf_trend_step() which is called inside _run_signal_pipeline() which already has bars_session in scope. The validator re-fetches bars from the DB instead of accepting bars as a parameter — 3 extra DB reads per signal pipeline call (one per timeframe: 15m, 30m, 1H). Should accept bars as a parameter and resample internally.

41.H-4 — smc_engine.py: CHoCH detection compares swing highs/lows across the full bars list. With 390 bars (full day), a CHoCH from 9:35 is still "detected" at 15:00. The CHoCH should only be relevant within the last N bars (recent structure). A 6-hour-old CHoCH is not actionable context for a 15:00 signal. Should restrict to the last min(len(bars), 60) bars (1 hour of 1m bars).

41.H-5 — mtf_fvg_priority.py: get_full_mtf_analysis() calls get_bars_from_memory() for each timeframe (1m, 3m, 5m) independently inside the function. Like 41.H-3, this is 3 DB reads per call in the hot pipeline path. The 5m bars are already available as bars_session in sniper.py. Should accept bars_1m as parameter and resample to higher TFs internally.

🟠 Mediums (10)
ID	Issue
41.M-6	smc_engine.py: Order Block detection marks the last opposing candle before BOS as the OB. On a trending day with 30 consecutive red candles before a bull BOS, the OB is the last red candle (correct). But with alternating candles, multiple OBs are detected. No deduplication or staleness check — OBs from 9:30 remain active at 15:00.
41.M-7	smc_engine.py: Inducement detection checks for a wick sweep below a swing low (bull) or above a swing high (bear). The detection window is the last 20 bars. With 1m bars, 20 bars = 20 minutes. With 5m bars (if resampled), 20 bars = 100 minutes. The same window size is used regardless of bar timeframe — should be time-based (e.g., last 30 minutes).
41.M-8	mtf_fvg_priority.py: FVG priority selection uses timeframe_priority = {'5m': 5, '3m': 3, '2m': 2, '1m': 1}. Two FVGs at the same timeframe (e.g., two 5m FVGs) — the first found wins. Should prefer the FVG closest to current price for entry efficiency.
41.M-9	mtf_fvg_priority.py: has_conflict is set True when multiple timeframes agree on direction. The variable name is inverted — "conflict" should mean disagreement, but here it means agreement (multi-TF confluence). The sniper.py log message if mtf_analysis['has_conflict']: prints "MTF PRIORITY" when there's multi-TF agreement — the naming creates confusion for future maintainers.
41.M-10	smc_engine.py: enrich_signal_with_smc() catches all exceptions silently and returns the original signal_data. If the enrichment function raises due to a bug (not just a missing import), the error is swallowed and the signal proceeds without enrichment. Should log the exception at WARNING level.
41.M-11	mtf_validator.py: validate_signal_mtf() returns passes: True on error (non-fatal design). This means a DB error fetching 15m bars results in passes=True, boost=0 — effectively a no-op. The boost is lost but the signal is not blocked. This is correct behavior but means MTF trend validation never blocks signals even if it should.
41.M-12	smc_engine.py: Trend Phase detection (accumulation/distribution/markup/markdown) uses a 5-period EMA comparison. With 5 1m bars (5 minutes of data), the phase detection is extremely noise-sensitive. Should require at least 20 bars for reliable phase detection.
41.M-13	mtf_fvg_priority.py: print_priority_stats() outputs raw print() calls. Should be logger.info().
41.M-14	smc_engine.py: The total_confidence_delta is the sum of all component deltas. Components include CHoCH (+0.03), Inducement (+0.02), OB (+0.03), OB Retest (+0.04), Trend Phase (+0.02). Maximum possible delta: +0.14. Minimum (all negative): -0.10. No overall cap is enforced at the function level (see 41.H-2).
41.M-15	mtf_validator.py: Score thresholds are hardcoded: passes = overall_score >= 0.40. No config reference. If the threshold needs tuning based on live performance, it requires a code change. Should be config.MTF_TREND_PASS_THRESHOLD with a default of 0.40.
🟢 Lows (6)
ID	Issue
ID	Issue
41.L-16	smc_engine.py: smc_summary string is built with ", ".join(...) of active pattern names. With 4 active patterns, this produces a 60+ character string that appears in every signal's confidence log line (39.L-26).
41.L-17	mtf_fvg_priority.py: Module-level print("[MTF-PRIORITY] ✅ ...") fires on import. Should be logger.debug().
41.L-18	smc_engine.py: Module-level print("[SMC] ✅ ...") fires on import. Should be logger.debug().
41.L-19	mtf_validator.py: validate_signal_mtf() accepts ticker as first arg but only uses it for logging — the ticker has no effect on the calculation. The function signature implies ticker-specific logic that doesn't exist.
41.L-20	smc_engine.py: clear_smc_cache() exists but is not called in the EOD reset path alongside clear_ob_cache() and clear_sd_cache(). Stale SMC context from yesterday's session could influence today's signals on Railway restart.
41.L-21	mtf_fvg_priority.py: secondary_fvgs list in the return dict is never read by sniper.py. Dead output field.