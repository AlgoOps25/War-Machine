# Cooldown Tracker - Prevents duplicate signals on same ticker
# Tracks ticker cooldown periods after signal generation
# Purpose: Avoid rapid-fire signals on same ticker (quality > quantity)
# FIXED (Issue #19): Cooldown state now persisted to DB — survives Railway restarts

from datetime import datetime, timedelta
from typing import Dict, Optional
from zoneinfo import ZoneInfo

class CooldownTracker:
    """
    Tracks signal cooldown periods to prevent duplicate signals.
    Default cooldown: 15 minutes after signal armed.
    Cooldown state is persisted to DB so Railway restarts don't reset it.
    """

    def __init__(self, cooldown_minutes: int = 15):
        self.cooldown_minutes = cooldown_minutes
        self._cooldowns: Dict[str, datetime] = {}  # ticker -> cooldown_expires_at
        self._db_loaded = False
        self._stats = {
            'total_cooldowns_set': 0,
            'signals_blocked': 0,
            'cooldowns_expired': 0
        }

    def _now_et(self) -> datetime:
        return datetime.now(ZoneInfo("America/New_York"))

    # ─────────────────────────────────────────────────────────────────────
    # DB HELPERS
    # ─────────────────────────────────────────────────────────────────────

    def _ensure_cooldown_db(self) -> None:
        """Create signal_cooldown table if it doesn't exist."""
        try:
            from app.data.db_connection import get_conn, return_conn
            conn = None
            try:
                conn = get_conn()
                cursor = conn.cursor()
                cursor.execute("""
                    CREATE TABLE IF NOT EXISTS signal_cooldown (
                        ticker          TEXT PRIMARY KEY,
                        expires_at      TIMESTAMP   NOT NULL,
                        signal_type     TEXT        NOT NULL DEFAULT 'CFW6',
                        updated_at      TIMESTAMP   DEFAULT CURRENT_TIMESTAMP
                    )
                """)
                conn.commit()
            finally:
                if conn:
                    return_conn(conn)
        except Exception as e:
            print(f"[COOLDOWN-DB] Init error: {e}")

    def _persist_cooldown(self, ticker: str, expires_at: datetime) -> None:
        """Upsert cooldown expiry to DB."""
        try:
            from app.data.db_connection import get_conn, return_conn
            from app.data.sql_safe import safe_execute, get_placeholder
            conn = None
            try:
                conn = get_conn()
                cursor = conn.cursor()
                p = get_placeholder(conn)
                query = f"""
                    INSERT INTO signal_cooldown (ticker, expires_at, updated_at)
                    VALUES ({p}, {p}, CURRENT_TIMESTAMP)
                    ON CONFLICT (ticker) DO UPDATE SET
                        expires_at = EXCLUDED.expires_at,
                        updated_at = CURRENT_TIMESTAMP
                """
                safe_execute(cursor, query, (ticker, expires_at))
                conn.commit()
            finally:
                if conn:
                    return_conn(conn)
        except Exception as e:
            print(f"[COOLDOWN-DB] Persist error for {ticker}: {e}")

    def _remove_cooldown_from_db(self, ticker: str) -> None:
        """Delete cooldown row for ticker."""
        try:
            from app.data.db_connection import get_conn, return_conn
            from app.data.sql_safe import safe_execute, get_placeholder
            conn = None
            try:
                conn = get_conn()
                cursor = conn.cursor()
                p = get_placeholder(conn)
                safe_execute(cursor, f"DELETE FROM signal_cooldown WHERE ticker = {p}", (ticker,))
                conn.commit()
            finally:
                if conn:
                    return_conn(conn)
        except Exception as e:
            print(f"[COOLDOWN-DB] Remove error for {ticker}: {e}")

    def _load_from_db(self) -> None:
        """Load active (non-expired) cooldowns from DB into memory cache."""
        if self._db_loaded:
            return
        self._db_loaded = True
        self._ensure_cooldown_db()
        self._cleanup_stale_cooldowns()
        try:
            from app.data.db_connection import get_conn, return_conn, dict_cursor
            from app.data.sql_safe import safe_query, get_placeholder
            conn = None
            try:
                conn = get_conn()
                cursor = dict_cursor(conn)
                p = get_placeholder(conn)
                now = self._now_et()
                rows = safe_query(cursor,
                    f"SELECT ticker, expires_at FROM signal_cooldown WHERE expires_at > {p}",
                    (now,)
                )
                loaded = 0
                for row in rows:
                    ticker = row['ticker']
                    expires_at = row['expires_at']
                    if hasattr(expires_at, 'tzinfo') and expires_at.tzinfo is None:
                        from zoneinfo import ZoneInfo as _ZI
                        expires_at = expires_at.replace(tzinfo=_ZI("America/New_York"))
                    self._cooldowns[ticker] = expires_at
                    loaded += 1
                if loaded:
                    print(f"[COOLDOWN-DB] 📄 Reloaded {loaded} active cooldown(s) from DB after restart")
            finally:
                if conn:
                    return_conn(conn)
        except Exception as e:
            print(f"[COOLDOWN-DB] Load error: {e}")

    def _cleanup_stale_cooldowns(self) -> None:
        """Remove expired cooldown rows from DB."""
        try:
            from app.data.db_connection import get_conn, return_conn
            from app.data.sql_safe import safe_execute, get_placeholder
            conn = None
            try:
                conn = get_conn()
                cursor = conn.cursor()
                p = get_placeholder(conn)
                now = self._now_et()
                safe_execute(cursor,
                    f"DELETE FROM signal_cooldown WHERE expires_at <= {p}",
                    (now,)
                )
                deleted = cursor.rowcount
                conn.commit()
                if deleted > 0:
                    print(f"[COOLDOWN-DB] 🧹 Auto-cleaned {deleted} expired cooldown(s)")
            finally:
                if conn:
                    return_conn(conn)
        except Exception as e:
            print(f"[COOLDOWN-DB] Cleanup error: {e}")

    # ─────────────────────────────────────────────────────────────────────
    # PUBLIC API
    # ─────────────────────────────────────────────────────────────────────

    def set_cooldown(self, ticker: str) -> None:
        """Set cooldown period for ticker after signal armed (memory + DB)."""
        expires_at = self._now_et() + timedelta(minutes=self.cooldown_minutes)
        self._cooldowns[ticker] = expires_at
        self._stats['total_cooldowns_set'] += 1
        self._persist_cooldown(ticker, expires_at)

    def is_in_cooldown(self, ticker: str) -> bool:
        """
        Check if ticker is in cooldown.
        Fast path: in-memory dict.
        Slow path (post-restart miss): DB lookup to catch persisted state.
        """
        # Ensure DB state is loaded once per process lifetime
        if not self._db_loaded:
            self._load_from_db()

        if ticker not in self._cooldowns:
            return False

        expires_at = self._cooldowns[ticker]
        now = self._now_et()

        if now >= expires_at:
            del self._cooldowns[ticker]
            self._stats['cooldowns_expired'] += 1
            self._remove_cooldown_from_db(ticker)
            return False

        self._stats['signals_blocked'] += 1
        return True

    def get_cooldown_remaining(self, ticker: str) -> float:
        """Get remaining cooldown time in seconds."""
        if ticker not in self._cooldowns:
            return 0.0
        expires_at = self._cooldowns[ticker]
        now = self._now_et()
        remaining = (expires_at - now).total_seconds()
        return max(0.0, remaining)

    def clear_cooldown(self, ticker: str) -> None:
        """Manually clear cooldown for ticker (e.g., position closed)."""
        if ticker in self._cooldowns:
            del self._cooldowns[ticker]
        self._remove_cooldown_from_db(ticker)

    def clear_all_cooldowns(self) -> None:
        """Clear all cooldowns (EOD reset) — memory + DB."""
        self._cooldowns.clear()
        try:
            from app.data.db_connection import get_conn, return_conn
            from app.data.sql_safe import safe_execute
            conn = None
            try:
                conn = get_conn()
                cursor = conn.cursor()
                safe_execute(cursor, "DELETE FROM signal_cooldown")
                conn.commit()
            finally:
                if conn:
                    return_conn(conn)
        except Exception as e:
            print(f"[COOLDOWN-DB] Clear all error: {e}")

    def get_active_cooldowns(self) -> Dict[str, float]:
        """Get all active cooldowns with remaining time in seconds."""
        now = self._now_et()
        active = {}
        expired = []

        for ticker, expires_at in self._cooldowns.items():
            remaining = (expires_at - now).total_seconds()
            if remaining > 0:
                active[ticker] = remaining
            else:
                expired.append(ticker)

        for ticker in expired:
            del self._cooldowns[ticker]
            self._stats['cooldowns_expired'] += 1
            self._remove_cooldown_from_db(ticker)

        return active

    def print_eod_report(self) -> None:
        """Print end-of-day cooldown statistics."""
        stats = self._stats
        active = self.get_active_cooldowns()

        print("\n" + "="*80)
        print("COOLDOWN TRACKER - END OF DAY REPORT")
        print("="*80)
        print(f"Cooldown Period: {self.cooldown_minutes} minutes")
        print(f"Total Cooldowns Set: {stats['total_cooldowns_set']}")
        print(f"Signals Blocked: {stats['signals_blocked']}")
        print(f"Cooldowns Expired: {stats['cooldowns_expired']}")
        print(f"DB Persistence: ✅ enabled")

        if active:
            print(f"\nActive Cooldowns at EOD: {len(active)}")
            for ticker, remaining in sorted(active.items()):
                minutes = remaining / 60
                print(f"  • {ticker}: {minutes:.1f} min remaining")
        else:
            print("\nNo active cooldowns at EOD")

        total_signals_attempted = stats['total_cooldowns_set'] + stats['signals_blocked']
        if total_signals_attempted > 0:
            block_rate = (stats['signals_blocked'] / total_signals_attempted) * 100
            print(f"\nBlock Rate: {block_rate:.1f}% ({stats['signals_blocked']}/{total_signals_attempted})")

        print("="*80 + "\n")


# Global singleton instance
cooldown_tracker = CooldownTracker(cooldown_minutes=15)
