# Find and replace the detection logic in production_indicator_backtest.py

import re

with open('production_indicator_backtest.py', 'r', encoding='utf-8') as f:
    content = f.read()

# Find the section to replace (lines 275-282)
old_code = """            # Detect breakouts
            result = detector.detect_breakout(df.to_dict("records"), ticker)
            signals = [result] if result is not None else []
            signals = [result] if result is not None else []
            signals = [result] if result is not None else []

            if not signals:
                print(" (0 signals)")
                continue"""

new_code = """            # Detect breakouts - scan bar-by-bar
            signals = []
            bars_list = df.to_dict("records")
            
            # Start after minimum bars needed
            for i in range(100, len(bars_list)):
                bars_subset = bars_list[:i+1]
                result = detector.detect_breakout(bars_subset, ticker)
                if result:
                    signals.append(result)
            
            if not signals:
                print(f" (0 signals)")
                continue
            
            print(f" ({len(signals)} signals)")"""

content = content.replace(old_code, new_code)

with open('production_indicator_backtest.py', 'w', encoding='utf-8') as f:
    f.write(content)

print(" Fixed backtest to scan bar-by-bar!")
