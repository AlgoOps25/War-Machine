"""
Position Manager - Consolidated Position Tracking, Sizing, and Win Rate Analysis
Replaces: position_tracker.py, position_sizing.py, win_rate_tracker.py
"""
import sqlite3
import config
from datetime import datetime, timedelta
from typing import Dict, List, Optional


class PositionManager:
    def __init__(self, db_path: str = None):
        self.db_path = db_path or config.TRADES_DB_PATH
        self.positions = []  # Active positions cache
        self._initialize_database()

    def _initialize_database(self):
        """Create positions table if not exists."""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS positions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
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

    def calculate_position_size(
        self,
        confidence: float,
        grade: str,
        account_size: float = None,
        risk_per_share: float = 1.0
    ) -> Dict:
        """
        CFW6 OPTIMIZATION: Dynamic position sizing based on signal quality.
        Grade-based risk allocation from config.POSITION_RISK.
        """
        account_size = account_size or config.ACCOUNT_SIZE

        # Determine risk % from config
        if confidence >= 0.85 and grade == "A+":
            risk_pct = config.POSITION_RISK["A+_high_confidence"]
        elif confidence >= 0.75 and grade in ["A+", "A"]:
            risk_pct = config.POSITION_RISK["A_high_confidence"]
        elif confidence >= 0.65:
            risk_pct = config.POSITION_RISK["standard"]
        else:
            risk_pct = config.POSITION_RISK["conservative"]

        position_risk = account_size * risk_pct
        contracts = max(1, int(position_risk / (risk_per_share * 100)))

        # Ensure even number of contracts for clean 50/50 scale-out
        if contracts > 1 and contracts % 2 != 0:
            contracts += 1

        # Apply hard limit
        contracts = min(contracts, config.MAX_CONTRACTS)

        return {
            "contracts": contracts,
            "risk_dollars": round(position_risk, 2),
            "risk_percentage": round(risk_pct * 100, 2),
            "allocation_type": f"{round(risk_pct * 100, 1)}% risk"
        }

    def open_position(
        self,
        ticker: str,
        direction: str,
        entry: float,
        stop: float,
        t1: float,
        t2: float,
        grade: str,
        confidence: float,
        contracts: int = 1
    ) -> int:
        """Open a new position and return position ID."""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        cursor.execute("""
            INSERT INTO positions
                (ticker, direction, entry_price, stop_price, t1_price, t2_price,
                 contracts, remaining_contracts, grade, confidence, status)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'OPEN')
        """, (ticker, direction, entry, stop, t1, t2, contracts, contracts, grade, confidence))
        position_id = cursor.lastrowid
        conn.commit()
        conn.close()

        self.positions.append({
            "id": position_id,
            "ticker": ticker,
            "direction": direction,
            "entry": entry,
            "stop": stop,
            "t1": t1,
            "t2": t2,
            "contracts": contracts,
            "remaining_contracts": contracts,
            "grade": grade,
            "confidence": confidence,
            "t1_hit": False,
            "pnl": 0.0
        })

        print(f"[POSITION] Opened {ticker} {direction.upper()} - ID {position_id}")
        print(f"  Entry: {entry:.2f}  Stop: {stop:.2f}  T1: {t1:.2f}  T2: {t2:.2f}")
        print(f"  Contracts: {contracts}  Grade: {grade}  Confidence: {confidence:.1%}")
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
            direction = pos["direction"]
            stop = pos["stop_price"]
            t1 = pos["t1_price"]
            t2 = pos["t2_price"]
            entry = pos["entry_price"]
            t1_hit = bool(pos["t1_hit"])
            remaining = pos["remaining_contracts"]
            pos_id = pos["id"]

            if direction == "bull":
                # Stop loss
                if current_price <= stop:
                    self.close_position(pos_id, current_price, "STOP LOSS")

                # T1 scale-out (only once)
                elif current_price >= t1 and not t1_hit:
                    self._scale_out(pos_id, current_price, entry)

                # T2 full exit
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
        """
        Scale out 50% of contracts at T1, move stop to break-even.
        Keeps position open for T2.
        """
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM positions WHERE id = ?", (position_id,))
        pos = cursor.fetchone()
        if not pos:
            conn.close()
            return

        ticker = pos["ticker"]
        direction = pos["direction"]
        total_contracts = pos["contracts"]
        remaining = pos["remaining_contracts"]
        contracts_to_close = max(1, remaining // 2)
        contracts_left = remaining - contracts_to_close

        # Calculate partial P&L
        if direction == "bull":
            pnl_per_share = exit_price - entry_price
        else:
            pnl_per_share = entry_price - exit_price
        partial_pnl = pnl_per_share * 100 * contracts_to_close

        # Move stop to break-even
        cursor.execute("""
            UPDATE positions
            SET t1_hit = 1,
                remaining_contracts = ?,
                stop_price = ?,
                pnl = COALESCE(pnl, 0) + ?
            WHERE id = ?
        """, (contracts_left, entry_price, partial_pnl, position_id))
        conn.commit()
        conn.close()

        # Update local cache
        for p in self.positions:
            if p["id"] == position_id:
                p["t1_hit"] = True
                p["remaining_contracts"] = contracts_left
                p["stop"] = entry_price
                p["pnl"] = p.get("pnl", 0) + partial_pnl
                break

        print(f"[POSITION] ⚡ SCALE OUT {ticker} @ {exit_price:.2f}")
        print(f"  Closed {contracts_to_close} contracts | Remaining: {contracts_left}")
        print(f"  Partial P&L: ${partial_pnl:.2f} | Stop moved to BE: {entry_price:.2f}")

        # Send Discord alert
        try:
            from discord_helpers import send_scaling_alert
            send_scaling_alert(ticker, exit_price, contracts_to_close, contracts_left, partial_pnl, entry_price)
        except Exception as e:
            print(f"[POSITION] Discord scale alert failed: {e}")

    def close_position(self, position_id: int, exit_price: float, exit_reason: str):
        """Close a position and calculate final P&L."""
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM positions WHERE id = ?", (position_id,))
        pos = cursor.fetchone()
        if not pos:
            conn.close()
            return

        ticker = pos["ticker"]
        direction = pos["direction"]
        entry = pos["entry_price"]
        remaining = pos["remaining_contracts"]
        prior_pnl = pos["pnl"] or 0.0

        # P&L on remaining contracts
        if direction == "bull":
            pnl_per_share = exit_price - entry
        else:
            pnl_per_share = entry - exit_price
        final_pnl = prior_pnl + (pnl_per_share * 100 * remaining)

        cursor.execute("""
            UPDATE positions
            SET exit_price = ?,
                exit_reason = ?,
                pnl = ?,
                exit_time = CURRENT_TIMESTAMP,
                status = 'CLOSED'
            WHERE id = ?
        """, (exit_price, exit_reason, final_pnl, position_id))
        conn.commit()
        conn.close()

        # Remove from active cache
        self.positions = [p for p in self.positions if p["id"] != position_id]

        emoji = "✅" if final_pnl > 0 else "❌"
        print(f"[POSITION] {emoji} CLOSED {ticker} @ {exit_price:.2f} | {exit_reason}")
        print(f"  Total P&L: ${final_pnl:.2f}")

        # Send Discord alert
        try:
            from discord_helpers import send_exit_alert
            send_exit_alert(ticker, exit_price, exit_reason, final_pnl)
        except Exception as e:
            print(f"[POSITION] Discord exit alert failed: {e}")

    def close_all_eod(self, current_prices: Dict[str, float]):
        """Close all open positions at end of day."""
        open_positions = self.get_open_positions()
        for pos in open_positions:
            ticker = pos["ticker"]
            price = current_prices.get(ticker, pos["entry_price"])
            self.close_position(pos["id"], price, "EOD CLOSE")

    def get_open_positions(self) -> List[Dict]:
        """Return all currently open positions from DB."""
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM positions WHERE status = 'OPEN'")
        rows = cursor.fetchall()
        conn.close()
        return [dict(row) for row in rows]

    def get_daily_stats(self) -> Dict:
        """Return today's trading stats."""
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        today = datetime.now().strftime("%Y-%m-%d")
        cursor.execute("""
            SELECT COUNT(*) as trades,
                   SUM(CASE WHEN pnl > 0 THEN 1 ELSE 0 END) as wins,
                   SUM(CASE WHEN pnl <= 0 THEN 1 ELSE 0 END) as losses,
                   SUM(pnl) as total_pnl
            FROM positions
            WHERE status = 'CLOSED'
              AND DATE(exit_time) = ?
        """, (today,))
        row = cursor.fetchone()
        conn.close()

        trades = row["trades"] or 0
        wins = row["wins"] or 0
        losses = row["losses"] or 0
        total_pnl = row["total_pnl"] or 0.0
        win_rate = (wins / trades * 100) if trades > 0 else 0.0

        return {
            "trades": trades,
            "wins": wins,
            "losses": losses,
            "total_pnl": round(total_pnl, 2),
            "win_rate": round(win_rate, 1)
        }

    def get_win_rate(self, lookback_days: int = 30) -> Dict:
        """Return win rate over a lookback period."""
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        since = (datetime.now() - timedelta(days=lookback_days)).strftime("%Y-%m-%d")
        cursor.execute("""
            SELECT grade,
                   COUNT(*) as total,
                   SUM(CASE WHEN pnl > 0 THEN 1 ELSE 0 END) as wins,
                   AVG(pnl) as avg_pnl
            FROM positions
            WHERE status = 'CLOSED'
              AND DATE(exit_time) >= ?
            GROUP BY grade
        """, (since,))
        rows = cursor.fetchall()
        conn.close()

        stats = {}
        for row in rows:
            grade = row["grade"] or "Unknown"
            total = row["total"]
            wins = row["wins"] or 0
            stats[grade] = {
                "total": total,
                "wins": wins,
                "win_rate": round((wins / total * 100) if total > 0 else 0, 1),
                "avg_pnl": round(row["avg_pnl"] or 0, 2)
            }
        return stats


# Global singleton
position_manager = PositionManager()


# Legacy compatibility shims
def update_ticker(ticker: str):
    """Legacy function — calls DataManager."""
    from data_manager import data_manager
    data_manager.update_ticker(ticker)


def cleanup_old_bars(days_to_keep: int = 7):
    """Legacy function — calls DataManager."""
    from data_manager import data_manager
    data_manager.cleanup_old_bars(days_to_keep)
