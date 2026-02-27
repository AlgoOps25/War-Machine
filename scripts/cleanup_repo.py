#!/usr/bin/env python3
"""
WAR MACHINE - REPOSITORY CLEANUP AUTOMATION
============================================

This script organizes the repository into a clean structure:
  - Moves core files to src/
  - Organizes docs into docs/
  - Archives old/backup files
  - Updates .gitignore

Usage:
  python cleanup_repo.py --dry-run    # Preview changes
  python cleanup_repo.py --execute    # Execute cleanup

WARNING: This will move many files. Review dry-run output first!
"""

import os
import shutil
import argparse
from pathlib import Path
from datetime import datetime

# File organization rules
FILE_STRUCTURE = {
    'src/core': [
        'scanner.py',
        'signal_generator.py',
        'signal_validator.py',
        'position_manager.py',
        'data_manager.py',
        'sniper.py',
    ],
    
    'src/engines': [
        'breakout_detector.py',
        'daily_bias_engine.py',
        'regime_filter.py',
        'vpvr_calculator.py',
        'bos_fvg_engine.py',
        'mtf_fvg_engine.py',
        'mtf_integration.py',
        'gex_engine.py',
    ],
    
    'src/indicators': [
        'technical_indicators.py',
        'cfw6_confirmation.py',
        'mtf_convergence.py',
        'mtf_fvg_priority.py',
    ],
    
    'src/filters': [
        'options_filter.py',
        'fundamentals_filter.py',
        'news_filter.py',
        'insider_filter.py',
        'correlation_check.py',
    ],
    
    'src/analytics': [
        'signal_analytics.py',
        'performance_monitor.py',
        'performance_alerts.py',
        'eod_digest.py',
        'pnl_digest.py',
    ],
    
    'src/data': [
        'candle_cache.py',
        'cache_manager.py',
        'mtf_data_manager.py',
        'options_data_manager.py',
        'db_connection.py',
    ],
    
    'src/screeners': [
        'dynamic_screener.py',
        'momentum_screener_optimized.py',
        'premarket_scanner_pro.py',
        'premarket_scanner_integration.py',
        'watchlist_funnel.py',
        'uoa_scanner.py',
    ],
    
    'src/optimizers': [
        'historical_tuner.py',
        'adaptive_historical_tuner.py',
        'remote_historical_tuner.py',
        'parameter_optimizer.py',
        'dynamic_thresholds.py',
        'scanner_optimizer.py',
    ],
    
    'src/ml': [
        'ai_learning.py',
        'learning_policy.py',
    ],
    
    'src/utils': [
        'exchange_hours.py',
        'trade_calculator.py',
        'discord_helpers.py',
        'config.py',
        'timeframe_manager.py',
        'volume_analyzer.py',
        'iv_tracker.py',
        'hourly_gate.py',
    ],
    
    'src/infrastructure': [
        'ws_feed.py',
        'monitoring_dashboard.py',
        'data_manager_cache_integration.py',
    ],
    
    'docs': [
        'TESTING_GUIDE.md',
        'REGIME_FILTER_SUMMARY.md',
        'README_REGIME_FILTER.md',
    ],
    
    'docs/deployment': [
        'DEPLOYMENT_READY.md',
        'INTEGRATION_COMPLETE.md',
        'INTEGRATION_INSTRUCTIONS.md',
        'INTEGRATION_NOTES.md',
        'INTEGRATION_PATCH_MTF_PRIORITY.md',
        'PHASE_4_INTEGRATION_GUIDE.md',
        'VPVR_DEPLOYED.md',
        'VPVR_INTEGRATION_GUIDE.md',
    ],
    
    'docs/fixes': [
        'FIXES_FEB25_1030AM.md',
        'Fixes.txt',
    ],
    
    'scripts': [
        'test_full_pipeline.py',
        'integrate_regime_filter.py',
        'deploy.ps1',
        'migrate_files.py',
        'apply_schema_migration.py',
        'apply_candle_cache_migration.py',
    ],
    
    'tests': [
        'test_mtf.py',
        'test_vix.py',
        'db_diagnostic.py',
        'diagnostics.py',
    ],
    
    'archive/backups': [
        'regime_filter.py.backup',
        'regime_filter_original.py',
        'signal_validator.py.backup_20260225_162510',
        'signal_validator.py.backup_20260225_162904',
    ],
    
    'migrations': [
        'fix_positions_schema.sql',
    ],
}

# Files to keep in root
ROOT_FILES = [
    '.gitignore',
    'requirements.txt',
    'railway.toml',
    'nixpacks.toml',
    'README.md',
]

class RepositoryCleanup:
    def __init__(self, dry_run=True):
        self.dry_run = dry_run
        self.root = Path('.')
        self.moves = []
        self.creates = []
        self.issues = []
        
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
            'SUCCESS': '[OK]',
            'WARNING': '[WARN]',
            'ERROR': '[ERROR]'
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
            self.log(f"Source not found: {src}", 'WARNING')
            self.issues.append(f"Missing: {src}")
            return False
        
        if self.dry_run:
            self.moves.append((str(src_path), str(dest_path)))
            self.log(f"Would move: {src_path} -> {dest_path}", 'INFO')
        else:
            try:
                # Create parent directory if needed
                dest_path.parent.mkdir(parents=True, exist_ok=True)
                
                # Move file
                shutil.move(str(src_path), str(dest_path))
                self.log(f"Moved: {src_path} -> {dest_path}", 'SUCCESS')
                return True
            except Exception as e:
                self.log(f"Error moving {src}: {e}", 'ERROR')
                self.issues.append(f"Error: {src} - {e}")
                return False
        
        return True
    
    def organize_files(self):
        """Organize files according to FILE_STRUCTURE."""
        self.log("\n" + "="*80)
        self.log("ORGANIZING FILES")
        self.log("="*80 + "\n")
        
        for target_dir, files in FILE_STRUCTURE.items():
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
    
    def create_readme(self):
        """Create new README.md in root."""
        readme_content = '''# War Machine - CFW6 Trading System

## 🎯 Overview

**War Machine** is a sophisticated algorithmic trading system that detects CFW6 (Consolidation Followed by Wide-Range Breakout on 6+ Volume) patterns and validates signals through a multi-layer confirmation system.

### Key Features

- **CFW6 Pattern Detection**: Identifies high-probability breakout setups
- **10-Layer Validation**: Multi-indicator confirmation system
- **Regime Filtering**: Adapts to market conditions (TRENDING/CHOPPY/VOLATILE)
- **Daily Bias Engine**: ICT-based top-down analysis
- **VPVR Integration**: Volume profile entry scoring
- **Options Intelligence**: Premium flow analysis and Greeks
- **Performance Tracking**: Real-time analytics and PnL monitoring

---

## 📁 Repository Structure

```
War-Machine/
├── src/                   # Core application code
│   ├── core/              # Main system components
│   ├── engines/           # Detection and analysis engines
│   ├── indicators/        # Technical indicators
│   ├── filters/           # Signal filtering layers
│   ├── analytics/         # Performance tracking
│   ├── data/              # Data management
│   ├── screeners/         # Market scanners
│   ├── optimizers/        # Parameter tuning
│   ├── ml/                # Machine learning
│   └── utils/             # Utility functions
│
├── docs/                  # Documentation
│   ├── deployment/        # Deployment guides
│   └── fixes/             # Historical fixes
│
├── scripts/               # Utility scripts
├── tests/                 # Test files
├── migrations/            # Database migrations
└── archive/               # Deprecated code
```

---

## 🚀 Quick Start

### Prerequisites

```bash
python 3.11+
PostgreSQL (Railway)
EODHD API key
Discord webhook
```

### Installation

```bash
# Clone repository
git clone https://github.com/AlgoOps25/War-Machine.git
cd War-Machine

# Install dependencies
pip install -r requirements.txt

# Set environment variables
export EODHD_API_KEY="your_key"
export DISCORD_WEBHOOK="your_webhook"
export DATABASE_URL="your_postgres_url"
```

### Run Tests

```bash
# Full pipeline test
python scripts/test_full_pipeline.py

# Expected output: 8/8 tests passed
```

### Deploy

```bash
# PowerShell
.\scripts\deploy.ps1

# Bash
git add . && git commit -m "Deploy" && git push origin main
```

---

## 📊 System Architecture

### Signal Generation Pipeline

```
┌──────────────────────────┐
│   SCANNER (scanner.py)    │
│  - Builds watchlist       │
│  - Manages scan cycles    │
└─────────┬────────────────┘
         │
         ▼
┌─────────┴──────────────────────────────────────┐
│   SIGNAL GENERATOR (signal_generator.py)   │
│   - Detects CFW6 breakouts                 │
│   - Manages cooldown periods               │
└─────────┬──────────────────────────────────────┘
         │
         ▼
┌─────────┴───────────────────────────┐
│   SIGNAL VALIDATOR (signal_validator.py) │
│   - 10 validation checks                  │
│   - Confidence scoring                    │
└─────────┬───────────────────────────┘
         │
         ▼
    📢 Discord Alert
```

### Validation Layers

1. **Layer 0**: Daily Bias (ICT) - Counter-trend penalty
2. **Layer 0A**: Regime Filter - Market condition check
3. **Layer 1**: Time-of-Day - Quality windows
4. **Layer 2**: EMA Stack - Trend alignment
5. **Layer 3**: RSI Divergence - Reversal warnings
6. **Layer 4**: ADX - Trend strength
7. **Layer 5**: Volume - Institutional confirmation
8. **Layer 6**: DMI - Direction alignment
9. **Layer 7**: CCI - Momentum
10. **Layer 8**: Bollinger Bands - Volatility
11. **Layer 9**: VPVR - Volume profile

---

## 📚 Documentation

- **[Testing Guide](docs/TESTING_GUIDE.md)** - Full system testing
- **[Regime Filter](docs/README_REGIME_FILTER.md)** - Market condition filtering
- **[Deployment](docs/deployment/DEPLOYMENT_READY.md)** - Production deployment

---

## 📈 Performance Metrics

**Target Performance:**
- Win Rate: 60-70%
- Risk/Reward: 1:2+
- Max Drawdown: <15%
- Daily Signals: 30-50

**Regime Impact:**
- TRENDING: 80-90% signal pass rate (+5% boost)
- CHOPPY: 20-30% signal pass rate (-30% penalty)
- VOLATILE: 10-20% signal pass rate (-30% penalty)

---

## ⚙️ Configuration

Key settings in `src/utils/config.py`:

```python
# Signal Generation
LOOKBACK_BARS = 12
VOLUME_MULTIPLIER = 2.0
COOLDOWN_MINUTES = 15
MIN_CONFIDENCE = 60

# Regime Filter
VIX_THRESHOLD = 30.0
ADX_THRESHOLD = 25.0

# Risk Management
RISK_PER_TRADE = 0.02  # 2%
MAX_POSITION_SIZE = 0.10  # 10%
```

---

## 🐛 Troubleshooting

Common issues and solutions:

### All signals being filtered
```bash
python -c "from src.engines.regime_filter import regime_filter; regime_filter.print_regime_summary()"
```

### VIX data not available
```bash
echo $EODHD_API_KEY
python -c "from src.core.data_manager import data_manager; print(data_manager.get_vix_level())"
```

### Database connection issues
```bash
python tests/db_diagnostic.py
```

---

## 🚀 Deployment

**Railway Auto-Deploy:**
1. Push to `main` branch
2. Railway detects changes
3. Builds and deploys automatically
4. Monitor logs for initialization messages

**Look for:**
```
[VALIDATOR] ✅ Regime filter enabled (TRENDING/CHOPPY/VOLATILE)
[SCANNER] ✅ Options intelligence layer enabled
[POSITION] ✅ Phase 4 trade tracking enabled
```

---

## 📄 License

Proprietary - All Rights Reserved

## 🚀 Version

**Phase 2C** - Regime Filter Integration Complete (Feb 2026)

---

**Built with ❤️ by AlgoOps**
'''
        
        if self.dry_run:
            self.log("\nWould create new README.md in root", 'INFO')
        else:
            readme_path = self.root / 'README.md'
            if readme_path.exists():
                # Backup existing README
                backup_path = self.root / 'archive' / 'README.md.old'
                backup_path.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(readme_path, backup_path)
                self.log(f"Backed up existing README to: {backup_path}", 'INFO')
            
            with open(readme_path, 'w', encoding='utf-8') as f:
                f.write(readme_content)
            self.log("Created new README.md", 'SUCCESS')
    
    def update_gitignore(self):
        """Update .gitignore to prevent backups from being committed."""
        gitignore_additions = '''

# === WAR MACHINE SPECIFIC ===
# Backup files
*.backup
*.backup_*
*.old
*.bak

# Local databases
*.db
*.db-journal
market_memory.db*
trades.db*

# Python cache
__pycache__/
*.py[cod]
*$py.class
*.so
.Python
build/
develop-eggs/
dist/
downloads/
eggs/
.eggs/
lib/
lib64/
parts/
sdist/
var/
wheels/
*.egg-info/
.installed.cfg
*.egg

# Virtual environments
venv/
ENV/
env/
.venv

# IDE
.vscode/
.idea/
*.swp
*.swo
*~

# OS
.DS_Store
Thumbs.db

# Logs
*.log
logs/

# Environment variables
.env
.env.local

# Testing
.pytest_cache/
.coverage
htmlcov/

# Temporary files
*.tmp
temp/
tmp/
'''
        
        if self.dry_run:
            self.log("\nWould update .gitignore with backup file exclusions", 'INFO')
        else:
            gitignore_path = self.root / '.gitignore'
            with open(gitignore_path, 'a', encoding='utf-8') as f:
                f.write(gitignore_additions)
            self.log("Updated .gitignore", 'SUCCESS')
    
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
        self.log(f"Issues found: {len(self.issues)}", 'WARNING' if self.issues else 'INFO')
        
        if self.issues:
            self.log("\nIssues:", 'WARNING')
            for issue in self.issues[:10]:  # Show first 10
                self.log(f"  - {issue}", 'WARNING')
            if len(self.issues) > 10:
                self.log(f"  ... and {len(self.issues) - 10} more", 'WARNING')
        
        if self.dry_run:
            self.log("\n" + "="*80)
            self.log("To execute cleanup, run:", 'INFO')
            self.log("  python cleanup_repo.py --execute", 'SUCCESS')
            self.log("="*80 + "\n")
        else:
            self.log("\n" + "="*80)
            self.log("✅ CLEANUP COMPLETE!", 'SUCCESS')
            self.log("="*80 + "\n")
            self.log("Next steps:", 'INFO')
            self.log("  1. Review changes: git status", 'INFO')
            self.log("  2. Test system: python scripts/test_full_pipeline.py", 'INFO')
            self.log("  3. Commit changes: git add . && git commit -m 'Reorganize repository structure'", 'INFO')
            self.log("  4. Push to GitHub: git push origin main", 'INFO')
            self.log("")
    
    def run(self):
        """Execute full cleanup process."""
        self.log("\n" + "#"*80)
        self.log("#" + " "*78 + "#")
        self.log("#" + " "*20 + "WAR MACHINE REPOSITORY CLEANUP" + " "*28 + "#")
        self.log("#" + " "*78 + "#")
        self.log("#"*80 + "\n")
        
        if self.dry_run:
            self.log("Running in DRY RUN mode - no files will be moved\n", 'WARNING')
        else:
            self.log("Running in EXECUTE mode - files will be moved\n", 'WARNING')
            response = input("Are you sure you want to proceed? (yes/no): ")
            if response.lower() != 'yes':
                self.log("Cleanup cancelled by user", 'WARNING')
                return
            print()
        
        # Execute cleanup steps
        self.organize_files()
        self.create_readme()
        self.update_gitignore()
        
        # Print summary
        self.print_summary()

def main():
    parser = argparse.ArgumentParser(
        description='War Machine Repository Cleanup Automation',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog='''
Examples:
  python cleanup_repo.py --dry-run    # Preview changes
  python cleanup_repo.py --execute    # Execute cleanup
'''
    )
    
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument('--dry-run', action='store_true',
                      help='Preview changes without executing')
    group.add_argument('--execute', action='store_true',
                      help='Execute cleanup (moves files)')
    
    args = parser.parse_args()
    
    cleanup = RepositoryCleanup(dry_run=args.dry_run)
    cleanup.run()

if __name__ == '__main__':
    main()
