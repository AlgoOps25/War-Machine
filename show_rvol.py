with open('scripts/backtesting/walk_forward_backtest.py', 'r', encoding='utf-8') as f:
    src = f.read()
idx = src.find('Step 2b')
print(repr(src[idx:idx+400]))
