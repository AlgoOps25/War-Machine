"""
Session Heatmap
Generates a weekly Discord heatmap showing win rate by ticker × hour of day.
Posted automatically every Friday at EOD via run_eod_digest() in main.py.

Purpose:
  Reveals which time windows consistently produce winning signals per ticker.
  Midday chop (11:00-12:00) typically shows red/yellow. Power hour (15:00)
  typically shows green. Use this data to manually tighten your watchlist
  focus at low-WR hours, or to tune MIN_CONFIDENCE thresholds by time.

Hour buckets (ET):
  9:30   → 9:00-9:59   (opening range + early momentum)
  10:00  → 10:00-10:59 (post-OR continuation)
  11:00  → 11:00-11:59 (mid-morning fade)
  12:00  → 12:00-12:59 (lunch chop)
  13:00  → 13:00-13:59 (early afternoon)
  14:00  → 14:00-14:59 (afternoon trend setup)
  15:00  → 15:00-15:59 (power hour)

Color coding:
  🟢  WR >= 65%   favorable — lean in
  🟡  WR 45-64%   neutral   — normal risk
  🔴  WR <  45%   avoid     — consider raising gate
  ⬜  0 trades   no data
"""
from datetime  import datetime, timedelta
from zoneinfo  import ZoneInfo
from typing    import Dict, List, Optional, Tuple

LOOKBACK_DAYS  = 30    # rolling window for heatmap data
MAX_TICKERS    = 6     # max ticker columns in the grid
MIN_TRADES_CELL = 2    # minimum trades to show WR (else ⬜)

# Hour bucket definitions: (label, start_hour_inclusive, end_hour_inclusive)
HOUR_BUCKETS = [
    ("9:30",  9,  9),
    ("10:00", 10, 10),
    ("11:00", 11, 11),
    ("12:00", 12, 12),
    ("13:00", 13, 13),
    ("14:00", 14, 14),
    ("15:00", 15, 15),
]


def _now_et() -> datetime:
    return datetime.now(ZoneInfo("America/New_York"))


def _wr_emoji(wr: Optional[float], trades: int) -> str:
    """Map a win rate to an emoji + compact label."""
    if trades < MIN_TRADES_CELL or wr is None:
        return "⬜  "
    if wr >= 65:
        return f"🟢{wr:2.0f}"
    if wr >= 45:
        return f"🟡{wr:2.0f}"
    return     f"🔴{wr:2.0f}"


# ─────────────────────────────────────────────────────────────
def build_heatmap_data(lookback_days: int = LOOKBACK_DAYS) -> dict:
    """
    Query closed positions and build a heatmap data structure.

    Returns:
    {
      "tickers"      : [str, ...]          top N tickers by trade count
      "cells"        : {(ticker, hour): {"trades": int, "wins": int,
                                          "wr": float, "avg_pnl": float}}
      "hour_totals"  : {hour: {"trades", "wins", "wr"}}  all-ticker roll-up
      "ticker_totals": {ticker: {"trades", "wins", "wr", "avg_pnl"}}
      "cutoff_date"  : str
      "has_data"     : bool
    }
    """
    cutoff = (_now_et() - timedelta(days=lookback_days)).date()
    result = {
        "tickers":       [],
        "cells":         {},
        "hour_totals":   {},
        "ticker_totals": {},
        "cutoff_date":   str(cutoff),
        "has_data":      False
    }

    try:
        from db_connection import get_conn, ph
        conn   = get_conn()
        cursor = conn.cursor()
        p      = ph()

        # Try PostgreSQL EXTRACT syntax first
        try:
            cursor.execute(f"""
                SELECT
                    ticker,
                    CAST(EXTRACT(HOUR FROM open_time) AS INTEGER) AS hour,
                    direction,
                    entry_price,
                    close_price
                FROM positions
                WHERE close_price IS NOT NULL
                  AND entry_price IS NOT NULL
                  AND DATE(open_time) >= {p}
                ORDER BY ticker, hour
            """, (cutoff,))
        except Exception:
            # SQLite fallback
            cursor.execute(f"""
                SELECT
                    ticker,
                    CAST(strftime('%H', open_time) AS INTEGER) AS hour,
                    direction,
                    entry_price,
                    close_price
                FROM positions
                WHERE close_price IS NOT NULL
                  AND entry_price IS NOT NULL
                  AND DATE(open_time) >= {p}
                ORDER BY ticker, hour
            """, (cutoff,))

        rows = cursor.fetchall()
        conn.close()
    except Exception as e:
        print(f"[HEATMAP] DB error: {e}")
        return result

    if not rows:
        return result

    # ── Aggregate into cells ────────────────────────────────────────────
    cells: Dict[Tuple, Dict] = {}
    ticker_counts: Dict[str, int] = {}

    for ticker, hour, direction, entry, close in rows:
        if entry is None or close is None or entry == 0:
            continue

        # Map raw hour to bucket hour (9 → 9, 10 → 10, etc.)
        bucket_hour = int(hour)
        if bucket_hour < 9 or bucket_hour > 15:
            continue

        # Determine win
        direc = (direction or "bull").lower()
        pnl   = (close - entry) if direc == "bull" else (entry - close)
        win   = 1 if pnl > 0 else 0

        key = (ticker, bucket_hour)
        if key not in cells:
            cells[key] = {"trades": 0, "wins": 0, "total_pnl": 0.0}
        cells[key]["trades"]    += 1
        cells[key]["wins"]      += win
        cells[key]["total_pnl"] += pnl
        ticker_counts[ticker]    = ticker_counts.get(ticker, 0) + 1

    # Top N tickers by total trade count
    top_tickers = sorted(ticker_counts, key=ticker_counts.get, reverse=True)[:MAX_TICKERS]

    # Finalise cells (compute WR + avg P&L)
    final_cells: Dict[Tuple, Dict] = {}
    for key, c in cells.items():
        n = c["trades"]
        final_cells[key] = {
            "trades":  n,
            "wins":    c["wins"],
            "wr":      round((c["wins"] / n) * 100, 1) if n > 0 else None,
            "avg_pnl": round(c["total_pnl"] / n, 2)    if n > 0 else 0.0
        }

    # Hour totals (all tickers combined)
    hour_totals: Dict[int, Dict] = {}
    for (ticker, hour), c in final_cells.items():
        if hour not in hour_totals:
            hour_totals[hour] = {"trades": 0, "wins": 0}
        hour_totals[hour]["trades"] += c["trades"]
        hour_totals[hour]["wins"]   += c["wins"]
    for hour, h in hour_totals.items():
        n = h["trades"]
        h["wr"] = round((h["wins"] / n) * 100, 1) if n > 0 else None

    # Ticker totals
    ticker_totals: Dict[str, Dict] = {}
    for (ticker, _), c in final_cells.items():
        if ticker not in ticker_totals:
            ticker_totals[ticker] = {"trades": 0, "wins": 0, "total_pnl": 0.0}
        ticker_totals[ticker]["trades"]    += c["trades"]
        ticker_totals[ticker]["wins"]      += c["wins"]
        ticker_totals[ticker]["total_pnl"] += c["avg_pnl"] * c["trades"]
    for t, d in ticker_totals.items():
        n = d["trades"]
        d["wr"]      = round((d["wins"] / n) * 100, 1) if n > 0 else None
        d["avg_pnl"] = round(d["total_pnl"] / n, 2)    if n > 0 else 0.0

    result["tickers"]       = top_tickers
    result["cells"]         = final_cells
    result["hour_totals"]   = hour_totals
    result["ticker_totals"] = ticker_totals
    result["has_data"]      = True
    return result


# ─────────────────────────────────────────────────────────────
def format_heatmap_discord(data: dict) -> str:
    """
    Format heatmap data into a Discord message string.
    Uses monospace code block for alignment + emoji color coding per cell.
    """
    if not data["has_data"] or not data["tickers"]:
        return "🌡️ **Session Heatmap** — No trade data yet (need closed positions)."

    now  = _now_et()
    week = now.strftime("Week of %b %d, %Y")
    tickers = data["tickers"]

    # Column widths: each ticker gets 5 chars (emoji + 2 digits + 1 space)
    COL = 5
    LABEL_W = 6   # hour label width

    lines = [
        f"🌡️ **SESSION HEATMAP** — {week}",
        f"📊 Win Rate by Hour × Ticker | Last {data.get('lookback_days', 30)} days",
        f"🟢 ≥65%  🟡 45-64%  🔴 <45%  ⬜ no data",
        "```"
    ]

    # Header row
    header = f"{'Hour':<{LABEL_W}} | ALL  | "
    header += " | ".join(f"{t[:4]:<{COL-1}}" for t in tickers)
    lines.append(header)
    lines.append("─" * len(header))

    # Data rows
    for label, start_h, end_h in HOUR_BUCKETS:
        # ALL column
        ht    = data["hour_totals"].get(start_h, {})
        all_e = _wr_emoji(ht.get("wr"), ht.get("trades", 0))

        row = f"{label:<{LABEL_W}} | {all_e} | "
        cells = []
        for t in tickers:
            c   = data["cells"].get((t, start_h), {"trades": 0, "wr": None})
            cells.append(f"{_wr_emoji(c.get('wr'), c.get('trades', 0)):<{COL}}")
        row += " | ".join(cells)
        lines.append(row)

    # Footer row: ticker WR totals
    lines.append("─" * len(header))
    footer = f"{'ALL':<{LABEL_W}} |      | "
    tfooter = []
    for t in tickers:
        td = data["ticker_totals"].get(t, {"wr": None, "trades": 0})
        tfooter.append(f"{_wr_emoji(td.get('wr'), td.get('trades', 0)):<{COL}}")
    footer += " | ".join(tfooter)
    lines.append(footer)
    lines.append("```")

    # ── Best hour summary
    ht = data["hour_totals"]
    valid_hours = [(h, v) for h, v in ht.items() if v.get("trades", 0) >= MIN_TRADES_CELL]
    if valid_hours:
        best_h  = max(valid_hours, key=lambda x: x[1].get("wr") or 0)
        worst_h = min(valid_hours, key=lambda x: x[1].get("wr") or 100)

        # Map hour int back to label
        hour_labels = {h: lbl for lbl, h, _ in HOUR_BUCKETS}
        best_label  = hour_labels.get(best_h[0],  str(best_h[0])  + ":00")
        worst_label = hour_labels.get(worst_h[0], str(worst_h[0]) + ":00")

        lines += [
            f"🏆 **Best hour:**  `{best_label}` — "
            f"{best_h[1]['wr']:.0f}% WR ({best_h[1]['trades']} trades)",
            f"⚠️ **Worst hour:** `{worst_label}` — "
            f"{worst_h[1]['wr']:.0f}% WR ({worst_h[1]['trades']} trades)",
        ]

    lines.append(f"🤖 War Machine | {now.strftime('%I:%M %p ET')}")
    return "\n".join(lines)


# ─────────────────────────────────────────────────────────────
def send_heatmap(force: bool = False) -> None:
    """
    Build and send the session heatmap to Discord.

    Parameters:
      force : if True, sends regardless of day of week (useful for testing)

    Normal behavior: only sends on Fridays.
    Silent no-op if no data or Discord unavailable.
    """
    now = _now_et()
    is_friday = (now.weekday() == 4)   # 0=Mon ... 4=Fri

    if not force and not is_friday:
        print(f"[HEATMAP] Skipping — not Friday (weekday={now.weekday()})")
        return

    print("[HEATMAP] Building session heatmap...")
    try:
        data = build_heatmap_data(LOOKBACK_DAYS)
        data["lookback_days"] = LOOKBACK_DAYS
        message = format_heatmap_discord(data)

        print("\n" + message + "\n")

        from discord_helpers import send_simple_message
        send_simple_message(message)
        print("[HEATMAP] ✅ Heatmap sent to Discord")

    except Exception as e:
        print(f"[HEATMAP] Error: {e}")
        import traceback
        traceback.print_exc()
