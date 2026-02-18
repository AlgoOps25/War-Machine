"""
War Machine - Main Entry Point
CFW6 Strategy + Options Signal Engine
"""

if __name__ == "__main__":
    import sys
    import os
    
    print("="*60)
    print("WAR MACHINE - STARTING")
    print("="*60)
    print(f"Python: {sys.version}")
    print(f"Working Directory: {os.getcwd()}")
    
    # Check environment variables
    api_key = os.getenv("EODHD_API_KEY", "")
    webhook = os.getenv("DISCORD_WEBHOOK_URL", "")
    
    print(f"EODHD API Key: {'✅' if api_key else '❌ MISSING'}")
    print(f"Discord Webhook: {'✅' if webhook else '❌ MISSING'}")
    print("="*60)
    
    if not api_key:
        print("❌ FATAL: EODHD_API_KEY not set!")
        sys.exit(1)
    
    # Import and start scanner
    try:
        print("[MAIN] Importing scanner module...")
        from scanner import start_scanner_loop
        
        print("[MAIN] Starting scanner loop...")
        start_scanner_loop()
        
    except ImportError as e:
        print(f"❌ IMPORT ERROR: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
    except Exception as e:
        print(f"❌ STARTUP ERROR: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
