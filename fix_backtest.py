import re

with open('production_indicator_backtest.py', 'r', encoding='utf-8') as f:
    content = f.read()

# Fix the line
old_line = 'signals = detector.detect_bos(df)'
new_line = 'signals = [detector.detect_breakout(df.to_dict("records"), ticker)] if not df.empty else []'

content = content.replace(old_line, new_line)

with open('production_indicator_backtest.py', 'w', encoding='utf-8') as f:
    f.write(content)

print(' Fixed!')
