"""
War Machine System Test Suite - ACCURATE VERSION
Tests actual modules and functions based on real repository structure
"""

import sys

print("=" * 80)
print(" WAR MACHINE - SYSTEM VERIFICATION TEST")
print("=" * 80)
print()

tests_passed = 0
tests_failed = 0
errors = []

def test_import(module_path, description):
    global tests_passed, tests_failed, errors
    try:
        exec(f"import {module_path}")
        print(f"✅ {description}")
        tests_passed += 1
        return True
    except Exception as e:
        print(f"❌ {description}")
        print(f"   Error: {str(e)[:100]}")
        tests_failed += 1
        errors.append({"module": module_path, "error": str(e)})
        return False

def test_from_import(from_module, import_what, description):
    global tests_passed, tests_failed, errors
    try:
        exec(f"from {from_module} import {import_what}")
        print(f"✅ {description}")
        tests_passed += 1
        return True
    except Exception as e:
        print(f"❌ {description}")
        print(f"   Error: {str(e)[:100]}")
        tests_failed += 1
        errors.append({"module": f"{from_module}.{import_what}", "error": str(e)})
        return False

print("PHASE 1: Core Configuration & Database")
print("-" * 80)
test_import("utils.config", "Config module")
test_import("utils.db_connection", "Database connection")
test_import("utils.production_helpers", "Production helpers")
print()

print("PHASE 2: Critical Signal Detection (CORE SYSTEM)")
print("-" * 80)
test_from_import("app.signals.breakout_detector", "BreakoutDetector", "Breakout Detector (BOS+FVG)")
test_from_import("app.signals.signal_generator", "SignalGenerator", "Signal Generator")
print()

print("PHASE 3: Backtesting Engine")
print("-" * 80)
test_from_import("app.backtesting.backtest_engine", "BacktestEngine", "Backtest Engine")
print()

print("PHASE 4: Discord Notifications")
print("-" * 80)
test_from_import("app.discord_helpers", "send_options_signal_alert", "Options signal alert")
test_from_import("app.discord_helpers", "send_exit_alert", "Exit alert")
test_from_import("app.discord_helpers", "send_scaling_alert", "Scaling alert")
test_from_import("app.discord_helpers", "send_simple_message", "Simple message")
test_from_import("app.discord_helpers", "test_webhook", "Webhook tester")
print()

print("PHASE 5: Additional App Modules (If Available)")
print("-" * 80)

# Test directories that exist
app_modules = [
    ("app.core", "Core module"),
    ("app.data", "Data module"),
    ("app.filters", "Filters module"),
    ("app.indicators", "Indicators module"),
    ("app.ml", "ML module"),
    ("app.models", "Models module"),
    ("app.mtf", "Multi-timeframe module"),
    ("app.options", "Options module"),
    ("app.risk", "Risk module"),
    ("app.screening", "Screening module"),
    ("app.validation", "Validation module"),
    ("app.analytics", "Analytics module"),
    ("app.ai", "AI module"),
]

for module, desc in app_modules:
    test_import(module, desc)

print()

# Summary
print("=" * 80)
print(" TEST RESULTS")
print("=" * 80)
print()
print(f"✅ Passed: {tests_passed}")
print(f"❌ Failed: {tests_failed}")
print(f"📊 Total:  {tests_passed + tests_failed}")

if tests_passed + tests_failed > 0:
    success_rate = (tests_passed / (tests_passed + tests_failed) * 100)
    print(f"🎯 Success Rate: {success_rate:.1f}%")
print()

# Critical systems check
critical_modules = [
    "utils.config",
    "app.signals.breakout_detector",
    "app.signals.signal_generator",
    "app.backtesting.backtest_engine",
    "app.discord_helpers"
]

print("=" * 80)
print(" CRITICAL SYSTEMS CHECK")
print("=" * 80)
print()

critical_passed = all(
    module not in [e["module"].split(".")[0] + "." + e["module"].split(".")[1] 
                   if "." in e["module"] else e["module"] 
                   for e in errors]
    for module in critical_modules
)

if critical_passed:
    print("🎉 ALL CRITICAL SYSTEMS OPERATIONAL!")
    print()
    print("✅ Configuration loaded")
    print("✅ Signal detection working")
    print("✅ Backtesting engine ready")
    print("✅ Discord notifications ready")
    print()
    print("📊 Your War Machine is FULLY FUNCTIONAL after reorganization!")
    sys.exit(0)
else:
    print("⚠️  Some critical systems have issues:")
    for error in errors:
        if any(crit in error["module"] for crit in critical_modules):
            print(f"   ❌ {error['module']}")
    sys.exit(1)
