#!/usr/bin/env python3
"""
Phase 3I: Final Documentation & Guide Cleanup

Removes ALL unnecessary documentation files that clutter the repository:
- Completed phase guides (Phase 1-4 completion docs)
- Duplicate/redundant testing guides
- Old roadmaps and execution plans
- Temporary root-level guide files
- Archived but no longer needed documentation

KEEPS:
- docs/README.md (main documentation index)
- README.md (if exists in root - project overview)
- Current production helper guides
"""

import os
import sys
from pathlib import Path

# Files to DELETE from root directory
ROOT_FILES_TO_DELETE = [
    "HARDENING_INTEGRATION_GUIDE.md",  # Completed - code integrated
    "PHASE_3G_3H_PRODUCTION_HARDENING.md",  # Completed tonight
    "execute_phase_3f_cleanup.py",  # Old cleanup script - completed
    "execute_phase_3g_3h_hardening.py",  # Analysis script - completed
]

# Files to DELETE from docs/ directory
DOCS_FILES_TO_DELETE = [
    # Completed phase documentation (historical value = 0)
    "PHASE_1_CLEANUP_GUIDE.md",
    "PHASE_1_COMPLETE.md",
    "PHASE_1_CONSOLIDATION_COMPLETE.md",
    "PHASE_2A_IMPLEMENTATION.md",
    "PHASE_2B_IMPLEMENTATION.md",
    "PHASE_2C_IMPLEMENTATION.md",
    "PHASE_2_PLAN.md",
    "PHASE_3A_READY_TO_IMPLEMENT.md",
    "PHASE_3_OVERVIEW.md",
    "PHASE_4A_INTEGRATION.md",
    "PHASE_4_COMPLETE.md",
    "PHASE_4_DEPLOYMENT_GUIDE.md",
    "PHASE_5_ROADMAP.md",  # Future phase - not needed now
    
    # Redundant/outdated guides
    "CLEANUP_GUIDE.md",  # Replaced by scripts
    "CONSOLIDATION_ROADMAP.md",  # Old planning doc
    "EXECUTION_PLAN.md",  # Old planning doc
    "TESTING_GUIDE.md",  # Redundant with guides/
    "DEBUGGING_GUIDE.md",  # Not actively used
]

# Files to DELETE from guides/ directory
GUIDES_FILES_TO_DELETE = [
    # Completed phase guides
    "PHASE4_COMPLETE.md",  # Duplicate of docs/PHASE_4_COMPLETE.md
    "PHASE_3F_DEAD_CODE_ANALYSIS.md",  # Completed tonight
    "PHASE_3F_FINAL_CLEANUP_REPORT.md",  # Completed tonight
    
    # Redundant testing guides (can recreate if needed)
    "API_TESTING_GUIDE.md",
    "MTF_TESTING_GUIDE.md",
    "VALIDATOR_TEST_MODE_GUIDE.md",
    
    # Integration guides (code is already integrated)
    "INDICATOR_INTEGRATION_GUIDE.md",
    "INTEGRATION_GUIDE.md",
    
    # Operational guides (not needed - system auto-manages)
    "SEEDING_GUIDE.md",
    "START_HERE.md",  # Redundant with README
    "DASHBOARD_GUIDE.md",  # System is self-documenting
    "SIGNAL_ANALYTICS_README.md",  # Redundant with code comments
]


def delete_file(filepath: Path, dry_run: bool = False) -> bool:
    """Delete a file, return True if successful or file doesn't exist."""
    if not filepath.exists():
        print(f"  ⏭️  SKIP: {filepath} (doesn't exist)")
        return True
    
    if dry_run:
        size_kb = filepath.stat().st_size / 1024
        print(f"  🗑️  WOULD DELETE: {filepath} ({size_kb:.1f} KB)")
        return True
    
    try:
        size_kb = filepath.stat().st_size / 1024
        filepath.unlink()
        print(f"  ✅ DELETED: {filepath} ({size_kb:.1f} KB)")
        return True
    except Exception as e:
        print(f"  ❌ ERROR deleting {filepath}: {e}")
        return False


def cleanup_directory(base_path: Path, files_to_delete: list, dry_run: bool = False) -> tuple:
    """Clean up files in a directory. Returns (deleted_count, total_kb)."""
    deleted_count = 0
    total_kb = 0
    
    for filename in files_to_delete:
        filepath = base_path / filename
        if filepath.exists():
            total_kb += filepath.stat().st_size / 1024
        
        if delete_file(filepath, dry_run):
            if filepath.exists() or not dry_run:  # Count if exists or not dry run
                deleted_count += 1
    
    return deleted_count, total_kb


def main():
    print("""\n╔═══════════════════════════════════════════════════════════════╗
║  PHASE 3I: FINAL DOCUMENTATION & GUIDE CLEANUP               ║
║  Removing all obsolete guides and documentation              ║
╚═══════════════════════════════════════════════════════════════╝\n""")
    
    # Determine if this is a dry run
    dry_run = "--dry-run" in sys.argv or "-n" in sys.argv
    
    if dry_run:
        print("🔍 DRY RUN MODE - No files will be deleted\n")
    else:
        print("⚠️  LIVE MODE - Files will be permanently deleted\n")
        response = input("Continue? (yes/no): ").strip().lower()
        if response != "yes":
            print("\n❌ Aborted by user.\n")
            return 1
    
    repo_root = Path.cwd()
    total_deleted = 0
    total_kb_freed = 0
    
    # Clean root directory
    print("\n" + "="*70)
    print("ROOT DIRECTORY CLEANUP")
    print("="*70)
    deleted, kb = cleanup_directory(repo_root, ROOT_FILES_TO_DELETE, dry_run)
    total_deleted += deleted
    total_kb_freed += kb
    
    # Clean docs/ directory
    print("\n" + "="*70)
    print("DOCS/ DIRECTORY CLEANUP")
    print("="*70)
    docs_path = repo_root / "docs"
    if docs_path.exists():
        deleted, kb = cleanup_directory(docs_path, DOCS_FILES_TO_DELETE, dry_run)
        total_deleted += deleted
        total_kb_freed += kb
    else:
        print("  ⏭️  SKIP: docs/ directory doesn't exist")
    
    # Clean guides/ directory
    print("\n" + "="*70)
    print("GUIDES/ DIRECTORY CLEANUP")
    print("="*70)
    guides_path = repo_root / "guides"
    if guides_path.exists():
        deleted, kb = cleanup_directory(guides_path, GUIDES_FILES_TO_DELETE, dry_run)
        total_deleted += deleted
        total_kb_freed += kb
        
        # Check if guides/ is now empty and delete it
        remaining = list(guides_path.glob("*"))
        if not remaining:
            if dry_run:
                print(f"\n  🗑️  WOULD DELETE: Empty directory {guides_path}")
            else:
                guides_path.rmdir()
                print(f"\n  ✅ DELETED: Empty directory {guides_path}")
    else:
        print("  ⏭️  SKIP: guides/ directory doesn't exist")
    
    # Summary
    print("\n" + "="*70)
    print("CLEANUP SUMMARY")
    print("="*70)
    print(f"Files {'would be ' if dry_run else ''}deleted: {total_deleted}")
    print(f"Space {'would be ' if dry_run else ''}freed: {total_kb_freed:.1f} KB ({total_kb_freed/1024:.2f} MB)")
    
    if dry_run:
        print("\n💡 Run without --dry-run to execute cleanup")
    else:
        print("\n✅ Cleanup complete!")
        print("\n📝 Next steps:")
        print("   1. Review the changes with: git status")
        print("   2. Commit: git add -A && git commit -m 'Phase 3I: Purged obsolete documentation'")
        print("   3. Push: git push origin main")
    
    print("\n" + "="*70 + "\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
