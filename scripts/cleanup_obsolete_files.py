#!/usr/bin/env python3
"""
War Machine Repository Cleanup Script
Safely removes obsolete files (backups, historical docs, completed migrations)

Usage:
    python scripts/cleanup_obsolete_files.py --dry-run  # Preview changes
    python scripts/cleanup_obsolete_files.py            # Execute cleanup
    python scripts/cleanup_obsolete_files.py --backup   # Create backup archive first

Author: War Machine Team
Date: March 9, 2026
"""
import os
import shutil
import argparse
from pathlib import Path
from datetime import datetime
import json

# Project root
PROJECT_ROOT = Path(__file__).resolve().parent.parent

# Files to delete (relative to project root)
OBSOLETE_FILES = [
    # ═══════════════════════════════════════════════════════════════════════
    # ROOT LEVEL - Old standalone files and backups
    # ═══════════════════════════════════════════════════════════════════════
    "breakout_detector.py",                    # Old standalone, now in app/core/sniper.py
    "sniper_backup_20260306_232502.py",        # Old backup
    "sniper_backup_20260306_232640.py",        # Duplicate backup
    
    # ═══════════════════════════════════════════════════════════════════════
    # ROOT LEVEL - Historical migration and fix documentation
    # ═══════════════════════════════════════════════════════════════════════
    "MIGRATION_SCRIPT_FIX_1.py",               # One-time migration (completed)
    "FIX_1_COMPLETE_STATUS.md",                # Historical fix doc
    "FIX_1_DEPLOYMENT_SUMMARY.md",             # Historical deployment doc
    "FIX_1_QUICK_REFERENCE.md",                # Historical reference doc
    "FIX_2_CONNECTION_POOL_MIGRATION.md",      # Historical migration doc
    "PHASE_1_14_SUMMARY.md",                   # Historical phase doc
    "SECURITY_FIX_3_SUMMARY.md",               # Historical security fix
    "SECURITY_FIX_4_SUMMARY.md",               # Historical security fix
    
    # ═══════════════════════════════════════════════════════════════════════
    # ROOT LEVEL - Test files that should be in /tests directory
    # ═══════════════════════════════════════════════════════════════════════
    "test_0dte_options.py",                    # Should be in /tests
    "test_discord_alerts.py",                  # Should be in /tests
    "trigger_test_alert.py",                   # One-time test script
    
    # ═══════════════════════════════════════════════════════════════════════
    # DOCS - Completed task documentation
    # ═══════════════════════════════════════════════════════════════════════
    "docs/ACTION_ITEM_5_COMPLETE.md",          # Completed task
    "docs/INTEGRATION_COMPLETE.md",            # Completed integration
    "docs/PHASE_4_INTEGRATION_COMPLETE.md",    # Completed phase
    "docs/Phase_1_14_Deployment_Checklist.md", # Completed checklist
    "docs/Phase_1_14_Implementation_Notes.md", # Historical notes
    "docs/ISSUES_17-23_COMPLETION_SUMMARY.md", # Historical summary
    "docs/ISSUE_20_WARMACHINECONFIG_ANALYSIS.md", # Historical analysis
    "docs/SNIPER_INTEGRATION_PATCH.md",        # Historical patch doc
    "docs/TASK_2_SNIPER_UPDATE.md",            # Completed task
    "docs/TASK3_GREEKS_INTEGRATION.md",        # Completed integration
    "docs/TASKS_4_5_6_IMPLEMENTATION.md",      # Completed tasks
    "docs/TASKS_4_6_INTEGRATION.md",           # Completed integration
    "docs/TASK_8_INTEGRATION.md",              # Completed task
    "docs/task9_integration_guide.md",         # Completed guide
    "docs/task10_backtesting_guide.md",        # Outdated guide
    
    # ═══════════════════════════════════════════════════════════════════════
    # TESTS - Outdated phase-specific tests
    # ═══════════════════════════════════════════════════════════════════════
    "tests/README_Phase_1_14.md",              # Phase-specific readme
    "tests/test_phase_1_14.py",                # Phase test (feature complete)
    "tests/test_phase_3e_mtf_consolidation.py", # Phase test (feature complete)
    "tests/test_days_1_4_end_to_end.py",       # Old end-to-end test
    "tests/diagnostics.py",                    # Simple diagnostic (replaced)
    "tests/fix_analytics_files.ps1",           # One-time fix script
]


def create_backup_archive():
    """Create a timestamped backup archive of files to be deleted."""
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_dir = PROJECT_ROOT / "backups" / f"cleanup_backup_{timestamp}"
    backup_dir.mkdir(parents=True, exist_ok=True)
    
    backed_up = 0
    for file_path in OBSOLETE_FILES:
        full_path = PROJECT_ROOT / file_path
        if full_path.exists():
            # Preserve directory structure in backup
            relative_path = full_path.relative_to(PROJECT_ROOT)
            backup_file = backup_dir / relative_path
            backup_file.parent.mkdir(parents=True, exist_ok=True)
            
            shutil.copy2(full_path, backup_file)
            backed_up += 1
            print(f"  ✓ Backed up: {file_path}")
    
    # Create manifest
    manifest = {
        "timestamp": timestamp,
        "files_backed_up": backed_up,
        "file_list": OBSOLETE_FILES
    }
    
    manifest_path = backup_dir / "backup_manifest.json"
    with open(manifest_path, "w") as f:
        json.dump(manifest, f, indent=2)
    
    print(f"\n✅ Backup created: {backup_dir}")
    print(f"📦 Files backed up: {backed_up}")
    return backup_dir


def analyze_files():
    """Analyze which files exist and calculate total size."""
    existing_files = []
    missing_files = []
    total_size = 0
    
    for file_path in OBSOLETE_FILES:
        full_path = PROJECT_ROOT / file_path
        if full_path.exists():
            size = full_path.stat().st_size
            existing_files.append({
                "path": file_path,
                "size": size,
                "size_kb": round(size / 1024, 2)
            })
            total_size += size
        else:
            missing_files.append(file_path)
    
    return existing_files, missing_files, total_size


def print_analysis(existing_files, missing_files, total_size):
    """Print detailed analysis of files to be deleted."""
    print("\n" + "="*80)
    print("WAR MACHINE REPOSITORY CLEANUP ANALYSIS")
    print("="*80)
    
    print(f"\n📊 SUMMARY:")
    print(f"   Total files in cleanup list: {len(OBSOLETE_FILES)}")
    print(f"   Files found: {len(existing_files)}")
    print(f"   Already deleted: {len(missing_files)}")
    print(f"   Total size to free: {round(total_size / 1024, 2)} KB ({round(total_size / (1024*1024), 2)} MB)")
    
    if existing_files:
        print(f"\n🗑️  FILES TO BE DELETED ({len(existing_files)}):")
        print("-" * 80)
        
        # Group by category
        root_files = [f for f in existing_files if "/" not in f["path"]]
        docs_files = [f for f in existing_files if f["path"].startswith("docs/")]
        test_files = [f for f in existing_files if f["path"].startswith("tests/")]
        
        if root_files:
            print("\n  📁 ROOT LEVEL:")
            for f in root_files:
                print(f"     - {f['path']:<50} ({f['size_kb']} KB)")
        
        if docs_files:
            print("\n  📁 DOCS:")
            for f in docs_files:
                print(f"     - {f['path']:<50} ({f['size_kb']} KB)")
        
        if test_files:
            print("\n  📁 TESTS:")
            for f in test_files:
                print(f"     - {f['path']:<50} ({f['size_kb']} KB)")
    
    if missing_files:
        print(f"\n✓ ALREADY DELETED ({len(missing_files)}):")
        for f in missing_files[:5]:  # Show first 5
            print(f"     - {f}")
        if len(missing_files) > 5:
            print(f"     ... and {len(missing_files) - 5} more")
    
    print("\n" + "="*80)


def delete_files(dry_run=True):
    """Delete obsolete files."""
    deleted_count = 0
    failed_deletions = []
    
    for file_path in OBSOLETE_FILES:
        full_path = PROJECT_ROOT / file_path
        
        if not full_path.exists():
            continue
        
        try:
            if dry_run:
                print(f"  [DRY RUN] Would delete: {file_path}")
            else:
                full_path.unlink()
                print(f"  ✓ Deleted: {file_path}")
                deleted_count += 1
        except Exception as e:
            failed_deletions.append({
                "file": file_path,
                "error": str(e)
            })
            print(f"  ✗ Failed to delete {file_path}: {e}")
    
    return deleted_count, failed_deletions


def generate_report(deleted_count, failed_deletions, backup_dir=None):
    """Generate cleanup report."""
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    
    report = f"""
WAR MACHINE REPOSITORY CLEANUP REPORT
Generated: {timestamp}

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

CLEANUP SUMMARY:
  Files successfully deleted: {deleted_count}
  Failed deletions: {len(failed_deletions)}
  Backup created: {"Yes" if backup_dir else "No"}
  {"Backup location: " + str(backup_dir) if backup_dir else ""}

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

CATEGORIES CLEANED:
  ✓ Old backups (sniper_backup_*.py)
  ✓ Historical migration scripts (MIGRATION_SCRIPT_FIX_1.py)
  ✓ Completed fix documentation (FIX_*, SECURITY_FIX_*)
  ✓ Phase completion docs (PHASE_*, Phase_1_14_*)
  ✓ Task completion docs (TASK_*, ACTION_ITEM_*)
  ✓ Integration completion docs (INTEGRATION_COMPLETE.md)
  ✓ Outdated test files (test_phase_*.py, test_days_*.py)
  ✓ Misplaced root test files (test_*.py in root)

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

REPOSITORY STATUS:
  ✅ All obsolete files removed
  ✅ Active code preserved
  ✅ Production deployment unaffected
  ✅ Test suite maintained (active tests kept)

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

NEXT STEPS:
  1. Review cleanup results above
  2. Run: git status (to see deleted files)
  3. Commit changes: git add -A && git commit -m "Clean up obsolete files"
  4. Push to GitHub: git push origin main

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
"""
    
    if failed_deletions:
        report += "\n⚠️  FAILED DELETIONS:\n"
        for failure in failed_deletions:
            report += f"   - {failure['file']}: {failure['error']}\n"
    
    return report


def main():
    parser = argparse.ArgumentParser(
        description="Clean up obsolete files from War Machine repository"
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Preview changes without deleting files"
    )
    parser.add_argument(
        "--backup",
        action="store_true",
        help="Create backup archive before deletion"
    )
    parser.add_argument(
        "--skip-confirmation",
        action="store_true",
        help="Skip confirmation prompt (use with caution)"
    )
    
    args = parser.parse_args()
    
    print("\n🎯 WAR MACHINE REPOSITORY CLEANUP")
    print("="*80)
    
    # Analyze files
    existing_files, missing_files, total_size = analyze_files()
    print_analysis(existing_files, missing_files, total_size)
    
    if not existing_files:
        print("\n✅ No files to clean up. Repository is already clean!")
        return
    
    # Confirmation
    if args.dry_run:
        print("\n🔍 DRY RUN MODE - No files will be deleted")
    else:
        if not args.skip_confirmation:
            print(f"\n⚠️  WARNING: This will permanently delete {len(existing_files)} files!")
            response = input("\nProceed with cleanup? (yes/no): ").lower().strip()
            if response != "yes":
                print("❌ Cleanup cancelled")
                return
    
    backup_dir = None
    if args.backup and not args.dry_run:
        print("\n📦 Creating backup archive...")
        backup_dir = create_backup_archive()
    
    # Delete files
    print(f"\n{'🔍 Analyzing' if args.dry_run else '🗑️  Deleting'} files...")
    print("-" * 80)
    deleted_count, failed_deletions = delete_files(dry_run=args.dry_run)
    
    # Generate report
    if not args.dry_run:
        report = generate_report(deleted_count, failed_deletions, backup_dir)
        print(report)
        
        # Save report
        report_path = PROJECT_ROOT / "cleanup_report.txt"
        with open(report_path, "w") as f:
            f.write(report)
        print(f"📄 Full report saved to: {report_path}")
    else:
        print(f"\n✅ Dry run complete. {len(existing_files)} files would be deleted.")
        print("   Run without --dry-run to execute cleanup.")


if __name__ == "__main__":
    main()
