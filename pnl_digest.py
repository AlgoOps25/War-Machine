"""
Daily P&L Digest
Builds and sends a structured end-of-day performance summary to Discord.

Fires:
  1. At 4:00 PM ET via the scheduled trigger in main.py
  2. On manual shutdown (KeyboardInterrupt) in main.py

Data sources:
  - positions table     : closed trades (P&L, grade, confidence, hold time)
  - proposed_trades     : total signals fired today
  - position_manager    : daily stats summary (win rate, trade count)

Message sections:
  Header              : date + session label
  Financials          : realized P&L, win rate, signals fired, avg hold time
  Best / Worst        : top and bottom individual trade
  Grade Breakdown     : per-grade WR + avg P&L (A+ / A / A-)
  Confidence Accuracy : WR by confidence tier (>=90% / 80-89% / <80%)
  Footer              : system status
"""
from datetime import datetime, date
from zoneinfo import ZoneInfo
from typing import Optional


def _now_et() -> datetime:
    return datetime.now(ZoneInfo("America/New_York"))


def _today_et() -> date:
    return _now_et().date()


# ─────────────────────────────────────────────────────────────
def _query_closed_positions(cursor, p, today: date) -> list:
    """
    Fetch all closed positions opened today.
    Returns list of row dicts. Returns [] on any DB error.
    """
    try:
        cursor.execute(f"""
            SELECT
                ticker, direction,
                entry_price, close_price,
                open_time,  close_time,
                confidence, grade
            FROM positions
            WHERE DATE(open_time) = {p}
              AND close_price IS NOT NULL
            ORDER BY open_time ASC
        """, (today,))
        cols = [d[0] for d in cursor.description]
        return [dict(zip(cols, row)) for row in cursor.fetchall()]
    except Exception:
        return []


def _query_signals_fired(cursor, p, today: date) -> int:
    """Count signals entered into proposed_trades today."""
    try:
        cursor.execute(
            f"SELECT COUNT(*) FROM proposed_trades WHERE DATE(timestamp) = {p}",
            (today,)
        )
        row = cursor.fetchone()
        return int(row[0]) if row else 0
    except Exception:
        return 0


# ─────────────────────────────────────────────────────────────
def build_pnl_summary() -> dict:
    """
    Query the DB and build a complete performance summary for today.

    Returns a dict with keys:
      date, day_label,
      trades, wins, losses, win_rate,
      total_pnl, avg_pnl_per_trade,
      avg_hold_minutes,
      signals_fired,
      best_trade, worst_trade,
      grade_breakdown   : {grade: {trades, wins, total_pnl}}
      conf_breakdown    : {tier_label: {trades, wins}}
      raw_trades        : list of trade dicts
    """
    today = _today_et()
    summary = {
        "date":            today.strftime("%A, %B %d, %Y"),
        "day_label":       today.strftime("%a %b %d"),
        "trades":          0,
        "wins":            0,
        "losses":          0,
        "win_rate":        0.0,
        "total_pnl":       0.0,
        "avg_pnl":         0.0,
        "avg_hold_min":    0.0,
        "signals_fired":   0,
        "best_trade":      None,
        "worst_trade":     None,
        "grade_breakdown": {},
        "conf_breakdown":  {},
        "raw_trades":      []
    }

    try:
        from db_connection import get_conn, ph
        conn   = get_conn()
        cursor = conn.cursor()
        p      = ph()

        trades          = _query_closed_positions(cursor, p, today)
        signals_fired   = _query_signals_fired(cursor, p, today)
        summary["signals_fired"] = signals_fired
        conn.close()
    except Exception as e:
        print(f"[DIGEST] DB error: {e}")
        return summary

    if not trades:
        return summary

    summary["raw_trades"] = trades

    # ── Core P&L math ────────────────────────────────────────────────
    pnl_list   = []
    hold_times = []
    wins = losses = 0

    for t in trades:
        entry = t.get("entry_price") or 0
        close = t.get("close_price") or 0
        direc = (t.get("direction") or "bull").lower()

        if entry > 0 and close > 0:
            raw_pnl = (close - entry) if direc == "bull" else (entry - close)
            pnl_list.append(raw_pnl)
            t["pnl"] = raw_pnl
            if raw_pnl > 0:
                wins += 1
            else:
                losses += 1
        else:
            t["pnl"] = 0.0
            pnl_list.append(0.0)

        # Hold time in minutes
        ot = t.get("open_time")
        ct = t.get("close_time")
        if ot and ct:
            try:
                if isinstance(ot, str):
                    ot = datetime.fromisoformat(ot)
                if isinstance(ct, str):
                    ct = datetime.fromisoformat(ct)
                hold_times.append((ct - ot).total_seconds() / 60)
            except Exception:
                pass

    total = len(trades)
    total_pnl = sum(pnl_list)

    summary["trades"]       = total
    summary["wins"]         = wins
    summary["losses"]       = losses
    summary["win_rate"]     = round((wins / total) * 100, 1) if total > 0 else 0.0
    summary["total_pnl"]    = round(total_pnl, 2)
    summary["avg_pnl"]      = round(total_pnl / total, 2) if total > 0 else 0.0
    summary["avg_hold_min"] = round(sum(hold_times) / len(hold_times), 1) if hold_times else 0.0

    # Best / worst trade
    if pnl_list:
        best_idx  = pnl_list.index(max(pnl_list))
        worst_idx = pnl_list.index(min(pnl_list))
        summary["best_trade"]  = trades[best_idx]
        summary["worst_trade"] = trades[worst_idx]

    # ── Grade breakdown ───────────────────────────────────────────────
    grade_data: dict = {}
    for t in trades:
        g = (t.get("grade") or "?").upper()
        if g not in grade_data:
            grade_data[g] = {"trades": 0, "wins": 0, "total_pnl": 0.0}
        grade_data[g]["trades"]    += 1
        grade_data[g]["total_pnl"] += t.get("pnl", 0)
        if t.get("pnl", 0) > 0:
            grade_data[g]["wins"] += 1
    # Compute win rate per grade
    for g in grade_data:
        n = grade_data[g]["trades"]
        grade_data[g]["win_rate"] = round(
            (grade_data[g]["wins"] / n) * 100, 1
        ) if n > 0 else 0.0
        grade_data[g]["avg_pnl"] = round(
            grade_data[g]["total_pnl"] / n, 2
        ) if n > 0 else 0.0
    summary["grade_breakdown"] = grade_data

    # ── Confidence tier breakdown ─────────────────────────────────────────
    conf_tiers = {
        ">=90%":  {"trades": 0, "wins": 0, "total_pnl": 0.0},
        "80-89%": {"trades": 0, "wins": 0, "total_pnl": 0.0},
        "<80%":   {"trades": 0, "wins": 0, "total_pnl": 0.0}
    }
    for t in trades:
        conf = (t.get("confidence") or 0) * 100
        tier = ">=90%" if conf >= 90 else ("80-89%" if conf >= 80 else "<80%")
        conf_tiers[tier]["trades"]    += 1
        conf_tiers[tier]["total_pnl"] += t.get("pnl", 0)
        if t.get("pnl", 0) > 0:
            conf_tiers[tier]["wins"] += 1
    for tier in conf_tiers:
        n = conf_tiers[tier]["trades"]
        conf_tiers[tier]["win_rate"] = round(
            (conf_tiers[tier]["wins"] / n) * 100, 1
        ) if n > 0 else 0.0
    summary["conf_breakdown"] = conf_tiers

    return summary


# ─────────────────────────────────────────────────────────────
def format_discord_digest(s: dict) -> str:
    """
    Format the P&L summary dict into a Discord-ready message string.
    """
    sep = "═" * 40

    # ── Header
    lines = [
        sep,
        f"📊 **WAR MACHINE — Daily P&L Digest**",
        f"📅 {s['date']}",
        sep,
        ""
    ]

    # ── Financials
    pnl      = s["total_pnl"]
    pnl_sign = "+" if pnl >= 0 else ""
    pnl_icon = "🟢" if pnl >= 0 else "🔴"
    wr_icon  = "🎯" if s["win_rate"] >= 60 else ("⚠️" if s["win_rate"] >= 40 else "🟥")

    lines += [
        f"{pnl_icon} **Realized P&L:**   `{pnl_sign}{pnl:.2f} pts`",
        f"{wr_icon} **Win Rate:**        `{s['win_rate']:.1f}%`  "
        f"({s['wins']}W / {s['losses']}L / {s['trades']} trades)",
        f"📶 **Signals Fired:**   `{s['signals_fired']}`",
        f"⏱  **Avg Hold Time:**   `{s['avg_hold_min']:.0f} min`",
        f"💹 **Avg P&L / Trade:** `{pnl_sign}{s['avg_pnl']:.2f} pts`",
        ""
    ]

    # ── Best / Worst trade
    def _trade_line(t, icon):
        if not t:
            return f"{icon} N/A"
        pnl    = t.get("pnl", 0)
        sign   = "+" if pnl >= 0 else ""
        ticker = t.get("ticker", "?")
        direc  = (t.get("direction") or "?").upper()
        grade  = t.get("grade") or "?"
        conf   = (t.get("confidence") or 0) * 100
        return (f"{icon} **{ticker}** {direc} `{sign}{pnl:.2f}` "
                f"| Grade: {grade} | Conf: {conf:.0f}%")

    lines += [
        _trade_line(s["best_trade"],  "🏆 **Best:**  "),
        _trade_line(s["worst_trade"], "💥 **Worst:** "),
        ""
    ]

    # ── Grade Breakdown
    gb = s.get("grade_breakdown", {})
    if gb:
        lines.append("🎚️ **Grade Breakdown:**")
        for grade in ["A+", "A", "A-"]:
            if grade in gb:
                d  = gb[grade]
                sp = "+" if d["avg_pnl"] >= 0 else ""
                lines.append(
                    f"  `{grade:<3}` {d['trades']:>2} trades | "
                    f"{d['win_rate']:>5.1f}% WR | avg `{sp}{d['avg_pnl']:.2f}`"
                )
        lines.append("")

    # ── Confidence Accuracy
    cb = s.get("conf_breakdown", {})
    if any(v["trades"] > 0 for v in cb.values()):
        lines.append("🧠 **Confidence Accuracy:**")
        for tier in [">=90%", "80-89%", "<80%"]:
            d = cb.get(tier, {})
            if d.get("trades", 0) > 0:
                lines.append(
                    f"  `{tier:<7}` {d['trades']:>2} trades | {d['win_rate']:>5.1f}% WR"
                )
        lines.append("")

    # ── Footer
    lines += [
        sep,
        f"🤖 War Machine | {_now_et().strftime('%I:%M %p ET')}",
        sep
    ]

    return "\n".join(lines)


# ─────────────────────────────────────────────────────────────
def send_pnl_digest() -> None:
    """
    Build and send the daily P&L digest to Discord.
    Safe to call at any time — silent no-op if no trades or Discord unavailable.
    """
    print("[DIGEST] Building daily P&L digest...")
    try:
        summary = build_pnl_summary()
        message = format_discord_digest(summary)

        # Print to console regardless of Discord status
        print("\n" + message + "\n")

        from discord_helpers import send_simple_message
        send_simple_message(message)
        print("[DIGEST] ✅ Digest sent to Discord")

    except Exception as e:
        print(f"[DIGEST] Error: {e}")
