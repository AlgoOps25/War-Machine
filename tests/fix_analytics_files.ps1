# Fix escaped newlines in analytics files
$files = @(
    "src/analytics/signal_analytics.py",
    "src/learning/ml_feedback_loop.py", 
    "src/reporting/performance_reporter.py"
)

foreach ($file in $files) {
    if (Test-Path $file) {
        $content = Get-Content $file -Raw
        $fixed = $content -replace '\\n', "`n"
        $fixed | Set-Content $file -NoNewline
        Write-Host "✅ Fixed: $file"
    }
}
