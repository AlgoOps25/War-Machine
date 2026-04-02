"""
app/futures/__init__.py

Futures trading package for War Machine.
Provides NQ/MNQ ORB signal generation, completely isolated from the
equity options system. No imports from app.options, app.validation
(greeks), or any equity-specific screener modules.

Public API:
    FuturesORBScanner  — main scanner class
    start_futures_loop — thread-safe loop entry point (called by scanner.py)
"""
from app.futures.futures_orb_scanner import FuturesORBScanner
from app.futures.futures_scanner_loop import start_futures_loop

__all__ = ["FuturesORBScanner", "start_futures_loop"]
