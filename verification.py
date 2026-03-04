#!/usr/bin/env python3
"""
Verify which duplicate files are actually imported by production code
"""
import sys
import os

# Test 1: Which config gets imported?
print("=" * 60)
print("TEST 1: Config Import Path")
print("=" * 60)
try:
    from utils import config
    print(f"✅ utils.config imported successfully")
    print(f"   Location: {config.__file__}")
    print(f"   Has MARKET_OPEN: {hasattr(config, 'MARKET_OPEN')}")
except ImportError as e:
    print(f"❌ Failed to import utils.config: {e}")

try:
    import config as root_config
    print(f"✅ root config imported successfully")
    print(f"   Location: {root_config.__file__}")
except ImportError as e:
    print(f"❌ Failed to import root config: {e}")

# Test 2: Which discord_helpers gets imported?
print("\n" + "=" * 60)
print("TEST 2: Discord Helpers Import Path")
print("=" * 60)
try:
    from app import discord_helpers as app_discord
    print(f"✅ app.discord_helpers imported successfully")
    print(f"   Location: {app_discord.__file__}")
    print(f"   Has send_simple_message: {hasattr(app_discord, 'send_simple_message')}")
except ImportError as e:
    print(f"❌ Failed to import app.discord_helpers: {e}")

try:
    from utils import discord_helpers as utils_discord
    print(f"✅ utils.discord_helpers imported successfully")
    print(f"   Location: {utils_discord.__file__}")
except ImportError as e:
    print(f"❌ Failed to import utils.discord_helpers: {e}")

# Test 3: Check if production files exist
print("\n" + "=" * 60)
print("TEST 3: Production vs Root Files")
print("=" * 60)
prod_sniper = "app/core/sniper.py"
root_sniper = "sniper.py"
print(f"Production sniper exists: {os.path.exists(prod_sniper)}")
print(f"Root sniper exists: {os.path.exists(root_sniper)}")

prod_position = "app/risk/position_manager.py"
root_position = "position_manager.py"
print(f"Production position_manager exists: {os.path.exists(prod_position)}")
print(f"Root position_manager exists: {os.path.exists(root_position)}")
