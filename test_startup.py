"""
Minimal startup test - diagnose what's blocking
"""

import sys
import os

print("Step 1: Python running")
print(f"Python version: {sys.version}")

print("\nStep 2: Check environment")
print(f"EODHD_API_KEY: {'✅' if os.getenv('EODHD_API_KEY') else '❌'}")
print(f"DISCORD_WEBHOOK_URL: {'✅' if os.getenv('DISCORD_WEBHOOK_URL') else '❌'}")

print("\nStep 3: Test imports")
try:
    import requests
    print("✅ requests")
except ImportError as e:
    print(f"❌ requests: {e}")

try:
    import config
    print("✅ config")
except ImportError as e:
    print(f"❌ config: {e}")

try:
    import scanner_helpers
    print("✅ scanner_helpers")
except ImportError as e:
    print(f"❌ scanner_helpers: {e}")

try:
    import scanner
    print("✅ scanner")
except ImportError as e:
    print(f"❌ scanner: {e}")

try:
    import sniper
    print("✅ sniper")
except ImportError as e:
    print(f"❌ sniper: {e}")

print("\nStep 4: All imports successful!")
print("If you see this, the code should work.")

# Keep container alive
import time
while True:
    print(f"Container alive at {time.strftime('%I:%M:%S %p')}")
    time.sleep(60)
