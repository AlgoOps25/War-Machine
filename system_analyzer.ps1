# system_analyzer.ps1
# Identifies distinct systems/subsystems in the codebase

Write-Host "`n=== Analyzing War Machine Repository Structure ===" -ForegroundColor Yellow

# Get all Python files
$allFiles = Get-ChildItem -Filter "*.py" -File | Where-Object { $_.Name -ne '__init__.py' }

# Define system patterns
$systems = @{
    'Core Scanner' = @('scanner.py', 'scanner_optimizer.py', 'sniper.py')
    'Signal Generation' = @('signal_generator.py', 'signal_validator.py', 'signal_analytics.py', 'breakout_detector.py')
    'Data Management' = @('data_manager.py', 'db_connection.py', 'candle_cache.py', 'ws_feed.py')
    'Validation & Filtering' = @('validation.py', 'cfw6_confirmation.py', 'correlation_check.py', 'hourly_gate.py')
    'Multi-Timeframe (MTF)' = @('mtf_integration.py', 'mtf_compression.py', 'mtf_fvg_priority.py', 'bos_fvg_engine.py')
    'Options Intelligence' = @('options_dte_selector.py', 'options_intelligence.py', 'iv_tracker.py', 'gex_engine.py')
    'Watchlist & Screening' = @('watchlist_funnel.py', 'dynamic_screener.py', 'premarket_scanner.py', 'volume_analyzer.py')
    'Risk & Position Management' = @('position_manager.py', 'trade_calculator.py', 'dynamic_thresholds.py')
    'Performance & Analytics' = @('performance_monitor.py', 'performance_alerts.py', 'technical_indicators.py')
    'AI & Learning' = @('ai_learning.py')
    'Infrastructure' = @('config.py', 'discord_helpers.py', 'production_helpers.py')
}

Write-Host "`n SYSTEM BREAKDOWN:" -ForegroundColor Cyan
Write-Host "" -ForegroundColor Cyan

$systemFiles = @{}

foreach ($system in $systems.Keys | Sort-Object) {
    Write-Host "`n[$system]" -ForegroundColor Green
    $count = 0
    
    foreach ($file in $systems[$system]) {
        if (Test-Path $file) {
            Write-Host "   $file" -ForegroundColor White
            $count++
            
            if (-not $systemFiles.ContainsKey($system)) {
                $systemFiles[$system] = @()
            }
            $systemFiles[$system] += $file
        } else {
            Write-Host "   $file (missing)" -ForegroundColor Gray
        }
    }
    
    Write-Host "  Total: $count files" -ForegroundColor Yellow
}

# Find unclassified files
$classifiedFiles = $systems.Values | ForEach-Object { $_ }
$unclassified = $allFiles | Where-Object { $classifiedFiles -notcontains $_.Name }

if ($unclassified.Count -gt 0) {
    Write-Host "`n[Unclassified Files]" -ForegroundColor Yellow
    $unclassified | ForEach-Object {
        Write-Host "  ? $($_.Name)" -ForegroundColor Gray
    }
}

Write-Host "`n`n=== PROPOSED FOLDER STRUCTURE ===" -ForegroundColor Cyan
Write-Host @"

war-machine/
 core/                      # Main scanner & sniper
    scanner.py
    scanner_optimizer.py
    sniper.py

 signals/                   # Signal generation & validation
    signal_generator.py
    signal_validator.py
    signal_analytics.py
    breakout_detector.py

 data/                      # Data pipelines & caching
    data_manager.py
    db_connection.py
    candle_cache.py
    ws_feed.py

 validation/                # Multi-layer validation
    validation.py
    cfw6_confirmation.py
    correlation_check.py
    hourly_gate.py

 mtf/                       # Multi-timeframe analysis
    mtf_integration.py
    mtf_compression.py
    mtf_fvg_priority.py
    bos_fvg_engine.py

 options/                   # Options intelligence
    options_dte_selector.py
    options_intelligence.py
    iv_tracker.py
    gex_engine.py

 screening/                 # Watchlist & screening
    watchlist_funnel.py
    dynamic_screener.py
    premarket_scanner.py
    volume_analyzer.py

 risk/                      # Risk & position management
    position_manager.py
    trade_calculator.py
    dynamic_thresholds.py

 analytics/                 # Performance tracking
    performance_monitor.py
    performance_alerts.py
    technical_indicators.py

 ai/                        # AI learning & optimization
    ai_learning.py

 backtesting/               # Backtesting engine (future)
    README.md

 utils/                     # Helpers & infrastructure
    config.py
    discord_helpers.py
    production_helpers.py

 tests/                     # Testing (separate)
    README.md

 archives/                  # Old code
     _archive_unused_2026-02-28/

"@ -ForegroundColor White

Write-Host "`n=== MIGRATION PLAN ===" -ForegroundColor Yellow
Write-Host @"

Phase 1: Create folder structure
Phase 2: Move files to folders
Phase 3: Update all imports
Phase 4: Test locally
Phase 5: Deploy to Railway

"@ -ForegroundColor White

# Save detailed report
$timestamp = Get-Date -Format "yyyy-MM-dd_HHmmss"
$reportFile = "system_structure_analysis_$timestamp.txt"

$report = @"
WAR MACHINE SYSTEM STRUCTURE ANALYSIS
Generated: $(Get-Date)

=== CURRENT SYSTEMS ===
$(foreach ($system in $systemFiles.Keys | Sort-Object) {
    "`n[$system]"
    $systemFiles[$system] | ForEach-Object { "  - $_" }
} | Out-String)

=== UNCLASSIFIED FILES ===
$($unclassified | ForEach-Object { "  - $($_.Name)" } | Out-String)

=== PROPOSED STRUCTURE ===
See console output above

=== NEXT STEPS ===
1. Review proposed structure
2. Adjust folder names if needed
3. Run migration script
4. Update imports systematically
5. Test & deploy
"@

$report | Out-File -FilePath $reportFile -Encoding UTF8

Write-Host " Full analysis saved: $reportFile" -ForegroundColor Cyan
Write-Host "`nReady to proceed with folder restructure? (Creates migration script)" -ForegroundColor Yellow
