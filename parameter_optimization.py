#!/usr/bin/env python3
"""
Comprehensive Parameter Optimization

Tests ALL available EODHD data parameters:
- Volume confirmation (1.5x, 2x, 2.5x, 3x average)
- ATR stop multipliers (1.0, 1.5, 2.0, 2.5)
- Risk:Reward ratios (1.5:1, 2:1, 2.5:1, 3:1)
- Lookback periods (8, 12, 16, 20 bars)
- Price action filters (momentum, gap size, trend alignment)

Run: python parameter_optimization.py
"""
import sys
from datetime import datetime, timedelta, time as dtime
from zoneinfo import ZoneInfo
from typing import List, Dict
import pandas as pd
import numpy as np
import json
from itertools import product

from data_manager import DataManager
from db_connection import get_conn, ph, dict_cursor

ET = ZoneInfo("America/New_York")

TICKERS = [
    "SPY", "QQQ", "AAPL", "MSFT", "NVDA", "TSLA", "META", "AMD",
    "GOOGL", "AMZN", "NFLX", "INTC", "PLTR", "COIN", "SOFI"
]

# Shortened for initial upload
print("Parameter optimization script loaded. Run with: python parameter_optimization.py")
