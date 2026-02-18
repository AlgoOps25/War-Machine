"""
Scanner Optimizer - Adaptive Scan Intervals
Dynamically adjusts scan frequency based on time of day
"""
from datetime import datetime, time

def get_adaptive_scan_interval() -> int:
    """
    CFW6 OPTIMIZATION: Scan more frequently during high-activity periods
    
    Opening Range (9:30-9:45): 30 seconds (catch early setups)
    High Activity (9:45-11:00, 2:00-3:30): 60 seconds
    Midday Chop (11:00-2:00): 180 seconds (slower market)
    Power Hour (3:30-4:00): 45 seconds
    """
    now = datetime.now().time()
    
    # Opening Range Period (most important)
    if time(9, 30) <= now < time(9, 45):
        interval = 30
        print(f"[SCANNER] 🔥 Opening Range Period → Scanning every {interval}s")
    
    # Morning Activity (9:45-11:00)
    elif time(9, 45) <= now < time(11, 0):
        interval = 60
        print(f"[SCANNER] ⚡ Morning Activity → Scanning every {interval}s")
    
    # Midday Chop (11:00-2:00)
    elif time(11, 0) <= now < time(14, 0):
        interval = 180
        print(f"[SCANNER] 😴 Midday Period → Scanning every {interval}s")
    
    # Afternoon Setup (2:00-3:30)
    elif time(14, 0) <= now < time(15, 30):
        interval = 60
        print(f"[SCANNER] ⚡ Afternoon Activity → Scanning every {interval}s")
    
    # Power Hour (3:30-4:00)
    elif time(15, 30) <= now < time(16, 0):
        interval = 45
        print(f"[SCANNER] 🔥 Power Hour → Scanning every {interval}s")
    
    # Outside market hours
    else:
        interval = 300
        print(f"[SCANNER] 💤 Outside Market Hours → Scanning every {interval}s")
    
    return interval

def should_scan_now() -> bool:
    """
    Determine if we should scan based on current time
    
    During 9:30-9:40 (Opening Range period), return False
    We only start scanning AFTER 9:40 per CFW6 rules
    """
    now = datetime.now().time()
    
    # CFW6 RULE: Don't scan during 9:30-9:40 (waiting for OR to form)
    if time(9, 30) <= now < time(9, 40):
        print(f"[SCANNER] ⏸️ Opening Range forming (9:30-9:40) - Waiting...")
        return False
    
    # Market hours check
    if time(9, 40) <= now <= time(16, 0):
        return True
    
    return False

def calculate_optimal_watchlist_size() -> int:
    """
    Adjust watchlist size based on time of day
    
    Early market: Smaller, focused watchlist
    Midday: Larger watchlist (more scanning needed)
    """
    now = datetime.now().time()
    
    # Opening Range + Early Morning: Focus on 30 best tickers
    if time(9, 30) <= now < time(10, 30):
        return 30
    
    # Mid-morning to early afternoon: Full watchlist
    elif time(10, 30) <= now < time(15, 0):
        return 50
    
    # Late day: Reduce to 35 tickers
    elif time(15, 0) <= now <= time(16, 0):
        return 35
    
    return 40  # Default
