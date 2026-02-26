#!/usr/bin/env python3
"""
WAR MACHINE - SAFE REPOSITORY CLEANUP
======================================

This script performs a SAFE cleanup based on actual repository audit.
It only moves files that won't conflict with existing structure.

PHASE 1: Safe Moves (No Import Breakage)
  ✅ Move docs from root → docs/
  ✅ Move test files from root → tests/
  ✅ Move backup files from root → archive/backups/
  ✅ Move scripts from root → scripts/
  ✅ Move migrations from root → migrations/

PHASE 2 (NOT IMPLEMENTED - requires import analysis):
  ⚠️ Moving Python modules from root → src/ subdirs
  ⚠️ This requires checking and updating imports first!

Usage:
  python cleanup_repo_safe.py --dry-run    # Preview changes
  python cleanup_repo_safe.py --execute    # Execute cleanup
"""

import os
import shutil
import argparse
from pathlib import Path
from datetime import datetime

# PHASE 1: Safe file moves (no import conflicts)
SAFE_MOVES = {
    'docs/history': [
        'DEPLOYMENT_READY.md',
        'FIXES_FEB25_1030AM.md',
        'Fixes.txt',
        'INTEGRATION_COMPLETE.md',
        'INTEGRATION_INSTRUCTIONS.md',
        'INTEGRATION_NOTES.md',
        'INTEGRATION_PATCH_MTF_PRIORITY.md',
        'PHASE_4_INTEGRATION_GUIDE.md',
    ],
    
    'docs/features': [
        'README_REGIME_FILTER.md',
        'REGIME_FILTER_SUMMARY.md',
        'VPVR_DEPLOYED.md',
        'VPVR_INTEGRATION_GUIDE.md',
    ],
    
    'docs': [
        'TESTING_GUIDE.md',
        'CLEANUP_GUIDE.md',
    ],
    
    'scripts': [
        'deploy.ps1',
        'integrate_regime_filter.py',
        'migrate_files.py',
        'apply_schema_migration.py',
        'apply_candle_cache_migration.py',
        'scanner_optimizer.py',
        'cleanup_repo.py',  # Move old cleanup script
    ],
    
    'tests': [
        'test_full_pipeline.py',
        'test_mtf.py',
        'test_vix.py',
        'db_diagnostic.py',
        'diagnostics.py',
    ],
    
    'migrations': [
        'fix_positions_schema.sql',
    ],
    
    'archive/backups': [
        'regime_filter.py.backup',
        'regime_filter_original.py',
        'signal_validator.py.backup_20260225_162510',
        'signal_validator.py.backup_20260225_162904',
    ],
}

# Files to keep in root
KEEP_IN_ROOT = [
    'scanner.py',
    'sniper.py',
    'requirements.txt',
    'railway.toml',
    'nixpacks.toml',
    '.gitignore',
    'README.md',
]

class SafeRepositoryCleanup:
    def __init__(self, dry_run=True):
        self.dry_run = dry_run
        self.root = Path('.')
        self.moves = []
        self.creates = []
        self.issues = []
        self.skipped = []
        
    def log(self, message, level='INFO'):
        """Log message with color coding."""
        colors = {
            'INFO': '\033[94m',    # Blue
            'SUCCESS': '\033[92m', # Green
            'WARNING': '\033[93m', # Yellow
            'ERROR': '\033[91m',   # Red
            'RESET': '\033[0m'
        }
        color = colors.get(level, colors['INFO'])
        reset = colors['RESET']
        prefix = {
            'INFO': '[INFO]',
            'SUCCESS': '[✓]',
            'WARNING': '[!]',
            'ERROR': '[✗]'
        }.get(level, '[INFO]')
        
        print(f"{color}{prefix}{reset} {message}")
    
    def create_directory(self, dir_path):
        """Create directory if it doesn't exist."""
        if self.dry_run:
            if not dir_path.exists():
                self.creates.append(str(dir_path))
                self.log(f"Would create: {dir_path}", 'INFO')
        else:
            if not dir_path.exists():
                dir_path.mkdir(parents=True, exist_ok=True)
                self.log(f"Created: {dir_path}", 'SUCCESS')
    
    def move_file(self, src, dest):
        """Move file from src to dest."""
        src_path = Path(src)
        dest_path = Path(dest)
        
        if not src_path.exists():
            self.log(f"Source not found (already moved?): {src}", 'WARNING')
            self.skipped.append(f"Not found: {src}")
            return False
        
        # Check if destination already exists
        if dest_path.exists():
            self.log(f"Destination exists, skipping: {dest}", 'WARNING')
            self.skipped.append(f"Already exists: {dest}")
            return False
        
        if self.dry_run:
            self.moves.append((str(src_path), str(dest_path)))
            self.log(f"Would move: {src_path} → {dest_path}", 'INFO')
        else:
            try:
                # Create parent directory if needed
                dest_path.parent.mkdir(parents=True, exist_ok=True)
                
                # Move file
                shutil.move(str(src_path), str(dest_path))
                self.log(f"Moved: {src_path} → {dest_path}", 'SUCCESS')
                return True
            except Exception as e:
                self.log(f"Error moving {src}: {e}", 'ERROR')
                self.issues.append(f"Error: {src} - {e}")
                return False
        
        return True
    
    def organize_files(self):
        """Organize files according to SAFE_MOVES."""
        self.log("\n" + "="*80)
        self.log("PHASE 1: SAFE FILE ORGANIZATION")
        self.log("="*80 + "\n")
        
        self.log("This will move docs, tests, scripts, and backups ONLY.")
        self.log("Python modules stay in root to avoid breaking imports.\n")
        
        for target_dir, files in SAFE_MOVES.items():
            self.log(f"\nProcessing: {target_dir}/", 'INFO')
            self.log("-" * 60)
            
            # Create target directory
            target_path = self.root / target_dir
            self.create_directory(target_path)
            
            # Move each file
            for filename in files:
                src = self.root / filename
                dest = target_path / filename
                self.move_file(src, dest)
    
    def print_python_modules_report(self):
        """Print report of Python modules still in root."""
        self.log("\n" + "="*80)
        self.log("PYTHON MODULES REMAINING IN ROOT")
        self.log("="*80 + "\n")
        
        root_python_files = []
        for f in self.root.glob('*.py'):
            if f.name not in ['cleanup_repo.py', 'cleanup_repo_safe.py'] and f.name not in KEEP_IN_ROOT:
                root_python_files.append(f.name)
        
        if root_python_files:
            self.log(f"Found {len(root_python_files)} Python modules still in root:", 'WARNING')
            self.log("")
            
            # Categorize them
            categories = {
                'Core System': ['scanner.py', 'sniper.py', 'signal_generator.py', 'signal_validator.py', 
                               'position_manager.py', 'data_manager.py'],
                'Engines': ['breakout_detector.py', 'daily_bias_engine.py', 'regime_filter.py', 
                           'vpvr_calculator.py', 'bos_fvg_engine.py', 'gex_engine.py'],
                'Data': ['candle_cache.py', 'cache_manager.py', 'db_connection.py', 
                        'options_data_manager.py', 'mtf_data_manager.py'],
                'Screeners': ['dynamic_screener.py', 'momentum_screener_optimized.py', 
                             'premarket_scanner_pro.py', 'watchlist_funnel.py'],
                'Analytics': ['signal_analytics.py', 'performance_monitor.py', 'eod_digest.py', 
                             'pnl_digest.py', 'performance_alerts.py'],
                'Optimizers': ['historical_tuner.py', 'parameter_optimizer.py', 'adaptive_historical_tuner.py'],
                'Other': [],
            }
            
            categorized = set()
            for cat, files in categories.items():
                found = [f for f in root_python_files if f in files]
                if found:
                    self.log(f"  {cat}: {len(found)} files", 'INFO')
                    categorized.update(found)
            
            uncategorized = set(root_python_files) - categorized
            if uncategorized:
                categories['Other'] = list(uncategorized)
                self.log(f"  Other: {len(uncategorized)} files", 'INFO')
            
            self.log("\n" + "-" * 80)
            self.log("⚠️  These files were NOT moved to avoid breaking imports.", 'WARNING')
            self.log("To move them safely:", 'INFO')
            self.log("  1. Check scanner.py and sniper.py imports", 'INFO')
            self.log("  2. Move files one category at a time", 'INFO')
            self.log("  3. Test after each move: python test_full_pipeline.py", 'INFO')
        else:
            self.log("✓ All Python modules are organized!", 'SUCCESS')
    
    def print_summary(self):
        """Print summary of cleanup operations."""
        self.log("\n" + "="*80)
        self.log("CLEANUP SUMMARY")
        self.log("="*80 + "\n")
        
        if self.dry_run:
            self.log("DRY RUN MODE - No files were actually moved", 'WARNING')
            self.log("")
        
        self.log(f"Directories to create: {len(self.creates)}", 'INFO')
        self.log(f"Files to move: {len(self.moves)}", 'INFO')
        self.log(f"Files skipped: {len(self.skipped)}", 'WARNING' if self.skipped else 'INFO')
        self.log(f"Errors: {len(self.issues)}", 'ERROR' if self.issues else 'INFO')
        
        if self.skipped:
            self.log("\nSkipped files:", 'WARNING')
            for item in self.skipped[:5]:
                self.log(f"  - {item}", 'WARNING')
            if len(self.skipped) > 5:
                self.log(f"  ... and {len(self.skipped) - 5} more", 'WARNING')
        
        if self.issues:
            self.log("\nIssues:", 'ERROR')
            for issue in self.issues:
                self.log(f"  - {issue}", 'ERROR')
        
        if self.dry_run:
            self.log("\n" + "="*80)
            self.log("To execute cleanup, run:", 'INFO')
            self.log("  python cleanup_repo_safe.py --execute", 'SUCCESS')
            self.log("="*80 + "\n")
        else:
            self.log("\n" + "="*80)
            self.log("✓ PHASE 1 CLEANUP COMPLETE!", 'SUCCESS')
            self.log("="*80 + "\n")
            self.log("Next steps:", 'INFO')
            self.log("  1. Review changes: git status", 'INFO')
            self.log("  2. Update .gitignore if needed", 'INFO')
            self.log("  3. Commit: git add . && git commit -m 'Reorganize docs, tests, scripts'", 'INFO')
            self.log("  4. Test system: python tests/test_full_pipeline.py", 'INFO')
            self.log("  5. Push: git push origin main", 'INFO')
            self.log("")
    
    def run(self):
        """Execute safe cleanup process."""
        self.log("\n" + "#"*80)
        self.log("#" + " "*78 + "#")
        self.log("#" + " "*18 + "WAR MACHINE SAFE REPOSITORY CLEANUP" + " "*25 + "#")
        self.log("#" + " "*78 + "#")
        self.log("#"*80 + "\n")
        
        if self.dry_run:
            self.log("Running in DRY RUN mode - no files will be moved\n", 'WARNING')
        else:
            self.log("Running in EXECUTE mode - files WILL be moved\n", 'WARNING')
            self.log("This will move docs, tests, scripts, and backups.", 'INFO')
            self.log("Python modules will stay in root (safe for imports).\n", 'INFO')
            response = input("Continue? (yes/no): ")
            if response.lower() != 'yes':
                self.log("Cleanup cancelled by user", 'WARNING')
                return
            print()
        
        # Execute cleanup
        self.organize_files()
        self.print_python_modules_report()
        self.print_summary()

def main():
    parser = argparse.ArgumentParser(
        description='War Machine Safe Repository Cleanup',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog='''
This script performs PHASE 1 cleanup only (safe moves):
  • Moves documentation to docs/
  • Moves tests to tests/
  • Moves scripts to scripts/
  • Moves backups to archive/
  • Keeps Python modules in root (avoids breaking imports)

Examples:
  python cleanup_repo_safe.py --dry-run    # Preview changes
  python cleanup_repo_safe.py --execute    # Execute cleanup
'''
    )
    
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument('--dry-run', action='store_true',
                      help='Preview changes without executing')
    group.add_argument('--execute', action='store_true',
                      help='Execute safe cleanup (moves docs/tests/scripts only)')
    
    args = parser.parse_args()
    
    cleanup = SafeRepositoryCleanup(dry_run=args.dry_run)
    cleanup.run()

if __name__ == '__main__':
    main()
