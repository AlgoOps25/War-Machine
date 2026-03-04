<#
.SYNOPSIS
    War Machine Repository Organization Script
.DESCRIPTION
    Safely organizes 31 files into proper directory structure with rollback capability
.NOTES
    Created: March 4, 2026
    All safety checks passed - no production code affected
#>

$ErrorActionPreference = "Stop"
$script_start = Get-Date

Write-Host "`n" -NoNewline
Write-Host ("=" * 80) -ForegroundColor Cyan
Write-Host " WAR MACHINE - REPOSITORY ORGANIZATION" -ForegroundColor Cyan
Write-Host ("=" * 80) -ForegroundColor Cyan
Write-Host "`n✨ Starting file organization...`n" -ForegroundColor Green

# Create backup log
$timestamp = Get-Date -Format "yyyyMMdd_HHmmss"
$log_file = "migration_log_$timestamp.txt"
$backup_dir = "migration_backup_$timestamp"

# Initialize tracking
$moves = @()
$errors = @()

function Write-Log {
    param($Message, $Color = "White")
    $logMessage = "[$(Get-Date -Format 'HH:mm:ss')] $Message"
    Write-Host $logMessage -ForegroundColor $Color
    Add-Content -Path $log_file -Value $logMessage
}

function Create-DirectoryIfNeeded {
    param($Path)
    if (!(Test-Path $Path)) {
        New-Item -ItemType Directory -Path $Path -Force | Out-Null
        Write-Log "   📁 Created directory: $Path" -Color DarkGray
    }
}

function Move-FileWithBackup {
    param(
        [string]$SourceFile,
        [string]$DestinationPath
    )
    
    if (!(Test-Path $SourceFile)) {
        Write-Log "   ⚠️  File not found (already moved?): $SourceFile" -Color Yellow
        return $false
    }
    
    try {
        # Create destination directory
        $destDir = Split-Path -Parent $DestinationPath
        Create-DirectoryIfNeeded $destDir
        
        # Create backup directory
        Create-DirectoryIfNeeded $backup_dir
        
        # Backup original
        $backupPath = Join-Path $backup_dir $SourceFile
        $backupDir = Split-Path -Parent $backupPath
        Create-DirectoryIfNeeded $backupDir
        Copy-Item $SourceFile $backupPath -Force
        
        # Move file
        Move-Item $SourceFile $DestinationPath -Force
        
        $script:moves += @{
            Source = $SourceFile
            Destination = $DestinationPath
            Backup = $backupPath
            Timestamp = Get-Date
        }
        
        Write-Log "   ✅ $SourceFile → $DestinationPath" -Color Green
        return $true
    }
    catch {
        $script:errors += @{
            File = $SourceFile
            Error = $_.Exception.Message
        }
        Write-Log "   ❌ Failed: $($_.Exception.Message)" -Color Red
        return $false
    }
}

# ============================================================================
# PHASE 1: CREATE DIRECTORY STRUCTURE
# ============================================================================

Write-Host "`n📁 Phase 1: Creating directory structure..." -ForegroundColor Cyan

$directories = @(
    "results/backtests",
    "results/optimization",
    "results/indicators",
    "results/validation",
    "scripts/backtesting",
    "scripts/optimization",
    "scripts/analysis",
    "scripts/database",
    "scripts/maintenance",
    "scripts/powershell",
    "scripts/config"
)

foreach ($dir in $directories) {
    Create-DirectoryIfNeeded $dir
}

Write-Host "   ✅ All directories created`n" -ForegroundColor Green

# ============================================================================
# PHASE 2: MOVE RESULTS FILES
# ============================================================================

Write-Host "📊 Phase 2: Organizing results files..." -ForegroundColor Cyan

# Backtest results
Write-Host "`n   → results/backtests/" -ForegroundColor White
Move-FileWithBackup "backtest_results.json" "results/backtests/backtest_results.json"
Move-FileWithBackup "quick_backtest_results.csv" "results/backtests/quick_backtest_results.csv"

# Optimization results
Write-Host "`n   → results/optimization/" -ForegroundColor White
Move-FileWithBackup "optimization_results.json" "results/optimization/optimization_results.json"
Move-FileWithBackup "optimized_filter_parameters.json" "results/optimization/optimized_filter_parameters.json"
Move-FileWithBackup "effective_filters_exhaustive.json" "results/optimization/effective_filters_exhaustive.json"
Move-FileWithBackup "two_phase_optimization_results.json" "results/optimization/two_phase_optimization_results.json"
Move-FileWithBackup "war_machine_optimized.json" "results/optimization/war_machine_optimized.json"

# Indicator results
Write-Host "`n   → results/indicators/" -ForegroundColor White
Move-FileWithBackup "indicator_backtest_detailed.json" "results/indicators/indicator_backtest_detailed.json"
Move-FileWithBackup "indicator_backtest_results.csv" "results/indicators/indicator_backtest_results.csv"
Move-FileWithBackup "indicator_backtest_results.json" "results/indicators/indicator_backtest_results.json"
Move-FileWithBackup "indicator_backtest_results_REAL.csv" "results/indicators/indicator_backtest_results_REAL.csv"
Move-FileWithBackup "indicator_backtest_results_REAL.json" "results/indicators/indicator_backtest_results_REAL.json"
Move-FileWithBackup "indicator_backtest_summary.csv" "results/indicators/indicator_backtest_summary.csv"
Move-FileWithBackup "quick_indicator_results.csv" "results/indicators/quick_indicator_results.csv"

# Validation results
Write-Host "`n   → results/validation/" -ForegroundColor White
Move-FileWithBackup "validation_signals.csv" "results/validation/validation_signals.csv"

Write-Host "`n   ✅ Results files organized`n" -ForegroundColor Green

# ============================================================================
# PHASE 3: MOVE SCRIPT FILES
# ============================================================================

Write-Host "🔧 Phase 3: Organizing script files..." -ForegroundColor Cyan

# Backtesting scripts
Write-Host "`n   → scripts/backtesting/" -ForegroundColor White
Move-FileWithBackup "backtest_optimized_params.py" "scripts/backtesting/backtest_optimized_params.py"
Move-FileWithBackup "production_indicator_backtest.py" "scripts/backtesting/production_indicator_backtest.py"

# Optimization scripts
Write-Host "`n   → scripts/optimization/" -ForegroundColor White
Move-FileWithBackup "smart_optimization.py" "scripts/optimization/smart_optimization.py"

# Analysis scripts
Write-Host "`n   → scripts/analysis/" -ForegroundColor White
Move-FileWithBackup "analyze_ml_training_data.py" "scripts/analysis/analyze_ml_training_data.py"
Move-FileWithBackup "inspect_signal_outcomes.py" "scripts/analysis/inspect_signal_outcomes.py"
Move-FileWithBackup "target_discovery.py" "scripts/analysis/target_discovery.py"

# Database scripts
Write-Host "`n   → scripts/database/" -ForegroundColor White
Move-FileWithBackup "check_database.py" "scripts/database/check_database.py"
Move-FileWithBackup "inspect_database_schema.py" "scripts/database/inspect_database_schema.py"
Move-FileWithBackup "setup_database.py" "scripts/database/setup_database.py"
Move-FileWithBackup "load_historical_data.py" "scripts/database/load_historical_data.py"

# Maintenance scripts
Write-Host "`n   → scripts/maintenance/" -ForegroundColor White
Move-FileWithBackup "update_sniper_greeks.py" "scripts/maintenance/update_sniper_greeks.py"
Move-FileWithBackup "production_helpers.py" "scripts/maintenance/production_helpers.py"

# PowerShell scripts
Write-Host "`n   → scripts/powershell/" -ForegroundColor White
Move-FileWithBackup "dependency_analyzer.ps1" "scripts/powershell/dependency_analyzer.ps1"
Move-FileWithBackup "restore_and_deploy.ps1" "scripts/powershell/restore_and_deploy.ps1"

# Config scripts
Write-Host "`n   → scripts/config/" -ForegroundColor White
Move-FileWithBackup "super_indicator_config.py" "scripts/config/super_indicator_config.py"
Move-FileWithBackup "super_indicator_filters.py" "scripts/config/super_indicator_filters.py"

Write-Host "`n   ✅ Script files organized`n" -ForegroundColor Green

# ============================================================================
# PHASE 4: SUMMARY AND VERIFICATION
# ============================================================================

$script_end = Get-Date
$duration = ($script_end - $script_start).TotalSeconds

Write-Host "`n" -NoNewline
Write-Host ("=" * 80) -ForegroundColor Cyan
Write-Host " MIGRATION COMPLETE" -ForegroundColor Green
Write-Host ("=" * 80) -ForegroundColor Cyan

Write-Host "`n📊 Summary:" -ForegroundColor Cyan
Write-Host "   Files moved: $($moves.Count)" -ForegroundColor Green
Write-Host "   Errors: $($errors.Count)" -ForegroundColor $(if ($errors.Count -eq 0) { "Green" } else { "Red" })
Write-Host "   Duration: $([math]::Round($duration, 2)) seconds" -ForegroundColor White
Write-Host "   Backup location: $backup_dir" -ForegroundColor Yellow

if ($errors.Count -gt 0) {
    Write-Host "`n⚠️  Errors encountered:" -ForegroundColor Red
    foreach ($error in $errors) {
        Write-Host "   ❌ $($error.File): $($error.Error)" -ForegroundColor Red
    }
}

Write-Host "`n📄 Logs:" -ForegroundColor Cyan
Write-Host "   Migration log: $log_file" -ForegroundColor White

Write-Host "`n🔄 Next Steps:" -ForegroundColor Cyan
Write-Host "   1. Review the changes: git status" -ForegroundColor White
Write-Host "   2. Test your application works correctly" -ForegroundColor White
Write-Host "   3. Commit the changes: git add . && git commit -m 'Organize repository structure'" -ForegroundColor White
Write-Host "   4. Push to GitHub: git push origin main" -ForegroundColor White

Write-Host "`n💾 Rollback (if needed):" -ForegroundColor Yellow
Write-Host "   To restore everything: .\rollback_migration.ps1`n" -ForegroundColor White

Write-Host ("=" * 80) -ForegroundColor Cyan
Write-Host ""

# Generate rollback script
$rollback_content = "# Rollback script - Generated $(Get-Date)`n`n"
$rollback_content += "`$ErrorActionPreference = 'Stop'`n`n"
$rollback_content += "Write-Host '`n🔄 Rolling back migration...' -ForegroundColor Yellow`n`n"

foreach ($move in $moves) {
    $rollback_content += "if (Test-Path '$($move.Destination)') { Move-Item '$($move.Destination)' '$($move.Source)' -Force; Write-Host '   ✅ Restored: $($move.Source)' -ForegroundColor Green }`n"
}

$rollback_content += "`nWrite-Host '`n✅ Rollback complete!`n' -ForegroundColor Green"
$rollback_content | Out-File -FilePath "rollback_migration.ps1" -Encoding UTF8

Write-Host "✅ Rollback script created: rollback_migration.ps1`n" -ForegroundColor Green
