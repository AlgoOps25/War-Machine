"""
Position Manager - Consolidated Position Tracking, Sizing, and Win Rate Analysis
Replaces: position_tracker.py, position_sizing.py, win_rate_tracker.py

Features:
  - Portfolio-level risk tracking (max drawdown, exposure limits)
  - Correlation-based position limits (sector/ticker concentration)
  - Dynamic position sizing (performance-based + VIX-based adjustment)
  - Risk/reward validation (minimum R:R requirements)
  - Circuit breaker (daily loss limits)
  - Signal tracking when trades execute (links signals to positions)
  - RTH guard: blocks new positions outside 9:30 AM - 4:00 PM ET

Module-level helpers (SECTOR_GROUPS, date helpers, _write_completed_at)
have been extracted to position_helpers.py for clarity.

PHASE C1 FIX (MAR 10, 2026):
  - FIXED: _load_session_state() now re-populates self.positions from DB on startup

FIXED M5 (MAR 10, 2026):
  - close_all_eod() resets streak counters after EOD close.

FIX #4 (MAR 11, 2026):
  - close_position() calls _write_completed_at() after every real close.

FIX #5 (MAR 13, 2026):
  - 10s TTL cache on get_daily_stats() and get_open_positions().

FIX #6 (MAR 14, 2026):
  - _check_risk_limits() testable wrapper around can_open_position().

FIX #7 (MAR 14, 2026):
  - Python 3.10 f-string backslash compat in get_risk_summary().

FIX #8 (MAR 15, 2026):
  - close_position() circuit-breaker check uses real session P&L.

FIX #9 (MAR 15, 2026):
  - check_exits() re-reads t1_hit from DB after _scale_out().

FIX #10 (MAR 16, 2026):
  - Unicode surrogate pair fix for rotate/siren emojis.

FIX #11 (MAR 19, 2026):
  - SQLite AT TIME ZONE crash fix via _date_eq_today / _date_lt_today helpers.

FIX #12 (MAR 25, 2026):
  - Corrected RTH import: app.analytics.rth_filter -> app.filters.rth_filter
    and function name is_rth_now -> is_rth. Prior broken import caused
    _RTH_GUARD_ENABLED to always be False (silent fallback), disabling
    the RTH guard on every session.

FIX #13 (MAR 26, 2026):
  - get_win_rate() used _date_eq_today("exit_time") in a >= clause — the
    name implied equality but was structurally a date extractor. Added
    _date_col() alias to position_helpers.py and updated this call site.
    No runtime behaviour change (the SQL fragment is identical); fixes
    misleading code that could confuse future readers or tools.
"""
from utils import config
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
import logging
logger = logging.getLogger(__name__)

_ET = ZoneInfo("America/New_York")

from typing import Dict, List, Optional, Tuple
from app.data import db_connection
from app.data.db_connection import get_conn, return_conn, ph, dict_cursor, serial_pk, USE_POSTGRES
import time

# ── Import helpers from position_helpers ───────────────────────────────────────────────────────────────────
from app.risk.position_helpers import (
    SECTOR_GROUPS,
    _STATS_CACHE_TTL,
    _POSITIONS_CACHE_TTL,
    _date_col,          # FIX #13: range queries (get_win_rate)
    _date_eq_today,
    _date_lt_today,
    _write_completed_at,
)

# ── VIX sizing (graceful fallback if module unavailable) ──────────────────────────────────────────
try:
    from app.risk.vix_sizing import get_vix_multiplier as _get_vix_mult
    _VIX_SIZING_ENABLED = True
except ImportError:
    _VIX_SIZING_ENABLED = False
    def _get_vix_mult(): return 1.0

# ── RTH guard (FIX #12: corrected path app.filters.rth_filter and function is_rth) ──
try:
    from app.filters.rth_filter import is_rth as _is_rth_now
    _RTH_GUARD_ENABLED = True
except ImportError:
    _RTH_GUARD_ENABLED = False
    def _is_rth_now(): return True  # Assume RTH if filter unavailable

# FIXED: Correct import path for signal_analytics
try:
    from app.signals.signal_analytics import signal_tracker
    SIGNAL_TRACKING_ENABLED = True
    logger.info("[POSITION] \u2705 Signal trade tracking enabled (signal_analytics)")
except ImportError:
    signal_tracker = None
    SIGNAL_TRACKING_ENABLED = False
    logger.info("[POSITION] \u26a0\ufe0f  Signal trade tracking disabled (signal_analytics not available)")


class PositionManager:

    def __init__(self, db_path: str = None):
        self.db_path = db_path or "market_memory.db"
        self.positions = []  # Active positions cache

        self.account_size = getattr(config, "ACCOUNT_SIZE", 25_000)
        self.intraday_high_water_mark = self.account_size
        self.session_starting_balance = self.account_size
        self.max_daily_loss_pct = getattr(config, "MAX_DAILY_LOSS_PCT", 3.0)
        self.max_open_positions = getattr(config, "MAX_OPEN_POSITIONS", 5)
        self.max_sector_exposure_pct = getattr(config, "MAX_SECTOR_EXPOSURE_PCT", 40.0)
        self.min_risk_reward_ratio = getattr(config, "MIN_RISK_REWARD_RATIO", 1.5)

        self.consecutive_wins = 0
        self.consecutive_losses = 0
        self.performance_multiplier = 1.0  # 0.5-1.5 range based on recent performance

        # ── FIX #5: DB query result caches ─────────────────────────────────────────────────────────
        self._daily_stats_cache:     Optional[Dict] = None
        self._daily_stats_ts:        float          = 0.0
        self._open_positions_cache:  Optional[List] = None
        self._open_positions_ts:     float          = 0.0
        # ─────────────────────────────────────────────────────────────────────────────

        self._initialize_database()
        self._close_stale_positions()
        self._load_session_state()

    # ── FIX #5: cache invalidation helper ───────────────────────────────────────────────────────────
    def _invalidate_caches(self) -> None:
        """Bust both caches immediately after any write (open/close)."""
        self._daily_stats_cache    = None
        self._daily_stats_ts       = 0.0
        self._open_positions_cache = None
        self._open_positions_ts    = 0.0
    # ───────────────────────────────────────────────────────────────────────────

    def _load_session_state(self) -> None:
        """Load session starting balance, open positions, and performance streak on initialization."""
        try:
            stats = self.get_daily_stats()
            total_pnl = stats.get("total_pnl", 0.0)

            self.account_size = self.session_starting_balance + total_pnl
            self.intraday_high_water_mark = max(self.intraday_high_water_mark, self.account_size)

            # ── C1 FIX: Re-populate in-memory cache from DB on restart ──────────────────────────────
            open_db = self.get_open_positions()
            self.positions = [
                {
                    "id":                  pos["id"],
                    "ticker":              pos["ticker"],
                    "direction":           pos["direction"],
                    "entry":               pos["entry_price"],
                    "stop":                pos["stop_price"],
                    "t1":                  pos["t1_price"],
                    "t2":                  pos["t2_price"],
                    "contracts":           pos["contracts"],
                    "remaining_contracts": pos["remaining_contracts"],
                    "grade":               pos["grade"],
                    "confidence":          pos["confidence"],
                    "t1_hit":              bool(pos["t1_hit"]),
                    "pnl":                 pos["pnl"] or 0.0,
                }
                for pos in open_db
            ]
            if self.positions:
                tickers = ", ".join(p["ticker"] for p in self.positions)
                print(f"[RISK] \U0001f504 Reloaded {len(self.positions)} open position(s) "
                      f"from DB after restart: {tickers}")
            else:
                logger.info("[RISK] \u2705 No open positions to reload \u2014 clean session start")
            # ────────────────────────────────────────────────────────────────────────────────

            closed_trades = self.get_todays_closed_trades()
            if closed_trades:
                self._update_performance_streak(closed_trades)

            print(f"[RISK] Session loaded | Balance: ${self.account_size:,.0f} | "
                  f"P&L: ${total_pnl:+.0f} | Streak: {self._format_streak()}")

        except Exception as e:
            logger.info(f"[RISK] Session state load error: {e}")

    def _update_performance_streak(self, trades: List[Dict]) -> None:
        """Update consecutive win/loss streak for dynamic sizing."""
        if not trades:
            return

        self.consecutive_wins = 0
        self.consecutive_losses = 0

        for trade in reversed(trades):
            pnl = trade.get("pnl", 0.0)
            if pnl > 0:
                if self.consecutive_losses > 0:
                    break
                self.consecutive_wins += 1
            else:
                if self.consecutive_wins > 0:
                    break
                self.consecutive_losses += 1

        if self.consecutive_losses >= 3:
            self.performance_multiplier = 0.5
        elif self.consecutive_losses >= 2:
            self.performance_multiplier = 0.75
        elif self.consecutive_wins >= 3:
            self.performance_multiplier = 1.25
        elif self.consecutive_wins >= 2:
            self.performance_multiplier = 1.1
        else:
            self.performance_multiplier = 1.0

    def _format_streak(self) -> str:
        """Format performance streak for display."""
        if self.consecutive_wins > 0:
            return f"{self.consecutive_wins}W (x{self.performance_multiplier:.2f})"
        elif self.consecutive_losses > 0:
            return f"{self.consecutive_losses}L (x{self.performance_multiplier:.2f})"
        else:
            return "0 (x1.00)"

    def check_circuit_breaker(self, stats: Dict = None) -> Tuple[bool, str]:
        """
        Check if daily loss limit has been hit.
        Accepts optional pre-fetched stats dict to avoid a redundant DB call.
        Returns (is_breached, reason).
        """
        if stats is None:
            stats = self.get_daily_stats()
        total_pnl = stats.get("total_pnl", 0.0)
        daily_loss_pct = (total_pnl / self.session_starting_balance) * 100

        if daily_loss_pct <= -self.max_daily_loss_pct:
            reason = (
                f"CIRCUIT BREAKER TRIGGERED: Daily loss limit reached "
                f"({daily_loss_pct:.1f}% / -{self.max_daily_loss_pct}% max)"
            )
            return True, reason

        return False, ""

    def check_max_drawdown(self, stats: Dict = None) -> Tuple[bool, str]:
        """
        Check if max drawdown from intraday high has been exceeded.
        Accepts optional pre-fetched stats dict to avoid a redundant DB call.
        Returns (is_breached, reason).
        """
        if stats is None:
            stats = self.get_daily_stats()
        total_pnl = stats.get("total_pnl", 0.0)
        current_balance = self.session_starting_balance + total_pnl

        drawdown = ((current_balance - self.intraday_high_water_mark) /
                    self.intraday_high_water_mark) * 100

        if current_balance > self.intraday_high_water_mark:
            self.intraday_high_water_mark = current_balance

        max_drawdown_pct = getattr(config, "MAX_INTRADAY_DRAWDOWN_PCT", 5.0)
        if drawdown <= -max_drawdown_pct:
            reason = (
                f"MAX DRAWDOWN EXCEEDED: {drawdown:.1f}% from peak "
                f"(${self.intraday_high_water_mark:,.0f} \u2192 ${current_balance:,.0f})"
            )
            return True, reason

        return False, ""

    def can_open_position(self, ticker: str, risk_dollars: float) -> Tuple[bool, str]:
        """
        Validate if a new position can be opened based on risk limits.
        Returns (can_open, reason) tuple.
        """
        if _RTH_GUARD_ENABLED and not _is_rth_now():
            return False, "Outside RTH (9:30 AM - 4:00 PM ET) \u2014 no new positions"

        stats = self.get_daily_stats()

        breached, reason = self.check_circuit_breaker(stats=stats)
        if breached:
            return False, reason

        breached, reason = self.check_max_drawdown(stats=stats)
        if breached:
            return False, reason

        open_positions = self.get_open_positions()
        if len(open_positions) >= self.max_open_positions:
            return False, f"Max open positions reached ({self.max_open_positions})"

        sector = self._get_ticker_sector(ticker)
        if sector:
            sector_exposure = self._calculate_sector_exposure(sector)
            position_exposure_pct = (risk_dollars / self.account_size) * 100

            if sector_exposure + position_exposure_pct > self.max_sector_exposure_pct:
                return False, (
                    f"Sector exposure limit ({sector}): "
                    f"{sector_exposure:.0f}% + {position_exposure_pct:.0f}% "
                    f"> {self.max_sector_exposure_pct:.0f}% max"
                )

        for pos in open_positions:
            if pos["ticker"] == ticker:
                return False, f"Position already open for {ticker}"

        return True, "OK"

    # ── FIX #6: testable risk-gate hook ────────────────────────────────────────────────────────────────────────
    def _check_risk_limits(self, ticker: str, risk_dollars: float) -> Tuple[bool, str]:
        """
        Thin wrapper around can_open_position() so tests can monkeypatch
        the risk gate without touching internals.
        """
        return self.can_open_position(ticker, risk_dollars)
    # ─────────────────────────────────────────────────────────────────────────────

    def _get_ticker_sector(self, ticker: str) -> Optional[str]:
        """Get sector for ticker from SECTOR_GROUPS mapping."""
        for sector, tickers in SECTOR_GROUPS.items():
            if ticker in tickers:
                return sector
        return None

    def _calculate_sector_exposure(self, sector: str) -> float:
        """Calculate current exposure percentage to a sector."""
        sector_tickers = SECTOR_GROUPS.get(sector, [])
        open_positions = self.get_open_positions()

        sector_risk = 0.0
        for pos in open_positions:
            if pos["ticker"] in sector_tickers:
                entry = pos["entry_price"]
                stop = pos["stop_price"]
                contracts = pos["remaining_contracts"]
                risk_per_contract = abs(entry - stop) * 100
                sector_risk += risk_per_contract * contracts

        return (sector_risk / self.account_size) * 100

    def validate_risk_reward(self, entry: float, stop: float, target: float) -> Tuple[bool, float]:
        """
        Validate risk/reward ratio meets minimum threshold.
        Returns (is_valid, risk_reward_ratio) tuple.
        """
        risk = abs(entry - stop)
        reward = abs(target - entry)

        if risk == 0:
            return False, 0.0

        risk_reward = reward / risk
        is_valid = risk_reward >= self.min_risk_reward_ratio

        return is_valid, risk_reward

    def has_loss_streak(self, max_consecutive_losses: int = 3) -> bool:
        """
        Return True if today's closed trades end with a losing streak
        of length >= max_consecutive_losses.
        """
        conn = None
        try:
            today  = datetime.now(_ET).strftime("%Y-%m-%d")
            conn   = get_conn()
            cursor = dict_cursor(conn)
            p      = ph()
            date_col = _date_eq_today("exit_time")
            cursor.execute(
                f"""
                SELECT pnl
                FROM positions
                WHERE status = {p}
                  AND {date_col} = {p}
                ORDER BY exit_time ASC
                """,
                ("CLOSED", today),
            )
            rows = cursor.fetchall()

            if not rows:
                return False

            streak = 0
            for row in rows:
                pnl = row["pnl"] or 0.0
                if pnl <= 0:
                    streak += 1
                else:
                    streak = 0

            return streak >= max_consecutive_losses

        except Exception as e:
            logger.info(f"[POSITION] Loss-streak check error: {e}")
            return False
        finally:
            if conn:
                return_conn(conn)

    def _initialize_database(self):
        """Create positions table if not exists with options columns."""
        conn = None
        try:
            conn = get_conn()
            cursor = conn.cursor()
            cursor.execute(f"""
                CREATE TABLE IF NOT EXISTS positions (
                    id {serial_pk()},
                    ticker TEXT NOT NULL,
                    direction TEXT NOT NULL,
                    entry_price REAL NOT NULL,
                    stop_price REAL NOT NULL,
                    t1_price REAL NOT NULL,
                    t2_price REAL NOT NULL,
                    contracts INTEGER DEFAULT 1,
                    remaining_contracts INTEGER DEFAULT 1,
                    grade TEXT,
                    confidence REAL,
                    t1_hit INTEGER DEFAULT 0,
                    entry_time TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    exit_time TIMESTAMP,
                    exit_price REAL,
                    exit_reason TEXT,
                    pnl REAL,
                    status TEXT DEFAULT 'OPEN',
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    strike REAL,
                    expiry TEXT,
                    contract_type TEXT,
                    delta REAL,
                    ivr REAL,
                    gex_context TEXT
                )
            """)
            conn.commit()
        finally:
            if conn:
                return_conn(conn)

    def _close_stale_positions(self):
        """
        Force-close any OPEN positions whose entry_time is from a prior trading day.
        Called on startup to ensure no overnight/weekend carryover for the 0DTE system.
        """
        conn = None
        try:
            today  = datetime.now(_ET).strftime("%Y-%m-%d")
            p      = ph()
            conn   = get_conn()
            cursor = dict_cursor(conn)

            date_col = _date_lt_today("entry_time")
            cursor.execute(f"""
                SELECT id, ticker, direction, entry_price
                FROM positions
                WHERE status = 'OPEN'
                AND {date_col} < {p}
            """, (today,))
            stale = cursor.fetchall()

            if not stale:
                logger.info("[POSITION] No stale positions from prior sessions")
                return

            logger.info(f"[POSITION] \u26a0\ufe0f  Found {len(stale)} stale position(s) \u2014 force closing before session")
            for pos in stale:
                pos = dict(pos)
                print(f"[POSITION] Force closing {pos['ticker']} {pos['direction'].upper()} "
                      f"(ID: {pos['id']}) entered @ ${pos['entry_price']:.2f} \u2014 STALE EOD")
                self.close_position(pos["id"], pos["entry_price"], "STALE_EOD")
        finally:
            if conn:
                return_conn(conn)

    def calculate_position_size(self, confidence: float, grade: str,
                                account_size: float = None,
                                risk_per_share: float = 1.0) -> Dict:
        """
        Calculate contract size based on confidence, grade, and risk.
        Applies performance multiplier and VIX volatility multiplier.

        Sizing stack (multiplicative):
          base_risk_pct  (from grade/confidence tier)
          \u00d7 performance_multiplier  (win/loss streak: 0.5\u20131.25)
          \u00d7 vix_multiplier          (volatility regime: 0.3\u20131.3)
          = final_risk_pct
        """
        account_size = account_size or self.account_size

        if confidence >= 0.85 and grade == "A+":
            risk_pct = config.POSITION_RISK["A+_high_confidence"]
        elif confidence >= 0.75 and grade in ["A+", "A"]:
            risk_pct = config.POSITION_RISK["A_high_confidence"]
        elif confidence >= 0.65:
            risk_pct = config.POSITION_RISK["standard"]
        else:
            risk_pct = config.POSITION_RISK["conservative"]

        adjusted_risk_pct = risk_pct * self.performance_multiplier

        vix_mult = _get_vix_mult()
        adjusted_risk_pct = adjusted_risk_pct * vix_mult

        if abs(vix_mult - 1.0) >= 0.10:
            direction = "reduced" if vix_mult < 1.0 else "increased"
            print(f"[VIX] Sizing {direction}: {risk_pct*100:.1f}% base \u2192 "
                  f"{adjusted_risk_pct*100:.1f}% adjusted ({vix_mult:.2f}\u00d7)")

        position_risk = account_size * adjusted_risk_pct
        contracts     = max(1, int(position_risk / (risk_per_share * 100)))
        if contracts > 1 and contracts % 2 != 0:
            contracts += 1

        max_contracts = getattr(config, "MAX_CONTRACTS", 10)
        contracts     = min(contracts, max_contracts)

        return {
            "contracts":       contracts,
            "risk_dollars":    round(position_risk, 2),
            "risk_percentage": round(adjusted_risk_pct * 100, 2),
            "allocation_type": f"{round(adjusted_risk_pct * 100, 1)}% risk",
            "performance_adj": self.performance_multiplier,
            "vix_mult":        round(vix_mult, 2),
        }

    def open_position(self, ticker: str, direction: str,
                      zone_low: float, zone_high: float,
                      or_low: float, or_high: float,
                      entry_price: float, stop_price: float,
                      t1: float, t2: float,
                      confidence: float, grade: str,
                      options_rec=None) -> int:
        """Open a new position and return position ID."""
        entry_price = float(entry_price)
        stop_price  = float(stop_price)
        zone_low    = float(zone_low)
        zone_high   = float(zone_high)
        or_low      = float(or_low)
        or_high     = float(or_high)
        t1          = float(t1)
        t2          = float(t2)
        confidence  = float(confidence)

        is_valid_rr, risk_reward = self.validate_risk_reward(entry_price, stop_price, t2)
        if not is_valid_rr:
            logger.info(f"[RISK] \u274c {ticker} rejected - R:R {risk_reward:.2f} < {self.min_risk_reward_ratio:.2f} minimum")
            return -1

        risk_per_share = round(abs(entry_price - stop_price), 4) or 1.0
        sizing    = self.calculate_position_size(confidence, grade,
                                                 risk_per_share=risk_per_share)
        contracts = sizing["contracts"]
        risk_dollars = sizing["risk_dollars"]

        can_open, reason = self._check_risk_limits(ticker, risk_dollars)
        if not can_open:
            logger.info(f"[RISK] \u274c {ticker} rejected - {reason}")
            return -1

        strike         = None
        expiry         = None
        contract_type  = None
        delta          = None
        ivr            = None
        gex_context    = None

        if options_rec:
            strike        = options_rec.get("strike")
            expiry        = options_rec.get("expiry")
            contract_type = options_rec.get("contract_type")
            delta         = options_rec.get("delta")
            ivr           = options_rec.get("ivr")
            gex_context   = options_rec.get("gex_label")

        p      = ph()
        values = (ticker, direction, entry_price, stop_price, t1, t2,
                  contracts, contracts, grade, confidence,
                  strike, expiry, contract_type, delta, ivr, gex_context)

        conn   = None
        try:
            conn   = get_conn()
            cursor = dict_cursor(conn)

            if db_connection.USE_POSTGRES:
                cursor.execute(f"""
                    INSERT INTO positions
                        (ticker, direction, entry_price, stop_price, t1_price, t2_price,
                         contracts, remaining_contracts, grade, confidence, status,
                         strike, expiry, contract_type, delta, ivr, gex_context)
                    VALUES ({p},{p},{p},{p},{p},{p},{p},{p},{p},{p},'OPEN',
                            {p},{p},{p},{p},{p},{p})
                    RETURNING id
                """, values)
                position_id = cursor.fetchone()["id"]
            else:
                cursor.execute(f"""
                    INSERT INTO positions
                        (ticker, direction, entry_price, stop_price, t1_price, t2_price,
                         contracts, remaining_contracts, grade, confidence, status,
                         strike, expiry, contract_type, delta, ivr, gex_context)
                    VALUES ({p},{p},{p},{p},{p},{p},{p},{p},{p},{p},'OPEN',
                            {p},{p},{p},{p},{p},{p})
                """, values)
                position_id = cursor.lastrowid

            conn.commit()
            self._invalidate_caches()

            self.positions.append({
                "id":                   position_id,
                "ticker":               ticker,
                "direction":            direction,
                "entry":                entry_price,
                "stop":                 stop_price,
                "t1":                   t1,
                "t2":                   t2,
                "contracts":            contracts,
                "remaining_contracts":  contracts,
                "grade":                grade,
                "confidence":           confidence,
                "t1_hit":               False,
                "pnl":                  0.0
            })

            if SIGNAL_TRACKING_ENABLED and signal_tracker:
                try:
                    signal_tracker.record_trade_executed(
                        ticker=ticker,
                        position_id=position_id
                    )
                except Exception as e:
                    logger.info(f"[POSITION] Signal tracking error: {e}")

            sector = self._get_ticker_sector(ticker) or "UNKNOWN"
            logger.info(f"[POSITION] Opened {ticker} {direction.upper()} - ID {position_id}")
            print(f"  Entry: {entry_price:.2f}  Stop: {stop_price:.2f}  "
                  f"T1: {t1:.2f}  T2: {t2:.2f}  R:R: {risk_reward:.2f}:1")
            print(f"  Contracts: {contracts}  Grade: {grade}  "
                  f"Confidence: {confidence:.1%}  Risk: ${risk_dollars:.0f} "
                  f"({sizing['risk_percentage']:.1f}%)  "
                  f"Perf: x{sizing['performance_adj']:.2f}  VIX: x{sizing['vix_mult']:.2f}")
            logger.info(f"  Sector: {sector}  Streak: {self._format_streak()}")

            if options_rec:
                opt_str = f"  Options: {contract_type} ${strike} exp {expiry}"
                if delta:
                    opt_str += f" | Delta: {delta:.2f}"
                if ivr:
                    opt_str += f" | IVR: {ivr:.0f}"
                if gex_context:
                    opt_str += f" | {gex_context}"
                logger.info(opt_str)

            return position_id
        finally:
            if conn:
                return_conn(conn)

    def check_exits(self, current_prices: Dict[str, float]):
        """Check all open positions for stop/target hits with scale-out logic."""
        open_positions = self.get_open_positions()
        if not open_positions:
            return

        for pos in open_positions:
            ticker = pos["ticker"]
            if ticker not in current_prices:
                continue

            current_price = current_prices[ticker]
            direction     = pos["direction"]
            stop          = pos["stop_price"]
            t1            = pos["t1_price"]
            t2            = pos["t2_price"]
            entry         = pos["entry_price"]
            t1_hit        = bool(pos["t1_hit"])
            pos_id        = pos["id"]

            if direction == "bull":
                if current_price <= stop:
                    self.close_position(pos_id, current_price, "STOP LOSS")
                elif current_price >= t1 and not t1_hit:
                    self._scale_out(pos_id, current_price, entry)
                    t1_hit = self._get_t1_hit_from_db(pos_id)
                    if current_price >= t2 and t1_hit:
                        self.close_position(pos_id, current_price, "TARGET 2")
                elif current_price >= t2 and t1_hit:
                    self.close_position(pos_id, current_price, "TARGET 2")
            else:  # bear
                if current_price >= stop:
                    self.close_position(pos_id, current_price, "STOP LOSS")
                elif current_price <= t1 and not t1_hit:
                    self._scale_out(pos_id, current_price, entry)
                    t1_hit = self._get_t1_hit_from_db(pos_id)
                    if current_price <= t2 and t1_hit:
                        self.close_position(pos_id, current_price, "TARGET 2")
                elif current_price <= t2 and t1_hit:
                    self.close_position(pos_id, current_price, "TARGET 2")

    def _get_t1_hit_from_db(self, position_id: int) -> bool:
        """FIX #9: Re-read t1_hit directly from DB (bypasses cache) after _scale_out."""
        conn = None
        try:
            p      = ph()
            conn   = get_conn()
            cursor = dict_cursor(conn)
            cursor.execute(
                f"SELECT t1_hit FROM positions WHERE id = {p}",
                (position_id,)
            )
            row = cursor.fetchone()
            return bool(row["t1_hit"]) if row else False
        except Exception as e:
            logger.info(f"[POSITION] _get_t1_hit_from_db error (non-fatal): {e}")
            return False
        finally:
            if conn:
                return_conn(conn)

    def _scale_out(self, position_id: int, exit_price: float, entry_price: float):
        """Close half the position at T1 and move stop to breakeven."""
        conn = None
        try:
            p      = ph()
            conn   = get_conn()
            cursor = dict_cursor(conn)
            cursor.execute(f"SELECT * FROM positions WHERE id = {p}", (position_id,))
            pos = cursor.fetchone()
            if not pos:
                return

            ticker             = pos["ticker"]
            direction          = pos["direction"]
            remaining          = pos["remaining_contracts"]
            contracts_to_close = max(1, remaining // 2)
            contracts_left     = remaining - contracts_to_close

            pnl_per_share = (
                (exit_price - entry_price) if direction == "bull"
                else (entry_price - exit_price)
            )
            partial_pnl = pnl_per_share * 100 * contracts_to_close

            cursor.execute(f"""
                UPDATE positions
                SET t1_hit              = 1,
                    remaining_contracts = {p},
                    stop_price          = {p},
                    pnl                 = COALESCE(pnl, 0) + {p}
                WHERE id = {p}
            """, (contracts_left, entry_price, partial_pnl, position_id))
            conn.commit()
            self._invalidate_caches()

            for cached in self.positions:
                if cached["id"] == position_id:
                    cached["t1_hit"]             = True
                    cached["remaining_contracts"] = contracts_left
                    cached["stop"]               = entry_price
                    cached["pnl"]                = cached.get("pnl", 0) + partial_pnl
                    break

            logger.info(f"[POSITION] \u26a1 SCALE OUT {ticker} @ {exit_price:.2f}")
            logger.info(f"  Closed {contracts_to_close} contracts | Remaining: {contracts_left}")
            logger.info(f"  Partial P&L: ${partial_pnl:.2f} | Stop \u2192 BE: {entry_price:.2f}")

            try:
                from app.notifications.discord_helpers import send_scaling_alert
                send_scaling_alert(ticker, exit_price, contracts_to_close,
                                   contracts_left, partial_pnl, entry_price)
            except Exception as e:
                logger.info(f"[POSITION] Discord scale alert failed: {e}")
        finally:
            if conn:
                return_conn(conn)

    def close_position(self, position_id: int, exit_price: float, exit_reason: str):
        """Close a position fully and record final P&L."""
        conn = None
        try:
            p      = ph()
            conn   = get_conn()
            cursor = dict_cursor(conn)
            cursor.execute(f"SELECT * FROM positions WHERE id = {p}", (position_id,))
            pos = cursor.fetchone()
            if not pos:
                return

            ticker    = pos["ticker"]
            direction = pos["direction"]
            entry     = pos["entry_price"]
            grade     = pos["grade"] or "A"
            remaining = pos["remaining_contracts"]
            prior_pnl = pos["pnl"] or 0.0

            pnl_per_share = (
                (exit_price - entry) if direction == "bull"
                else (entry - exit_price)
            )
            final_pnl = prior_pnl + (pnl_per_share * 100 * remaining)

            exit_time = datetime.now(_ET)

            cursor.execute(f"""
                UPDATE positions
                SET exit_price  = {p},
                    exit_reason = {p},
                    pnl         = {p},
                    exit_time   = {p},
                    status      = 'CLOSED'
                WHERE id = {p}
            """, (exit_price, exit_reason, final_pnl, exit_time, position_id))
            conn.commit()
            self._invalidate_caches()

            self.positions = [p for p in self.positions if p["id"] != position_id]

            # FIX #4: write completed_at back to ml_signals
            if exit_reason != "STALE_EOD":
                _ml_outcome = "WIN" if final_pnl > 0 else "LOSS"
                _write_completed_at(ticker, direction, _ml_outcome, exit_price, exit_time)

            if exit_reason != "STALE_EOD":
                closed_trades = self.get_todays_closed_trades()
                self._update_performance_streak(closed_trades)

            emoji = "\u2705" if final_pnl > 0 else "\u274c"
            logger.info(f"[POSITION] {emoji} CLOSED {ticker} @ {exit_price:.2f} | {exit_reason}")
            logger.info(f"  Total P&L: ${final_pnl:.2f}  Streak: {self._format_streak()}")

            if exit_reason != "STALE_EOD":
                try:
                    from app.ai.ai_learning import learning_engine
                    learning_engine.record_trade({
                        "ticker":    ticker,
                        "direction": direction,
                        "grade":     grade,
                        "entry":     entry,
                        "exit":      exit_price,
                        "pnl":       final_pnl,
                        "timeframe": "5m"
                    })
                except Exception as e:
                    logger.info(f"[POSITION] AI record error: {e}")

            try:
                from app.notifications.discord_helpers import send_exit_alert
                send_exit_alert(ticker, exit_price, exit_reason, final_pnl)
            except Exception as e:
                logger.info(f"[POSITION] Discord exit alert failed: {e}")

            # FIX #8: use real session P&L from DB (cache already busted above)
            session_stats = self.get_daily_stats()
            breached, reason = self.check_circuit_breaker(stats=session_stats)
            if breached:
                logger.info(f"\n[RISK] \U0001f6a8 {reason}")
                logger.info("[RISK] No new positions will be opened until next session\n")
        finally:
            if conn:
                return_conn(conn)

    def close_all_eod(self, current_prices: Dict[str, float]):
        """Close all open positions at end of day (0DTE force close at 3:55 PM)."""
        open_positions = self.get_open_positions()
        for pos in open_positions:
            ticker = pos["ticker"]
            price  = current_prices.get(ticker, pos["entry_price"])
            self.close_position(pos["id"], price, "EOD CLOSE")

        # M5 FIX: Reset streak counters after EOD force-close
        self.consecutive_wins = 0
        self.consecutive_losses = 0
        self.performance_multiplier = 1.0
        logger.info("[POSITION] \U0001f504 EOD streak reset \u2014 performance_multiplier \u2192 1.0x for next session")

    def get_open_positions(self) -> List[Dict]:
        """Return all currently open positions from the database (cached up to 5s)."""
        now = time.monotonic()
        if (
            self._open_positions_cache is not None
            and (now - self._open_positions_ts) < _POSITIONS_CACHE_TTL
        ):
            return self._open_positions_cache

        conn = None
        try:
            conn   = get_conn()
            cursor = dict_cursor(conn)
            cursor.execute("SELECT * FROM positions WHERE status = 'OPEN'")
            rows   = cursor.fetchall()
            result = [dict(row) for row in rows]
            self._open_positions_cache = result
            self._open_positions_ts    = now
            return result
        finally:
            if conn:
                return_conn(conn)

    def get_daily_stats(self) -> Dict:
        """Return win/loss/P&L stats for today's closed trades (cached up to 10s)."""
        now = time.monotonic()
        if (
            self._daily_stats_cache is not None
            and (now - self._daily_stats_ts) < _STATS_CACHE_TTL
        ):
            return self._daily_stats_cache

        conn = None
        try:
            p      = ph()
            conn   = get_conn()
            cursor = dict_cursor(conn)
            today  = datetime.now(_ET).strftime("%Y-%m-%d")
            date_col = _date_eq_today("exit_time")
            cursor.execute(f"""
                SELECT COUNT(*)                                  AS trades,
                       SUM(CASE WHEN pnl > 0 THEN 1 ELSE 0 END) AS wins,
                       SUM(CASE WHEN pnl <= 0 THEN 1 ELSE 0 END) AS losses,
                       SUM(pnl)                                  AS total_pnl
                FROM positions
                WHERE status = 'CLOSED'
                  AND {date_col} = {p}
            """, (today,))
            row = cursor.fetchone()

            trades    = row["trades"]    or 0
            wins      = row["wins"]      or 0
            losses    = row["losses"]    or 0
            total_pnl = row["total_pnl"] or 0.0
            win_rate  = (wins / trades * 100) if trades > 0 else 0.0

            result = {
                "trades":    trades,
                "wins":      wins,
                "losses":    losses,
                "total_pnl": round(total_pnl, 2),
                "win_rate":  round(win_rate, 1)
            }
            self._daily_stats_cache = result
            self._daily_stats_ts    = now
            return result
        finally:
            if conn:
                return_conn(conn)

    def get_win_rate(self, lookback_days: int = 30) -> Dict:
        """Return per-grade win rate stats over the last N days."""
        conn = None
        try:
            p      = ph()
            conn   = get_conn()
            cursor = dict_cursor(conn)
            since  = (datetime.now(_ET) - timedelta(days=lookback_days)).strftime("%Y-%m-%d")
            # FIX #13: use _date_col() (range extractor) not _date_eq_today() (equality semantics)
            date_col = _date_col("exit_time")
            cursor.execute(f"""
                SELECT grade,
                       COUNT(*)                                  AS total,
                       SUM(CASE WHEN pnl > 0 THEN 1 ELSE 0 END) AS wins,
                       AVG(pnl)                                  AS avg_pnl
                FROM positions
                WHERE status = 'CLOSED' AND {date_col} >= {p}
                GROUP BY grade
            """, (since,))
            rows = cursor.fetchall()

            stats = {}
            for row in rows:
                grade = row["grade"] or "Unknown"
                total = row["total"]
                wins  = row["wins"] or 0
                stats[grade] = {
                    "total":    total,
                    "wins":     wins,
                    "win_rate": round((wins / total * 100) if total > 0 else 0, 1),
                    "avg_pnl":  round(row["avg_pnl"] or 0, 2)
                }
            return stats
        finally:
            if conn:
                return_conn(conn)

    def generate_report(self) -> str:
        """Generate end-of-day performance report string."""
        stats         = self.get_daily_stats()
        win_rate_data = self.get_win_rate(lookback_days=30)

        trades    = stats.get("trades",    0)
        wins      = stats.get("wins",      0)
        losses    = stats.get("losses",    0)
        total_pnl = stats.get("total_pnl", 0.0)
        win_rate  = stats.get("win_rate",  0.0)

        daily_return_pct = (total_pnl / self.session_starting_balance) * 100
        max_dd_pct = ((self.account_size - self.intraday_high_water_mark) /
                      self.intraday_high_water_mark) * 100

        lines = [
            "=" * 50,
            "WAR MACHINE \u2014 END OF DAY REPORT",
            "=" * 50,
            f"Date:         {datetime.now(_ET).strftime('%Y-%m-%d')}",
            f"Total Trades: {trades}",
            f"Winners:      {wins}",
            f"Losers:       {losses}",
            f"Win Rate:     {win_rate:.1f}%",
            f"Net P&L:      ${total_pnl:+.2f} ({daily_return_pct:+.2f}%)",
            f"Max Drawdown: {max_dd_pct:.2f}%",
            f"Final Streak: {self._format_streak()}",
            "",
            "\u2500 30-Day Grade Breakdown \u2500"
        ]

        if win_rate_data:
            for grade in ["A+", "A", "A-"]:
                if grade in win_rate_data:
                    g = win_rate_data[grade]
                    lines.append(
                        f"  {grade}: {g['total']} trades | "
                        f"{g['win_rate']:.1f}% WR | "
                        f"Avg P&L: ${g['avg_pnl']:+.2f}"
                    )
        else:
            lines.append("  No grade data yet.")

        lines.append("=" * 50)
        return "\n".join(lines)

    def get_todays_closed_trades(self) -> List[Dict]:
        """Return all trades closed today for EOD ML training."""
        conn = None
        try:
            p      = ph()
            conn   = get_conn()
            cursor = dict_cursor(conn)
            today  = datetime.now(_ET).strftime("%Y-%m-%d")
            date_col = _date_eq_today("exit_time")
            cursor.execute(f"""
                SELECT ticker, direction, grade, entry_price, exit_price, pnl
                FROM positions
                WHERE status = 'CLOSED'
                  AND {date_col} = {p}
                  AND exit_reason != 'STALE_EOD'
            """, (today,))
            rows = cursor.fetchall()
            return [dict(row) for row in rows]
        finally:
            if conn:
                return_conn(conn)

    def get_risk_summary(self, open_positions: List[Dict] = None) -> str:
        """Get formatted risk management summary."""
        stats = self.get_daily_stats()
        total_pnl = stats.get("total_pnl", 0.0)

        current_balance = self.session_starting_balance + total_pnl
        daily_return_pct = (total_pnl / self.session_starting_balance) * 100
        max_dd_pct = ((current_balance - self.intraday_high_water_mark) /
                      self.intraday_high_water_mark) * 100

        if open_positions is None:
            open_positions = self.get_open_positions()

        total_exposure = sum(
            abs(pos["entry_price"] - pos["stop_price"]) * 100 * pos["remaining_contracts"]
            for pos in open_positions
        )
        exposure_pct = (total_exposure / current_balance) * 100 if current_balance else 0.0

        circuit_breached, _ = self.check_circuit_breaker(stats=stats)

        # FIX #7: pre-compute label — backslashes in f-string expressions are a
        # SyntaxError on Python 3.10 (Railway runtime).
        cb_label = "\U0001f6a8 TRIGGERED" if circuit_breached else "\u2705 OK"

        summary = "\n" + "="*60 + "\n"
        summary += "RISK MANAGEMENT SUMMARY\n"
        summary += "="*60 + "\n"
        summary += f"Account Balance:  ${current_balance:,.0f}\n"
        summary += f"Session Start:    ${self.session_starting_balance:,.0f}\n"
        summary += f"High Water Mark:  ${self.intraday_high_water_mark:,.0f}\n"
        summary += f"Daily P&L:        ${total_pnl:+,.0f} ({daily_return_pct:+.2f}%)\n"
        summary += f"Max Drawdown:     {max_dd_pct:.2f}% (limit: -{self.max_daily_loss_pct}%)\n"
        summary += f"Open Positions:   {len(open_positions)} / {self.max_open_positions} max\n"
        summary += f"Total Exposure:   ${total_exposure:,.0f} ({exposure_pct:.1f}%)\n"
        summary += f"Performance:      {self._format_streak()}\n"
        summary += f"Circuit Breaker:  {cb_label}\n"
        summary += "="*60 + "\n"

        return summary


# ── Global singleton ───────────────────────────────────────────────────────────────────────────────────────────────────────
position_manager = PositionManager()
