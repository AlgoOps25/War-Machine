# smart_migrate.ps1
# Intelligent subsystem migration tool with safety checks

param(
    [Parameter(Mandatory=$true)]
    [ValidateSet("risk", "screening", "options", "mtf", "validation", "data", "signals", "core")]
    [string]$Subsystem
)

# Define subsystem configurations
$subsystems = @{
    'risk' = @{
        folder = 'app/risk'
        files = @('position_manager.py', 'trade_calculator.py', 'dynamic_thresholds.py')
        impact = 'Medium - Position sizing'
        dependencies = @('config', 'db_connection')
    }
    'screening' = @{
        folder = 'app/screening'
        files = @('watchlist_funnel.py', 'dynamic_screener.py', 'premarket_scanner.py', 'volume_analyzer.py')
        impact = 'Medium - Ticker selection'
        dependencies = @('config', 'data_manager')
    }
    'options' = @{
        folder = 'app/options'
        files = @('options_dte_selector.py', 'options_intelligence.py', 'iv_tracker.py', 'gex_engine.py')
        impact = 'Medium - Options selection'
        dependencies = @('config', 'db_connection', 'technical_indicators')
    }
    'mtf' = @{
        folder = 'app/mtf'
        files = @('mtf_integration.py', 'mtf_compression.py', 'mtf_fvg_priority.py', 'bos_fvg_engine.py')
        impact = 'High - Signal scoring'
        dependencies = @('config')
    }
    'validation' = @{
        folder = 'app/validation'
        files = @('validation.py', 'cfw6_confirmation.py', 'correlation_check.py', 'hourly_gate.py')
        impact = 'High - Signal filtering'
        dependencies = @('config', 'technical_indicators', 'options_intelligence')
    }
    'data' = @{
        folder = 'app/data'
        files = @('data_manager.py', 'db_connection.py', 'candle_cache.py', 'ws_feed.py')
        impact = 'CRITICAL - Data flow'
        dependencies = @('config')
    }
    'signals' = @{
        folder = 'app/signals'
        files = @('signal_generator.py', 'signal_validator.py', 'signal_analytics.py', 'breakout_detector.py')
        impact = 'CRITICAL - Core logic'
        dependencies = @('config', 'data_manager', 'validation', 'options_dte_selector')
    }
    'core' = @{
        folder = 'app/core'
        files = @('scanner.py', 'scanner_optimizer.py', 'sniper.py')
        impact = 'CRITICAL - Entry point'
        dependencies = @('ALL')
    }
}

$config = $subsystems[$Subsystem]

Write-Host "`n" -ForegroundColor Cyan
Write-Host "MIGRATING: $Subsystem" -ForegroundColor Green
Write-Host "" -ForegroundColor Cyan
Write-Host "Folder: $($config.folder)" -ForegroundColor White
Write-Host "Files: $($config.files.Count)" -ForegroundColor White
Write-Host "Impact: $($config.impact)" -ForegroundColor Yellow
Write-Host ""

# Function to fix imports safely
function Fix-ImportsSafely {
    param([string]$FilePath, [string]$TargetFolder)
    
    $content = Get-Content $FilePath -Raw
    $originalContent = $content
    
    # CRITICAL: Check if already migrated
    if ($content -match "from $TargetFolder") {
        Write-Host "    File already has migrated imports - skipping" -ForegroundColor Yellow
        return $false
    }
    
    # Fix common imports (only if not already fixed)
    if ($content -notmatch "from utils import config") {
        $content = $content -replace '\bimport config\b', 'from utils import config'
    }
    
    if ($content -notmatch "from app\.data import db_connection") {
        $content = $content -replace '\bimport db_connection\b', 'from app.data import db_connection'
    }
    
    # Only save if changed
    if ($content -ne $originalContent) {
        $content | Out-File -FilePath $FilePath -Encoding UTF8 -Force
        return $true
    }
    
    return $false
}

# STEP 1: Create backup
Write-Host " Step 1: Creating backup..." -ForegroundColor Yellow
$backupFolder = "_migration_backup_$(Get-Date -Format 'yyyyMMdd_HHmmss')"
New-Item -ItemType Directory -Path $backupFolder -Force | Out-Null

foreach ($file in $config.files) {
    if (Test-Path $file) {
        Copy-Item $file "$backupFolder/$file"
        Write-Host "   Backed up: $file" -ForegroundColor Green
    }
}

# STEP 2: Fix imports in target folder
Write-Host "`n Step 2: Fixing imports in $($config.folder)..." -ForegroundColor Yellow

$fixedCount = 0
foreach ($file in $config.files) {
    $targetFile = "$($config.folder)/$file"
    if (Test-Path $targetFile) {
        if (Fix-ImportsSafely -FilePath $targetFile -TargetFolder $config.folder) {
            Write-Host "   Fixed: $targetFile" -ForegroundColor Green
            $fixedCount++
        } else {
            Write-Host "   Skipped: $targetFile (already migrated)" -ForegroundColor Gray
        }
    }
}

$env:PYTHONIOENCODING = "utf-8"  # Fix Windows Unicode issues`n# STEP 3: Test imports
Write-Host "`n Step 3: Testing all imports..." -ForegroundColor Yellow

$allPassed = $true
foreach ($file in $config.files) {
    $moduleName = [System.IO.Path]::GetFileNameWithoutExtension($file)
    $importPath = "$($config.folder.Replace('/', '.')).$moduleName"
    
    $testResult = python -c "from $importPath import *; print('')" 2>&1
    
    if ($LASTEXITCODE -eq 0) {
        Write-Host "   $importPath" -ForegroundColor Green
    } else {
        Write-Host "   $importPath - $testResult" -ForegroundColor Red
        $allPassed = $false
    }
}

if (-not $allPassed) {
    Write-Host "`n TESTS FAILED - Restoring backup..." -ForegroundColor Red
    foreach ($file in $config.files) {
        if (Test-Path "$backupFolder/$file") {
            Copy-Item "$backupFolder/$file" $file -Force
        }
    }
    Write-Host " Backup restored" -ForegroundColor Green
    exit 1
}

# STEP 4: Delete root files
Write-Host "`n  Step 4: Cleaning up root files..." -ForegroundColor Yellow

foreach ($file in $config.files) {
    if (Test-Path $file) {
        Remove-Item $file -Force
        Write-Host "   Deleted: $file" -ForegroundColor Green
    }
}

# STEP 5: Deploy
Write-Host "`n Step 5: Deploying..." -ForegroundColor Cyan

git add .
git commit -m "refactor: migrate $Subsystem subsystem to $($config.folder)"
git push

Write-Host "`n $Subsystem MIGRATION COMPLETE!" -ForegroundColor Green
Write-Host "Backup saved in: $backupFolder" -ForegroundColor Gray

