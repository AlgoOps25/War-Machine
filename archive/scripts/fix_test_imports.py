#!/usr/bin/env python3
"""
Fix test file imports after moving tests to tests/ directory.

This adds the parent directory to sys.path so tests can import
modules from the root directory.
"""

import os
from pathlib import Path

def fix_test_file(test_path):
    """Add sys.path fix to beginning of test file."""
    
    path_fix = '''import sys
from pathlib import Path

# Add parent directory to path so we can import from root
root_dir = Path(__file__).parent.parent
sys.path.insert(0, str(root_dir))

'''
    
    with open(test_path, 'r', encoding='utf-8') as f:
        content = f.read()
    
    # Check if already fixed
    if 'sys.path.insert(0, str(root_dir))' in content:
        print(f"✓ {test_path.name} already fixed")
        return False
    
    # Find the first import statement
    lines = content.split('\n')
    insert_index = 0
    
    # Skip shebang, docstring, and comments at the top
    in_docstring = False
    for i, line in enumerate(lines):
        stripped = line.strip()
        
        # Handle docstrings
        if stripped.startswith('"""') or stripped.startswith("'''"):
            in_docstring = not in_docstring
            continue
        
        if in_docstring:
            continue
        
        # Find first import
        if stripped.startswith('import ') or stripped.startswith('from '):
            insert_index = i
            break
    
    # Insert the path fix before the first import
    new_lines = lines[:insert_index] + path_fix.split('\n') + lines[insert_index:]
    new_content = '\n'.join(new_lines)
    
    # Write back
    with open(test_path, 'w', encoding='utf-8') as f:
        f.write(new_content)
    
    print(f"✓ Fixed {test_path.name}")
    return True

def main():
    print("="*80)
    print("FIXING TEST IMPORTS")
    print("="*80)
    print()
    
    tests_dir = Path('tests')
    
    if not tests_dir.exists():
        print("❌ tests/ directory not found!")
        print("   Make sure you're in the War-Machine root directory.")
        return 1
    
    # Find all test Python files
    test_files = list(tests_dir.glob('test_*.py')) + list(tests_dir.glob('*_test.py'))
    test_files += [p for p in tests_dir.glob('*.py') if 'diagnostic' in p.name.lower()]
    
    if not test_files:
        print("❌ No test files found in tests/")
        return 1
    
    print(f"Found {len(test_files)} test files:\n")
    
    fixed_count = 0
    for test_file in test_files:
        if fix_test_file(test_file):
            fixed_count += 1
    
    print()
    print("="*80)
    print(f"✓ Fixed {fixed_count} test file(s)")
    print("="*80)
    print()
    print("Next: Test the system")
    print("  python tests/test_full_pipeline.py")
    print()
    
    return 0

if __name__ == '__main__':
    exit(main())
