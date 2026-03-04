$ErrorActionPreference = "Stop"
$timestamp = Get-Date -Format "yyyyMMdd_HHmmss"
$log_file = "migration_log_$timestamp.txt"
$backup_dir = "migration_backup_$timestamp"
$script:moves = @()
$script:errors = @()

Write-Host ""
Write-Host "================================================================================" -ForegroundColor Cyan
Write-Host " WAR MACHINE - REPOSITORY ORGANIZATION" -ForegroundColor Cyan
Write-Host "================================================================================" -ForegroundColor Cyan
Write-Host ""

function Write-Log($Message, $Color = "White") {
    $logMessage = "[$(Get-Date -Format 'HH:mm:ss')] $Message"
    Write-Host $logMessage -ForegroundColor $Color
    Add-Content -Path $log_file -Value $logMessage
}

function Create-Dir($Path) {
    if (!(Test-Path $Path)) {
        New-Item -ItemType Directory -Path $Path -Force | Out-Null
        Write-Log "   Created: $Path" -Color DarkGray
    }
}

function Move-File($Source, $Dest) {
    if (!(Test-Path $Source)) {
        Write-Log "   Skipped (not found): $Source" -Color Yellow
        return
    }
    
    try {
        $destDir = Split-Path -Parent $Dest
        Create-Dir $destDir
        Create-Dir $backup_dir
        
        $backupPath = Join-Path $backup_dir $Source
        $backupDir = Split-Path -Parent $backupPath
        Create-Dir $backupDir
        Copy-Item $Source $backupPath -Force
        
        Move-Item $Source $Dest -Force
        
        $script:moves += @{
            Source = $Source
            Destination = $Dest
            Backup = $backupPath
        }
        
        Write-Log "   OK: $Source -> $Dest" -Color Green
    }
    catch {
        $script:errors += @{File = $Source; Error = $_.Exception.Message}
        Write-Log "   FAILED: $Source - $($_.Exception.Message)" -Color Red
    }
}

Write-Host "Phase 1: Creating directories..." -ForegroundColor Cyan
Create-Dir "results/backtests"
Create-Dir "results/optimization"
Create-Dir "results/indicators"
Create-Dir "results/validation"
Create-Dir "scripts/backtesting"
Create-Dir "scripts/optimization"
Create-Dir "scripts/analysis"
Create-Dir "scripts/database"
Create-Dir "scripts/maintenance"
Create-Dir "scripts/powershell"
Create-Dir "scripts/config"
Write-Host "   Done!" -ForegroundColor Green
Write-Host ""

Write-Host "Phase 2: Moving results files..." -ForegroundColor Cyan
Write-Host "   -> results/backtests/" -ForegroundColor White
Move-File "backtest_results.json" "results/backtests/backtest_results.json"
Move-File "quick_backtest_results.csv" "results/backtests/quick_backtest_results.csv"

Write-Host "   -> results/optimization/" -ForegroundColor White
Move-File "optimization_results.json" "results/optimization/optimization_results.json"
Move-File "optimized_filter_parameters.json" "results/optimization/optimized_filter_parameters.json"
Move-File "effective_filters_exhaustive.json" "results/optimization/effective_filters_exhaustive.json"
Move-File "two_phase_optimization_results.json" "results/optimization/two_phase_optimization_results.json"
Move-File "war_machine_optimized.json" "results/optimization/war_machine_optimized.json"

Write-Host "   -> results/indicators/" -ForegroundColor White
Move-File "indicator_backtest_detailed.json" "results/indicators/indicator_backtest_detailed.json"
Move-File "indicator_backtest_results.csv" "results/indicators/indicator_backtest_results.csv"
Move-File "indicator_backtest_results.json" "results/indicators/indicator_backtest_results.json"
Move-File "indicator_backtest_results_REAL.csv" "results/indicators/indicator_backtest_results_REAL.csv"
Move-File "indicator_backtest_results_REAL.json" "results/indicators/indicator_backtest_results_REAL.json"
Move-File "indicator_backtest_summary.csv" "results/indicators/indicator_backtest_summary.csv"
Move-File "quick_indicator_results.csv" "results/indicators/quick_indicator_results.csv"

Write-Host "   -> results/validation/" -ForegroundColor White
Move-File "validation_signals.csv" "results/validation/validation_signals.csv"
Write-Host ""

Write-Host "Phase 3: Moving script files..." -ForegroundColor Cyan
Write-Host "   -> scripts/backtesting/" -ForegroundColor White
Move-File "backtest_optimized_params.py" "scripts/backtesting/backtest_optimized_params.py"
Move-File "production_indicator_backtest.py" "scripts/backtesting/production_indicator_backtest.py"

Write-Host "   -> scripts/optimization/" -ForegroundColor White
Move-File "smart_optimization.py" "scripts/optimization/smart_optimization.py"

Write-Host "   -> scripts/analysis/" -ForegroundColor White
Move-File "analyze_ml_training_data.py" "scripts/analysis/analyze_ml_training_data.py"
Move-File "inspect_signal_outcomes.py" "scripts/analysis/inspect_signal_outcomes.py"
Move-File "target_discovery.py" "scripts/analysis/target_discovery.py"

Write-Host "   -> scripts/database/" -ForegroundColor White
Move-File "check_database.py" "scripts/database/check_database.py"
Move-File "inspect_database_schema.py" "scripts/database/inspect_database_schema.py"
Move-File "setup_database.py" "scripts/database/setup_database.py"
Move-File "load_historical_data.py" "scripts/database/load_historical_data.py"

Write-Host "   -> scripts/maintenance/" -ForegroundColor White
Move-File "update_sniper_greeks.py" "scripts/maintenance/update_sniper_greeks.py"
Move-File "production_helpers.py" "scripts/maintenance/production_helpers.py"

Write-Host "   -> scripts/powershell/" -ForegroundColor White
Move-File "dependency_analyzer.ps1" "scripts/powershell/dependency_analyzer.ps1"
Move-File "restore_and_deploy.ps1" "scripts/powershell/restore_and_deploy.ps1"

Write-Host "   -> scripts/config/" -ForegroundColor White
Move-File "super_indicator_config.py" "scripts/config/super_indicator_config.py"
Move-File "super_indicator_filters.py" "scripts/config/super_indicator_filters.py"
Write-Host ""

Write-Host "================================================================================" -ForegroundColor Cyan
Write-Host " MIGRATION COMPLETE" -ForegroundColor Green
Write-Host "================================================================================" -ForegroundColor Cyan
Write-Host ""
Write-Host "Summary:" -ForegroundColor Cyan
Write-Host "   Files moved: $($moves.Count)" -ForegroundColor Green
Write-Host "   Errors: $($errors.Count)" -ForegroundColor $(if ($errors.Count -eq 0) { "Green" } else { "Red" })
Write-Host "   Backup: $backup_dir" -ForegroundColor Yellow
Write-Host "   Log: $log_file" -ForegroundColor White
Write-Host ""
Write-Host "Next Steps:" -ForegroundColor Cyan
Write-Host "   1. git status" -ForegroundColor White
Write-Host "   2. git add ." -ForegroundColor White
Write-Host "   3. git commit -m 'Organize repository structure'" -ForegroundColor White
Write-Host "   4. git push origin main" -ForegroundColor White
Write-Host ""

$rollback = @"
`$ErrorActionPreference = 'Stop'
Write-Host 'Rolling back migration...' -ForegroundColor Yellow
"@

foreach ($move in $moves) {
    $rollback += "`nif (Test-Path '$($move.Destination)') { Move-Item '$($move.Destination)' '$($move.Source)' -Force; Write-Host '   Restored: $($move.Source)' -ForegroundColor Green }"
}

$rollback += "`nWrite-Host 'Rollback complete!' -ForegroundColor Green"
$rollback | Out-File "rollback_migration.ps1" -Encoding UTF8

Write-Host "Rollback script: rollback_migration.ps1" -ForegroundColor Green
Write-Host ""
