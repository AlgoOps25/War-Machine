# main.py
# Master orchestrator: starts scanner loop, sniper monitor, trade logger monitor
import threading
import scanner
import sniper
from trade_logger import start_monitor_thread
from discord_bot import send

if __name__ == "__main__":
    send("⚔️ WAR MACHINE GOD MODE PRO — starting up")
    # start sniper fast monitor
    sniper.start_fast_monitor()
    # start trade logger monitor
    start_monitor_thread()
    # start scanner loop (blocking)
    scanner.start_scanner_loop()
