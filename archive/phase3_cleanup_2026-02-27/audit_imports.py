#!/usr/bin/env python3
"""
War Machine Import Dependency Audit
Scans all production files to verify import dependencies before cleanup
"""

import os
import re
from pathlib import Path

# Core production files that MUST be safe
CORE_FILES = [
    'sniper.py',
    'config.py',
    'discord_helpers.py',
    'validation.py',
    'ai_learning.py',
    'cfw6_confirmation.py',
    'trade_calculator.py',
    'data_manager.py',
    'position_manager.py',
    'bos_fvg_engine.py',
    'db_connection.py',
]

# Files we're considering archiving
ARCHIVE_CANDIDATES = [
    'adaptive_historical_tuner.py',
    'analyze_optimization_results.py',
    'advanced_mtf_backtest.py',
    'advanced_indicators.py',
    'breakout_detector.py',
    'build_cache.py',
]

def find_imports_in_file(filepath):
    """Extract all import statements from a Python file"""
    imports = set()
    try:
        with open(filepath, 'r', encoding='utf-8') as f:
            content = f.read()
            
        # Match: from X import Y
        from_imports = re.findall(r'from\s+(\w+)\s+import', content)
        imports.update(from_imports)
        
        # Match: import X
        direct_imports = re.findall(r'^\s*import\s+(\w+)', content, re.MULTILINE)
        imports.update(direct_imports)
        
    except Exception as e:
        print(f"Error reading {filepath}: {e}")
    
    return imports

def audit_dependencies():
    """Check if any core file imports archive candidates"""
    print("="*80)
    print("WAR MACHINE IMPORT DEPENDENCY AUDIT")
    print("="*80)
    
    # Scan all core files
    violations = {}
    safe = []
    
    print("\n🔍 Scanning core files for imports...\n")
    
    for candidate in ARCHIVE_CANDIDATES:
        module_name = candidate.replace('.py', '')
        found = False
        
        print(f"Checking: {candidate}", end=" ")
        
        for core_file in CORE_FILES:
            if not os.path.exists(core_file):
                continue
            
            imports = find_imports_in_file(core_file)
            
            if module_name in imports:
                if candidate not in violations:
                    violations[candidate] = []
                violations[candidate].append(core_file)
                found = True
        
        if found:
            print("❌ USED")
        else:
            print("✅ SAFE")
            safe.append(candidate)
    
    # Report results
    print("\n" + "="*80)
    
    if violations:
        print("\n❌ BLOCKING ISSUES FOUND:")
        print("-"*80)
        for candidate, core_files in violations.items():
            print(f"\n{candidate} is imported by:")
            for core_file in core_files:
                print(f"  - {core_file}")
        print("\n⚠️  DO NOT ARCHIVE THESE FILES - THEY ARE ACTIVELY USED")
        print("-"*80)
        status = "HALT - MANUAL REVIEW REQUIRED"
        return False
    else:
        print("\n✅ ALL CLEAR - Archive candidates are NOT imported by core files")
        print("\nSafe to archive:")
        for file in safe:
            print(f"  ✓ {file}")
        status = "SAFE TO PROCEED WITH CLEANUP"
        return True
    
    print("\n" + "="*80)
    print(f"STATUS: {status}")
    print("="*80)

if __name__ == "__main__":
    safe = audit_dependencies()
    print("\n" + "="*80)
    if safe:
        print("✅ STATUS: SAFE TO PROCEED WITH CLEANUP")
    else:
        print("❌ STATUS: HALT - MANUAL REVIEW REQUIRED")
    print("="*80)
