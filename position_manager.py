"""
Position Manager - Consolidated Position Tracking, Sizing, and Win Rate Analysis
Replaces: position_tracker.py, position_sizing.py, win_rate_tracker.py
"""
import config
from datetime import datetime, timedelta
from typing import Dict, List, Optional
import db_connection
from db_connection import get_conn, ph, dict_cursor, serial_pk


class PositionManager:

    def __init__(self, db_path: str = None):
        self.db_path = db_path or config.TRADES_DB_PATH
        self.positions = []  # Active positions cache
        self._initialize_database()
        self._close_stale_positions()  # Force-close any positions from prior trading days

    def has_loss_streak(self, max_consecutive_losses: int = 3) -> bool:
        """
        Return True if today's closed trades end with a losing streak
        of length >= max_consecutive_losses.
        Uses db_connection (Postgres-safe — does NOT call sqlite3 directly).
        """
        try:
            today  = datetime.now().strftime("%Y-%m-%d")
            conn   = get_conn(self.db_path)
            cursor = dict_cursor(conn)
            p      = ph()
            cursor.execute(
                f"""
                SELECT pnl
                FROM positions
                WHERE status = {p}
                  AND DATE(exit_time) = {p}
                ORDER BY exit_time ASC
                """,
                ("CLOSED", today),
            )
            rows = cursor.fetchall()
            conn.close()

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
            print(f"[POSITION] Loss-streak check error: {e}")
            return False

    def _initialize_database(self):
        """Create positions table if not exists."""
        conn = get_conn(self.db_path)
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
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        conn.commit()
        conn.close()


    def _close_stale_positions(self):
        """
        Force-close any OPEN positions whose entry_time is from a prior trading day.
        Called on startup — ensures no overnight/weekend carryover for the 0DTE system.
        Closed at entry_price (no current price available) with reason STALE_EOD.
        """
        today  = datetime.now().strftime("%Y-%m-%d")
        p      = ph()
        conn   = get_conn(self.db_path)
        cursor = dict_cursor(conn)

        cursor.execute(f"""
            SELECT id, ticker, direction, entry_price
            FROM positions
            WHERE status = 'OPEN'
            AND DATE(entry_time) < {p}
        """, (today,))
        stale = cursor.fetchall()
        conn.close()

        if not stale:
            print("[POSITION] No stale positions from prior sessions")
            return

        print(f"[POSITION] \u26a0\ufe0f  Found {len(stale)} stale position(s) \u2014 force closing before session")
        for pos in stale:
            pos = dict(pos)
            print(f"[POSITION] Force closing {pos['ticker']} {pos['direction'].upper()} "
                  f"(ID: {pos['id']}) entered @ ${pos['entry_price']:.2f} \u2014 STALE EOD")
            self.close_position(pos["id"], pos["entry_price"], "STALE_EOD")


    def calculate_position_size(self, confidence: float, grade: str,
                                account_size: float = None,
                                risk_per_share: float = 1.0) -> Dict:
        """Calculate contract size based on confidence, grade, and risk."""
        account_size = account_size or getattr(config, "ACCOUNT_SIZE", 25_000)

        if confidence >= 0.85 and grade == "A+":
            risk_pct = config.POSITION_RISK["A+_high_confidence"]
        elif confidence >= 0.75 and grade in ["A+", "A"]:
            risk_pct = config.POSITION_RISK["A_high_confidence"]
        elif confidence >= 0.65:
            risk_pct = config.POSITION_RISK["standard"]
        else:
            risk_pct = config.POSITION_RISK["conservative"]

        position_risk = account_size * risk_pct
        contracts     = max(1, int(position_risk / (risk_per_share * 100)))
        if contracts > 1 and contracts % 2 != 0:
            contracts += 1

        max_contracts = getattr(config, "MAX_CONTRACTS", 10)
        contracts     = min(contracts, max_contracts)

        return {
            "contracts":       contracts,
            "risk_dollars":    round(position_risk, 2),
            "risk_percentage": round(risk_pct * 100, 2),
            "allocation_type": f"{round(risk_pct * 100, 1)}% risk"
        }


    def open_position(self, ticker: str, direction: str,
                      zone_low: float, zone_high: float,
                      or_low: float, or_high: float,
                      entry_price: float, stop_price: float,
                      t1: float, t2: float,
                      confidence: float, grade: str,
                      options_rec=None) -> int:
        """Open a new position and return position ID."""
        # Cast numpy types to native Python BEFORE SQL
        entry_price = float(entry_price)
        stop_price  = float(stop_price)
        zone_low    = float(zone_low)
        zone_high   = float(zone_high)
        or_low      = float(or_low)
        or_high     = float(or_high)
        t1          = float(t1)
        t2          = float(t2)
        confidence  = float(confidence)

        # Size the position based on actual stop distance
        risk_per_share = round(abs(entry_price - stop_price), 4) or 1.0
        sizing    = self.calculate_position_size(confidence, grade,
                                                 risk_per_share=risk_per_share)
        contracts = sizing["contracts"]

        p      = ph()
        values = (ticker, direction, entry_price, stop_price, t1, t2,
                  contracts, contracts, grade, confidence)

        conn   = get_conn(self.db_path)
        cursor = dict_cursor(conn)

        if db_connection.USE_POSTGRES:
            cursor.execute(f"""
                INSERT INTO positions
                    (ticker, direction, entry_price, stop_price, t1_price, t2_price,
                     contracts, remaining_contracts, grade, confidence, status)
                VALUES ({p},{p},{p},{p},{p},{p},{p},{p},{p},{p},'OPEN')
                RETURNING id
            """, values)
            position_id = cursor.fetchone()["id"]
        else:
            cursor.execute(f"""
                INSERT INTO positions
                    (ticker, direction, entry_price, stop_price, t1_price, t2_price,
                     contracts, remaining_contracts, grade, confidence, status)
                VALUES ({p},{p},{p},{p},{p},{p},{p},{p},{p},{p},'OPEN')
            """, values)
            position_id = cursor.lastrowid

        conn.commit()
        conn.close()

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

        print(f"[POSITION] Opened {ticker} {direction.upper()} - ID {position_id}")
        print(f"  Entry: {entry_price:.2f}  Stop: {stop_price:.2f}  "
              f"T1: {t1:.2f}  T2: {t2:.2f}")
        print(f"  Contracts: {contracts}  Grade: {grade}  "
              f"Confidence: {confidence:.1%}  Risk/share: ${risk_per_share:.2f}")
        return position_id


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
                elif current_price >= t2 and t1_hit:
                    self.close_position(pos_id, current_price, "TARGET 2")
            else:  # bear
                if current_price >= stop:
                    self.close_position(pos_id, current_price, "STOP LOSS")
                elif current_price <= t1 and not t1_hit:
                    self._scale_out(pos_id, current_price, entry)
                elif current_price <= t2 and t1_hit:
                    self.close_position(pos_id, current_price, "TARGET 2")


    def _scale_out(self, position_id: int, exit_price: float, entry_price: float):
        """Close half the position at T1 and move stop to breakeven."""
        p      = ph()
        conn   = get_conn(self.db_path)
        cursor = dict_cursor(conn)
        cursor.execute(f"SELECT * FROM positions WHERE id = {p}", (position_id,))
        pos = cursor.fetchone()
        if not pos:
            conn.close()
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
        conn.close()

        for cached in self.positions:
            if cached["id"] == position_id:
                cached["t1_hit"]             = True
                cached["remaining_contracts"] = contracts_left
                cached["stop"]               = entry_price
                cached["pnl"]                = cached.get("pnl", 0) + partial_pnl
                break

        print(f"[POSITION] \u26a1 SCALE OUT {ticker} @ {exit_price:.2f}")
        print(f"  Closed {contracts_to_close} contracts | Remaining: {contracts_left}")
        print(f"  Partial P&L: ${partial_pnl:.2f} | Stop \u2192 BE: {entry_price:.2f}")

        try:
            from discord_helpers import send_scaling_alert
            send_scaling_alert(ticker, exit_price, contracts_to_close,
                               contracts_left, partial_pnl, entry_price)
        except Exception as e:
            print(f"[POSITION] Discord scale alert failed: {e}")


    def close_position(self, position_id: int, exit_price: float, exit_reason: str):
        """Close a position fully and record final P&L."""
        p      = ph()
        conn   = get_conn(self.db_path)
        cursor = dict_cursor(conn)
        cursor.execute(f"SELECT * FROM positions WHERE id = {p}", (position_id,))
        pos = cursor.fetchone()
        if not pos:
            conn.close()
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

        cursor.execute(f"""
            UPDATE positions
            SET exit_price  = {p},
                exit_reason = {p},
                pnl         = {p},
                exit_time   = CURRENT_TIMESTAMP,
                status      = 'CLOSED'
            WHERE id = {p}
        """, (exit_price, exit_reason, final_pnl, position_id))
        conn.commit()
        conn.close()

        self.positions = [p for p in self.positions if p["id"] != position_id]

        emoji = "\u2705" if final_pnl > 0 else "\u274c"
        print(f"[POSITION] {emoji} CLOSED {ticker} @ {exit_price:.2f} | {exit_reason}")
        print(f"  Total P&L: ${final_pnl:.2f}")

        # FIX Bug #9: record every closed trade to the AI learning engine.
        # Previously learning_engine.record_trade() was never called anywhere,
        # so optimize_confirmation_weights() and optimize_fvg_threshold() ran
        # on an empty trades list every EOD and produced no useful output.
        # STALE_EOD closures are excluded — they carry no useful signal data.
        if exit_reason != "STALE_EOD":
            try:
                from ai_learning import learning_engine
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
                print(f"[POSITION] AI record error: {e}")

        try:
            from discord_helpers import send_exit_alert
            send_exit_alert(ticker, exit_price, exit_reason, final_pnl)
        except Exception as e:
            print(f"[POSITION] Discord exit alert failed: {e}")


    def close_all_eod(self, current_prices: Dict[str, float]):
        """Close all open positions at end of day (0DTE force close at 3:55 PM)."""
        open_positions = self.get_open_positions()
        for pos in open_positions:
            ticker = pos["ticker"]
            price  = current_prices.get(ticker, pos["entry_price"])
            self.close_position(pos["id"], price, "EOD CLOSE")


    def get_open_positions(self) -> List[Dict]:
        """Return all currently open positions from the database."""
        conn   = get_conn(self.db_path)
        cursor = dict_cursor(conn)
        cursor.execute("SELECT * FROM positions WHERE status = 'OPEN'")
        rows   = cursor.fetchall()
        conn.close()
        return [dict(row) for row in rows]


    def get_daily_stats(self) -> Dict:
        """Return win/loss/P&L stats for today's closed trades."""
        p      = ph()
        conn   = get_conn(self.db_path)
        cursor = dict_cursor(conn)
        today  = datetime.now().strftime("%Y-%m-%d")
        cursor.execute(f"""
            SELECT COUNT(*)                                  AS trades,
                   SUM(CASE WHEN pnl > 0 THEN 1 ELSE 0 END) AS wins,
                   SUM(CASE WHEN pnl <= 0 THEN 1 ELSE 0 END) AS losses,
                   SUM(pnl)                                  AS total_pnl
            FROM positions
            WHERE status = 'CLOSED' AND DATE(exit_time) = {p}
        """, (today,))
        row = cursor.fetchone()
        conn.close()

        trades    = row["trades"]    or 0
        wins      = row["wins"]      or 0
        losses    = row["losses"]    or 0
        total_pnl = row["total_pnl"] or 0.0
        win_rate  = (wins / trades * 100) if trades > 0 else 0.0

        return {
            "trades":    trades,
            "wins":      wins,
            "losses":    losses,
            "total_pnl": round(total_pnl, 2),
            "win_rate":  round(win_rate, 1)
        }


    def get_win_rate(self, lookback_days: int = 30) -> Dict:
        """Return per-grade win rate stats over the last N days."""
        p      = ph()
        conn   = get_conn(self.db_path)
        cursor = dict_cursor(conn)
        since  = (datetime.now() - timedelta(days=lookback_days)).strftime("%Y-%m-%d")
        cursor.execute(f"""
            SELECT grade,
                   COUNT(*)                                  AS total,
                   SUM(CASE WHEN pnl > 0 THEN 1 ELSE 0 END) AS wins,
                   AVG(pnl)                                  AS avg_pnl
            FROM positions
            WHERE status = 'CLOSED' AND DATE(exit_time) >= {p}
            GROUP BY grade
        """, (since,))
        rows = cursor.fetchall()
        conn.close()

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


    def generate_report(self) -> str:
        """Generate end-of-day performance report string."""
        stats         = self.get_daily_stats()
        win_rate_data = self.get_win_rate(lookback_days=30)

        trades    = stats.get("trades",    0)
        wins      = stats.get("wins",      0)
        losses    = stats.get("losses",    0)
        total_pnl = stats.get("total_pnl", 0.0)
        win_rate  = stats.get("win_rate",  0.0)

        lines = [
            "=" * 50,
            "WAR MACHINE \u2014 END OF DAY REPORT",
            "=" * 50,
            f"Date:         {datetime.now().strftime('%A, %B %d, %Y')}",
            f"Total Trades: {trades}",
            f"Winners:      {wins}",
            f"Losers:       {losses}",
            f"Win Rate:     {win_rate:.1f}%",
            f"Net P&L:      ${total_pnl:+.2f}",
            "",
            "\u2014 30-Day Grade Breakdown \u2014"
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


# ── Global singleton ──────────────────────────────────────────────────────────────────
position_manager = PositionManager()


# ── Legacy compatibility shims ──────────────────────────────────────────────────────────────────
def update_ticker(ticker: str):
    """Legacy function — calls DataManager."""
    from data_manager import data_manager
    data_manager.update_ticker(ticker)


def cleanup_old_bars(days_to_keep: int = 7):
    """Legacy function — calls DataManager."""
    from data_manager import data_manager
    data_manager.cleanup_old_bars(days_to_keep)
