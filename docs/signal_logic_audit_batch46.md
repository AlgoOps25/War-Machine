Batch 46 — app/mtf/mtf_compression.py + app/mtf/mtf_validator.py (remaining) + Cross-Cutting Summary
Total Findings: 14 (0C / 2H / 7M / 5L)

🟡 Highs (2)
46.H-1 — mtf_compression.py: compress_to_3m(), compress_to_2m(), compress_to_1m() assume input bars are 1-minute bars. If bars_5m (5-minute bars from scanner.py) is passed to these functions (as it is from check_mtf_convergence()), compress_to_3m(bars_5m) produces bars with 3× the 5-minute duration = 15-minute bars. compress_to_2m(bars_5m) produces 10-minute bars. The function names and docstrings imply output timeframe but the actual output depends entirely on input bar resolution. mtf_integration.py calls these with bars_session which comes from data_manager.get_today_session_bars() — if that returns 1m bars, compression is correct. If it returns 5m bars (as the variable name implies), all compressed timeframes are 5× longer than intended. Should validate input bar interval and document the assumption explicitly.

46.H-2 — mtf_compression.py: The bucketing logic uses datetime.replace(minute=(dt.minute // N) * N, second=0, microsecond=0) — the same pattern as the _resample_bars() function defined inside sniper.py's _run_signal_pipeline(). Two independent implementations of the same bar resampler exist in the codebase (sniper.py inline, mtf_compression.py module). They will diverge over time. sniper.py's inline version (39.H-3) should be deleted and replaced with imports from mtf_compression.py. Single implementation, single bug surface.

🟠 Mediums (7)
ID	Issue
ID	Issue
46.M-3	mtf_compression.py: compress_to_3m() groups bars by (dt.minute // 3) * 3 — standard floor bucketing. But for 2m bars: (dt.minute // 2) * 2. At 9:30, 9:31 → bucket 9:30. At 9:32, 9:33 → bucket 9:32. The OR window 9:30–9:40 produces 5 complete 2m bars. At 9:39, the bar at 9:39 is the start of the 9:38–9:39 bucket — only 1 bar, incomplete. The last bucket in any window is always potentially incomplete (1 bar instead of N). Should mark incomplete buckets and exclude them from pattern detection.
46.M-4	mtf_compression.py: No handling of gaps in bar data. If bars skip from 9:45 to 9:47 (e.g., low-volume ticker with no trades at 9:46), the 9:45 2m bucket contains only 1 bar. The compressed bar represents 1 minute of data but is labeled as a 2-minute bar. Downstream pattern detection (FVG, BOS) treats it as a complete 2m candle, potentially misclassifying the structure.
46.M-5	mtf_compression.py: The three compression functions (compress_to_3m, compress_to_2m, compress_to_1m) are structurally identical — same logic, different divisor. Should be a single compress_bars(bars, minutes) function. The three named functions can be thin Continuing exactly where Batch 46 left off:

| 46.M-5 | compress_to_3m, compress_to_2m, compress_to_1m are structurally identical — same logic, different divisor. Should be a single compress_bars(bars, minutes) function. The three named functions can be thin wrappers: def compress_to_3m(bars): return compress_bars(bars, 3). DRY violation — a bug fix to the core bucketing logic must be applied to all three functions manually. |
| 46.M-6 | mtf_compression.py: compress_to_1m() takes bars and returns them grouped into 1-minute buckets. If input is already 1m bars, this is a no-op identity transform that iterates all bars twice (once to group, once to aggregate). Called from check_mtf_convergence() with bars_5m which, if truly 5m bars, returns 1-minute compressed bars from 5m input — meaning each output "1m" bar is actually a 5m bar relabeled. |
| 46.M-7 | mtf_compression.py: The aggregation for each compressed bar sets "datetime" to the first bar in the bucket's datetime. This means the compressed bar's timestamp is the open of the bucket, not the close. is_valid_entry_time() in bos_fvg_engine.py compares bar["datetime"].time() against HARD_CLOSE_TIME = 15:45. A compressed 5m bar whose open is 15:40 passes the time filter even though it closes at 15:45 — where a new entry at 15:41 (next bar open) would be beyond HARD_CLOSE_TIME. Minor but can allow one spurious late-session entry on the last compressed bar of the day. |
| 46.M-8 | mtf_compression.py: compress_to_3m() uses defaultdict(list) keyed by bucket datetime. The final sort: sorted(compressed.items()) sorts by datetime key — correct. But sorted() on datetime objects uses chronological order only if all datetimes are tz-aware or all tz-naive. If a mix of aware and naive datetimes reaches the compression function (the tz-aware/naive bug family — 44.H-2), sorted() raises TypeError: can't compare offset-naive and offset-aware datetimes. This would surface as a crash in check_mtf_convergence() on any session where the DB returns mixed tz bars. |
| 46.M-9 | mtf_compression.py: volume aggregation uses sum(b["volume"] for b in bucket_bars) — correct. But open uses bucket_bars[0]["open"] and close uses bucket_bars[-1]["close"]. If bucket_bars is not sorted by time (e.g., bars arrive out of order from data_manager.get_today_session_bars() on a cache miss), the open and close will be incorrect. Should sort bucket_bars by datetime before extracting open/close. |

🟢 Lows (5)
ID	Issue
46.L-10	mtf_compression.py: No module docstring. Given that input bar resolution is the critical assumption (see 46.H-1), this module above all others needs a clear docstring stating: "Assumes 1-minute input bars. All output timeframes are relative to input resolution."
46.L-11	mtf_compression.py: compress_to_1m() has a misleading name. It doesn't compress to 1m — it regroups bars into 1m buckets (only useful if input has sub-1m bars, which War Machine never produces). The function name implies downsampling but performs upsampling from sub-1m (which doesn't exist) or identity transform for 1m input. Should be named group_to_1m_buckets() or simply removed.
46.L-12	mtf_compression.py: high aggregation uses max(b["high"] for b in bucket_bars) and low uses min(b["low"] for b in bucket_bars) — correct for OHLC aggregation. However vwap is not aggregated (not present in compressed bar dict). If any downstream function calls bar["vwap"] on a compressed bar, it raises KeyError. Should add "vwap": None as a placeholder.
46.L-13	mtf_compression.py: The three compression functions import defaultdict at the module level — correct. But from datetime import datetime is imported but datetime is only used in type hints via bt.replace(...) on bar datetimes. No explicit datetime object is constructed. The import is used indirectly (duck typing on bar dicts) — safe but could be removed.
46.L-14	mtf_compression.py: No unit tests referenced or present. Given that 46.H-1 (wrong input resolution assumption) and 46.M-8 (tz-aware sort crash) are latent bugs that only surface at runtime with real bar data, this module is the highest-priority candidate for unit tests in the entire app/mtf/ directory.
Batches 40–46 — Master Summary
Batch	File(s)	Findings	C	H	M	L
40	bos_fvg_engine.py + mtf_integration.py	19	0	4	9	6
41	mtf_fvg_priority.py + smc_engine.py + mtf_validator.py	21	0	5	10	6
42	app/filters/ (6 files)	23	0	5	11	7
43	greeks_precheck.py + vwap_reclaim.py + signal_generator_cooldown.py	18	0	4	9	5
44	config.py + time_helpers.py + production_helpers.py	17	0	3	9	5
45	discord_helpers.py + app/screening/	16	0	3	8	5
46	mtf_compression.py + cross-cutting wrap	14	0	2	7	5
Total	Batches 40–46	128	0	26	63	39
Top 5 Highest-Impact Findings Across Batches 40–46
44.H-2 — _strip_tz() in time_helpers.py drops TZ without converting to ET first. Root cause of 15+ tz-naive bugs across the entire codebase. Single fix, massive blast-radius improvement.

40.H-3 — check_fvg_entry() bounce check uses fvg_mid instead of fvg_high/low. FVG confirmations are firing on bars still inside the gap — entries before the bounce is complete.

40.H-2 — detect_bos() only evaluates the single latest bar. BOS events that occurred 1–2 cycles ago are permanently undetected, silently dropping valid setups.

45.H-3 — screener_integration stub always returns qualified: False. Explosive mover override never fires. All trade records have rvol=0.0, corrupting signal quality analytics permanently.

46.H-1 — mtf_compression.py assumes 1m input. If bars_session is 5m data, all compressed timeframes are 5× too long — the "3m" TF is actually 15m, "2m" is 10m, making MTF convergence meaningless.