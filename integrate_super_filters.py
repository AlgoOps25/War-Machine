# Integration script - adds super indicator filters to production_indicator_backtest.py

import re

with open('production_indicator_backtest.py', 'r', encoding='utf-8') as f:
    content = f.read()

# 1. Add import at top
import_line = "from super_indicator_filters import SuperIndicatorFilters, SUPER_FILTERS"
if import_line not in content:
    # Find the imports section and add it
    import_section = content.find("from typing import")
    if import_section != -1:
        # Find end of that line
        end_of_line = content.find("\n", import_section)
        content = content[:end_of_line+1] + import_line + "\n" + content[end_of_line+1:]
        print(" Added super filters import")

# 2. Add super indicator combo to CONFIG
super_combo_config = '''
    # Super Indicator Combos
    {
        "name": "Super Indicator (7-Way)",
        "filters": ["rsi_threshold", "supertrend_alignment", "volume_surge", 
                    "vwap_position", "ema_200_alignment", "atr_threshold", "time_filter"]
    },
    {
        "name": "Super Lite (5-Way)",
        "filters": ["supertrend_alignment", "volume_surge", "vwap_position", 
                    "atr_threshold", "time_filter"]
    },
'''

# Find the combinations list in CONFIG
combo_section = content.find('"combinations": [')
if combo_section != -1 and "Super Indicator" not in content:
    # Find the opening bracket
    bracket_pos = content.find('[', combo_section)
    # Insert after the bracket
    content = content[:bracket_pos+1] + "\n" + super_combo_config + content[bracket_pos+1:]
    print(" Added super indicator combos to CONFIG")

# 3. Register super filters in the apply_filters function
filter_registration = '''
# Super indicator filters
if 'supertrend_alignment' in active_filters:
    if 'atr' not in df.columns:
        df = calculate_atr_column(df)
    df = SuperIndicatorFilters.calculate_supertrend(df)
    if not SuperIndicatorFilters.supertrend_alignment(df, signal):
        return False

if 'vwap_position' in active_filters:
    df = SuperIndicatorFilters.calculate_vwap(df)
    if not SuperIndicatorFilters.vwap_position(df, signal):
        return False

if 'ema_200_alignment' in active_filters:
    df = SuperIndicatorFilters.calculate_ema_200(df)
    if not SuperIndicatorFilters.ema_200_alignment(df, signal):
        return False

if 'time_filter' in active_filters:
    if not SuperIndicatorFilters.time_filter(df, signal):
        return False
'''

# Find the apply_filters function
apply_filters_pos = content.find("def apply_filters(")
if apply_filters_pos != -1 and "supertrend_alignment" not in content:
    # Find the end of the function (before the next def or end of file)
    next_def = content.find("\ndef ", apply_filters_pos + 100)
    if next_def == -1:
        next_def = len(content)
    
    # Find the last return statement in the function
    function_content = content[apply_filters_pos:next_def]
    last_return = function_content.rfind("return True")
    
    if last_return != -1:
        insert_pos = apply_filters_pos + last_return
        content = content[:insert_pos] + filter_registration + "\n    " + content[insert_pos:]
        print(" Integrated super filters into apply_filters()")

# Write back
with open('production_indicator_backtest.py', 'w', encoding='utf-8') as f:
    f.write(content)

print("\n Integration complete!")
print("New combos added:")
print("  - Super Indicator (7-Way)")
print("  - Super Lite (5-Way)")
