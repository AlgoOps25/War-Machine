#!/usr/bin/env python3
"""
Fix #1: Automated Migration Script - Thread-Safe State Management

This script migrates sniper.py to use the new ThreadSafeState singleton,
replacing all direct dictionary operations with thread-safe method calls.

Usage:
    python MIGRATION_SCRIPT_FIX_1.py

Backup created automatically before migration.
"""

import re
import shutil
from datetime import datetime
from pathlib import Path

def backup_file(file_path: Path) -> Path:
    """Create timestamped backup of original file"""
    timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    backup_path = file_path.parent / f"{file_path.stem}_backup_{timestamp}{file_path.suffix}"
    shutil.copy2(file_path, backup_path)
    print(f"✅ Backup created: {backup_path}")
    return backup_path

def apply_migration(content: str) -> tuple[str, int]:
    """
    Apply all migration transformations.
    Returns (migrated_content, num_changes)
    """
    changes = 0
    original = content
    
    # Patch 1: Add thread-safe state import
    pattern = r'from app\.filters\.early_session_disqualifier import should_skip_cfw6_or_early'
    replacement = '''from app.filters.early_session_disqualifier import should_skip_cfw6_or_early

# ══════════════════════════════════════════════════════════════════════════════
# FIX #1: THREAD-SAFE STATE MANAGEMENT
# ══════════════════════════════════════════════════════════════════════════════
from app.core.thread_safe_state import get_state

_state = get_state()
print("[SNIPER] ✅ Thread-safe state management enabled")'''
    content, n = re.subn(pattern, replacement, content)
    changes += n
    
    # Patch 2: Remove old timing globals
    pattern = r'_last_dashboard_check = datetime\.now\(\)\n_last_alert_check = datetime\.now\(\)'
    replacement = '# Dashboard/alert timing now managed by thread-safe state'
    content, n = re.subn(pattern, replacement, content)
    changes += n
    
    # Patch 3: Remove validator stats global
    pattern = r"_validator_stats = \{'tested': 0, 'passed': 0, 'filtered': 0, 'boosted': 0, 'penalized': 0\}"
    replacement = '# Validator stats now managed by thread-safe state'
    content, n = re.subn(pattern, replacement, content)
    changes += n
    
    # Patch 4: Remove validation call tracker global
    pattern = r'_validation_call_tracker = \{\}'
    replacement = '# Validation call tracker now managed by thread-safe state'
    content, n = re.subn(pattern, replacement, content)
    changes += n
    
    # Patch 5: Remove armed/watching globals
    pattern = r'armed_signals = \{\}\nwatching_signals = \{\}\n_watches_loaded = False\n_armed_loaded = False'
    replacement = '# Thread-safe state is now managed by _state singleton\n# Access via: _state.get_armed_signal(ticker), _state.ticker_is_armed(ticker), etc.'
    content, n = re.subn(pattern, replacement, content)
    changes += n
    
    # Patch 6: Update _track_validation_call function
    pattern = r'def _track_validation_call\(ticker: str, direction: str, price: float\) -> bool:\s+signal_id = _get_signal_id\(ticker, direction, price\)\s+if signal_id in _validation_call_tracker:\s+_validation_call_tracker\[signal_id\] \+= 1'
    replacement = '''def _track_validation_call(ticker: str, direction: str, price: float) -> bool:
    signal_id = _get_signal_id(ticker, direction, price)
    call_count = _state.track_validation_call(signal_id)  # Thread-safe
    if call_count > 1'''
    content, n = re.subn(pattern, replacement, content, flags=re.MULTILINE)
    changes += n
    
    # Fix the remainder of _track_validation_call
    pattern = r'f"\[VALIDATOR\] ⚠️  WARNING: \{ticker\} validated \{_validation_call_tracker\[signal_id\]\} times "'
    replacement = r'f"[VALIDATOR] ⚠️  WARNING: {ticker} validated {call_count} times "'
    content, n = re.subn(pattern, replacement, content)
    changes += n
    
    pattern = r'_validation_call_tracker\[signal_id\] = 1\s+return False'
    replacement = 'return False'
    content, n = re.suben(pattern, replacement, content)
    changes += n
    
    # Patch 7: Update print_validation_stats
    pattern = r'def print_validation_stats\(\):\s+if not VALIDATOR_ENABLED or _validator_stats\[\'tested\'\] == 0:\s+return\s+stats = _validator_stats'
    replacement = '''def print_validation_stats():
    if not VALIDATOR_ENABLED:
        return
    stats = _state.get_validator_stats()  # Thread-safe copy
    if stats['tested'] == 0:
        return'''
    content, n = re.subn(pattern, replacement, content, flags=re.MULTILINE)
    changes += n
    
    # Patch 8: Update print_validation_call_stats
    pattern = r'if not _validation_call_tracker:\s+return\s+total_signals = len\(_validation_call_tracker\)\s+duplicate_calls = \[\s+\(sig_id, count\) for sig_id, count in _validation_call_tracker\.items\(\)'
    replacement = '''tracker = _state.get_validation_call_tracker()  # Thread-safe copy
    if not tracker:
        return
    total_signals = len(tracker)
    duplicate_calls = [
        (sig_id, count) for sig_id, count in tracker.items()'''
    content, n = re.subn(pattern, replacement, content, flags=re.MULTILINE)
    changes += n
    
    # Patch 9-16: Replace all armed_signals operations
    replacements = [
        (r'if ticker in armed_signals:', r'if _state.ticker_is_armed(ticker):'),
        (r'armed_signals\[ticker\] = ', r'_state.set_armed_signal(ticker, '),
        (r'del armed_signals\[ticker\]', r'_state.remove_armed_signal(ticker)'),
        (r'armed_signals\.clear\(\)', r'_state.clear_armed_signals()'),
        (r'armed_signals\.update\(', r'_state.update_armed_signals_bulk('),
    ]
    
    for pattern, replacement in replacements:
        content, n = re.subn(pattern, replacement, content)
        changes += n
    
    # Patch 17-22: Replace all watching_signals operations
    replacements = [
        (r'if ticker in watching_signals:', r'if _state.ticker_is_watching(ticker):'),
        (r'watching_signals\[ticker\] = ', r'_state.set_watching_signal(ticker, '),
        (r'del watching_signals\[ticker\]', r'_state.remove_watching_signal(ticker)'),
        (r'watching_signals\.clear\(\)', r'_state.clear_watching_signals()'),
        (r'watching_signals\.update\(', r'_state.update_watching_signals_bulk('),
    ]
    
    for pattern, replacement in replacements:
        content, n = re.suben(pattern, replacement, content)
        changes += n
    
    # Patch 23: Fix watching_signals dict access patterns
    pattern = r'w = watching_signals\[ticker\]'
    replacement = r'w = _state.get_watching_signal(ticker)'
    content, n = re.subn(pattern, replacement, content)
    changes += n
    
    pattern = r'w\["breakout_idx"\] = resolved_idx'
    replacement = r'_state.update_watching_signal_field(ticker, "breakout_idx", resolved_idx)'
    content, n = re.subn(pattern, replacement, content)
    changes += n
    
    # Patch 24-28: Replace _validator_stats operations
    replacements = [
        (r"_validator_stats\['tested'\] \+= 1", r"_state.increment_validator_stat('tested')"),
        (r"_validator_stats\['passed'\] \+= 1", r"_state.increment_validator_stat('passed')"),
        (r"_validator_stats\['filtered'\] \+= 1", r"_state.increment_validator_stat('filtered')"),
        (r"_validator_stats\['boosted'\] \+= 1", r"_state.increment_validator_stat('boosted')"),
        (r"_validator_stats\['penalized'\] \+= 1", r"_state.increment_validator_stat('penalized')"),
    ]
    
    for pattern, replacement in replacements:
        content, n = re.subn(pattern, replacement, content)
        changes += n
    
    # Patch 29-32: Replace dashboard/alert timing
    replacements = [
        (r'\(now - _last_dashboard_check\)', r'(now - _state.get_last_dashboard_check())'),
        (r'_last_dashboard_check = now', r'_state.update_last_dashboard_check(now)'),
        (r'\(now - _last_alert_check\)', r'(now - _state.get_last_alert_check())'),
        (r'_last_alert_check = now', r'_state.update_last_alert_check(now)'),
    ]
    
    for pattern, replacement in replacements:
        content, n = re.subn(pattern, replacement, content)
        changes += n
    
    # Patch 33-34: Update _maybe_load_armed_signals
    pattern = r'global _armed_loaded, armed_signals\s+if _armed_loaded:\s+return\s+_armed_loaded = True'
    replacement = '''if _state.is_armed_loaded():
        return
    _state.set_armed_loaded(True)'''
    content, n = re.subn(pattern, replacement, content, flags=re.MULTILINE)
    changes += n
    
    pattern = r'if loaded:\s+armed_signals\.update\(loaded\)'
    replacement = '''if loaded:
        _state.update_armed_signals_bulk(loaded)'''
    content, n = re.subn(pattern, replacement, content, flags=re.MULTILINE)
    changes += n
    
    # Patch 35-36: Update _maybe_load_watches
    pattern = r'global _watches_loaded, watching_signals\s+if _watches_loaded:\s+return\s+_watches_loaded = True'
    replacement = '''if _state.is_watches_loaded():
        return
    _state.set_watches_loaded(True)'''
    content, n = re.subn(pattern, replacement, content, flags=re.MULTILINE)
    changes += n
    
    pattern = r'if loaded:\s+watching_signals\.update\(loaded\)'
    replacement = '''if loaded:
        _state.update_watching_signals_bulk(loaded)'''
    content, n = re.subn(pattern, replacement, content, flags=re.MULTILINE)
    changes += n
    
    # Patch 37-38: Update clear functions
    pattern = r'def clear_armed_signals\(\):\s+global _armed_loaded\s+armed_signals\.clear\(\)\s+_armed_loaded = False'
    replacement = '''def clear_armed_signals():
    _state.clear_armed_signals()  # Thread-safe clear + reset loaded flag'''
    content, n = re.subn(pattern, replacement, content, flags=re.MULTILINE)
    changes += n
    
    pattern = r'def clear_watching_signals\(\):\s+global _watches_loaded\s+watching_signals\.clear\(\)\s+_watches_loaded = False'
    replacement = '''def clear_watching_signals():
    _state.clear_watching_signals()  # Thread-safe clear + reset loaded flag'''
    content, n = re.subn(pattern, replacement, content, flags=re.MULTILINE)
    changes += n
    
    return content, changes

def main():
    print("="*70)
    print("Fix #1: Thread-Safe State Migration")
    print("="*70)
    print()
    
    sniper_path = Path(__file__).parent / 'app' / 'core' / 'sniper.py'
    
    if not sniper_path.exists():
        print(f"❌ Error: {sniper_path} not found")
        print("   Make sure you run this from the War-Machine root directory")
        return 1
    
    print(f"📁 Target file: {sniper_path}")
    
    # Create backup
    backup_path = backup_file(sniper_path)
    
    # Load content
    print("📖 Loading sniper.py...")
    with open(sniper_path, 'r') as f:
        content = f.read()
    
    original_lines = len(content.splitlines())
    print(f"   Original: {original_lines} lines, {len(content):,} bytes")
    
    # Apply migration
    print("\n🔧 Applying thread-safe state migration...")
    migrated, changes = apply_migration(content)
    
    migrated_lines = len(migrated.splitlines())
    print(f"   Migrated: {migrated_lines} lines, {len(migrated):,} bytes")
    print(f"   Changes applied: {changes}")
    
    if changes == 0:
        print("\n⚠️  Warning: No changes were applied!")
        print("   File may already be migrated or patterns didn't match.")
        return 1
    
    # Write migrated content
    print("\n💾 Writing migrated file...")
    with open(sniper_path, 'w') as f:
        f.write(migrated)
    
    print("\n✅ Migration complete!")
    print()
    print("Next steps:")
    print("  1. Review changes: git diff app/core/sniper.py")
    print("  2. Run tests to verify functionality")
    print(f"  3. If issues occur, restore from: {backup_path.name}")
    print()
    print("="*70)
    
    return 0

if __name__ == '__main__':
    exit(main())
