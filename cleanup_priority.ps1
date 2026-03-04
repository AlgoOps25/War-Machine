# War Machine - Priority Cleanup Script
$ErrorActionPreference = "Stop"

Write-Host ""
Write-Host "================================================================================" -ForegroundColor Cyan
Write-Host " WAR MACHINE - PRIORITY CLEANUP"
Write-Host "================================================================================" -ForegroundColor Cyan
Write-Host ""

# PRIORITY 1: Remove duplicate migration directory
Write-Host "Priority 1: Removing duplicate migration/ directory..." -ForegroundColor Yellow
if (Test-Path "migration") {
    git rm -r migration
    Write-Host "   ✅ Removed migration/ (duplicate)" -ForegroundColor Green
}
Write-Host ""

# PRIORITY 2: Organize backtests directory
Write-Host "Priority 2: Organizing backtests directory..." -ForegroundColor Yellow

# Move Python scripts to scripts/backtesting/
$backtest_scripts = @(
    "backtests/analyze_losers.py",
    "backtests/extract_candles_from_db.py",
    "backtests/historical_advisor.py",
    "backtests/run_full_dte_backtest.py",
    "backtests/simulate_from_candles.py",
    "backtests/test_dte_logic.py"
)

foreach ($script in $backtest_scripts) {
    if (Test-Path $script) {
        $filename = Split-Path -Leaf $script
        git mv $script "scripts/backtesting/$filename"
        Write-Host "   ✅ Moved $filename to scripts/backtesting/" -ForegroundColor Green
    }
}

# Move CSV results to results/backtests/
$backtest_results = @(
    "backtests/historical_signals.csv",
    "backtests/position_history.csv"
)

foreach ($result in $backtest_results) {
    if (Test-Path $result) {
        $filename = Split-Path -Leaf $result
        git mv $result "results/backtests/$filename"
        Write-Host "   ✅ Moved $filename to results/backtests/" -ForegroundColor Green
    }
}

# Move README to docs
if (Test-Path "backtests/README.md") {
    git mv backtests/README.md docs/backtests.md
    Write-Host "   ✅ Moved README to docs/backtests.md" -ForegroundColor Green
}

# Remove empty backtests directory
if ((Get-ChildItem -Path backtests -Force | Measure-Object).Count -eq 0) {
    Remove-Item backtests -Force
    Write-Host "   ✅ Removed empty backtests/ directory" -ForegroundColor Green
}

Write-Host ""
Write-Host "================================================================================" -ForegroundColor Cyan
Write-Host " CLEANUP COMPLETE"
Write-Host "================================================================================" -ForegroundColor Cyan
Write-Host ""
Write-Host "Next steps:" -ForegroundColor Cyan
Write-Host "   1. Review changes: git status" -ForegroundColor White
Write-Host "   2. Commit: git commit -m 'Clean up duplicate directories and organize backtests'" -ForegroundColor White
Write-Host "   3. Push: git push origin main" -ForegroundColor White
Write-Host ""
