import sys
from pathlib import Path

# Add parent directory to path so we can import from root
root_dir = Path(__file__).parent.parent
sys.path.insert(0, str(root_dir))


from data_manager import data_manager

print("Testing VIX fetch...")
try:
    # Test 1: get_bars_from_memory
    print("\n1. Testing get_bars_from_memory...")
    bars = data_manager.get_bars_from_memory("VIX", limit=1)
    print(f"   Memory: {bars}")
    
    # Test 2: get_bars
    print("\n2. Testing get_bars...")
    bars = data_manager.get_bars("VIX", timeframe="1m", limit=1)
    print(f"   API: {bars}")
    
    # Test 3: Check data_manager methods
    print("\n3. Available methods on data_manager:")
    methods = [m for m in dir(data_manager) if 'bar' in m.lower() and not m.startswith('_')]
    print(f"   {methods}")
    
    print("\n✅ All VIX tests passed!")
    
except AttributeError as e:
    print(f"\n❌ AttributeError: {e}")
    print(f"\n🔍 All data_manager attributes:")
    print([attr for attr in dir(data_manager) if not attr.startswith('_')])
    
except Exception as e:
    print(f"\n❌ Error: {type(e).__name__}: {e}")
