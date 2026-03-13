# app/filters/__init__.py
# Required for Python to treat app/filters/ as a package.
# Without this file, `from app.filters.market_regime_context import ...`
# raises ModuleNotFoundError at boot despite the .py file existing on disk.
# Phase 1.26a fix — restores SPY EMA context (5m EMA 9/21/50) in sniper.py
