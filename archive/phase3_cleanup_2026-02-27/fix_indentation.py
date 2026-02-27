import re

# Read the file
with open('comprehensive_backtest.py', 'r', encoding='utf-8') as f:
    lines = f.readlines()

# Find and fix the problematic section (around line 154)
fixed_lines = []
for i, line in enumerate(lines):
    # Replace the with statement while preserving indentation
    if 'with dict_cursor(conn) as cur:' in line:
        # Get the indentation (spaces before 'with')
        indent = line[:line.index('with')]
        # Replace with proper indented version
        fixed_lines.append(f"{indent}cur = dict_cursor(conn)\n")
        print(f"Fixed line {i+1}: removed 'with' statement")
    else:
        fixed_lines.append(line)

# Write back
with open('comprehensive_backtest.py', 'w', encoding='utf-8') as f:
    f.writelines(fixed_lines)

print("\n✅ Fixed indentation!")
print("Now run: python comprehensive_backtest.py")