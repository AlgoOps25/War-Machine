# dependency_analyzer.ps1
# Scans Python files to find all import dependencies

Write-Host "`n=== PHASE 1: Scanning Python Files ===" -ForegroundColor Cyan

$pythonFiles = Get-ChildItem -Filter "*.py" -Recurse -File | Where-Object {
    $_.FullName -notlike "*\.venv\*" -and 
    $_.FullName -notlike "*\archive\*" -and
    $_.FullName -notlike "*_archive*"
}

Write-Host "Found $($pythonFiles.Count) Python files to analyze`n" -ForegroundColor Green

# Track all imports
$allImports = @{}
$fileImports = @{}

foreach ($file in $pythonFiles) {
    $content = Get-Content $file.FullName -Raw
    $fileName = $file.Name -replace '\.py$', ''
    
    # Find import statements
    $imports = [regex]::Matches($content, '(?:from|import)\s+([a-zA-Z0-9_]+)')
    
    $fileImports[$file.Name] = @()
    
    foreach ($match in $imports) {
        $importName = $match.Groups[1].Value
        
        # Only track local module imports (not stdlib or external packages)
        $localModule = "$importName.py"
        if (Test-Path $localModule) {
            $fileImports[$file.Name] += $importName
            
            if (-not $allImports.ContainsKey($importName)) {
                $allImports[$importName] = @()
            }
            $allImports[$importName] += $file.Name
        }
    }
}

Write-Host "`n=== PHASE 2: Dependency Analysis ===" -ForegroundColor Cyan

# Find entry points (files that are run directly)
$entryPoints = @('scanner.py', 'app.py', 'main.py', 'run.py')
$activeFiles = $entryPoints | Where-Object { Test-Path $_ }

Write-Host "`nEntry Points Found:" -ForegroundColor Yellow
$activeFiles | ForEach-Object { Write-Host "   $_" -ForegroundColor Green }

# Build dependency tree from entry points
$required = @{}
$toProcess = [System.Collections.Queue]::new()

foreach ($entry in $activeFiles) {
    $moduleName = $entry -replace '\.py$', ''
    $required[$entry] = "ENTRY_POINT"
    $toProcess.Enqueue($entry)
}

Write-Host "`n Building dependency tree..." -ForegroundColor Yellow

while ($toProcess.Count -gt 0) {
    $current = $toProcess.Dequeue()
    
    if ($fileImports.ContainsKey($current)) {
        foreach ($import in $fileImports[$current]) {
            $importFile = "$import.py"
            
            if (-not $required.ContainsKey($importFile)) {
                $required[$importFile] = $current
                $toProcess.Enqueue($importFile)
            }
        }
    }
}

Write-Host "`n=== PHASE 3: Results ===" -ForegroundColor Cyan

# Get all Python files in root
$rootFiles = Get-ChildItem -Filter "*.py" -File | Where-Object {
    $_.Name -ne '__init__.py'
}

Write-Host "`n REQUIRED FILES (Keep in root):" -ForegroundColor Green
Write-Host "" -ForegroundColor Green

$requiredList = @()
foreach ($file in $rootFiles | Sort-Object Name) {
    if ($required.ContainsKey($file.Name)) {
        $importedBy = $required[$file.Name]
        Write-Host "   $($file.Name.PadRight(40)) <- $importedBy" -ForegroundColor White
        $requiredList += $file.Name
    }
}

Write-Host "`n  UNUSED FILES (Safe to archive):" -ForegroundColor Yellow
Write-Host "" -ForegroundColor Yellow

$unusedList = @()
foreach ($file in $rootFiles | Sort-Object Name) {
    if (-not $required.ContainsKey($file.Name)) {
        # Check if file has "test", "validate", "old" in name
        $isTest = $file.Name -match '(test_|_test|validate|old|backup|temp)'
        $marker = if ($isTest) { "" } else { "" }
        
        Write-Host "  $marker $($file.Name)" -ForegroundColor Gray
        $unusedList += $file.Name
    }
}

Write-Host "`n=== SUMMARY ===" -ForegroundColor Cyan
Write-Host "Required files:  $($requiredList.Count)" -ForegroundColor Green
Write-Host "Unused files:    $($unusedList.Count)" -ForegroundColor Yellow
Write-Host "Total analyzed:  $($rootFiles.Count)" -ForegroundColor White

# Save results
$timestamp = Get-Date -Format "yyyy-MM-dd_HHmmss"
$reportFile = "dependency_report_$timestamp.txt"

$requiredText = $requiredList | ForEach-Object { " $_" }
$unusedText = $unusedList | ForEach-Object { " $_" }
$dependencyText = $required.Keys | Sort-Object | ForEach-Object { "$_ <- $($required[$_])" }

$report = @"
WAR MACHINE DEPENDENCY ANALYSIS
Generated: $(Get-Date)

=== REQUIRED FILES ===
$($requiredText -join "`n")

=== UNUSED FILES ===
$($unusedText -join "`n")

=== DEPENDENCY TREE ===
$($dependencyText -join "`n")
"@

$report | Out-File -FilePath $reportFile -Encoding UTF8

Write-Host "`n Full report saved: $reportFile" -ForegroundColor Cyan

# Generate archive command
if ($unusedList.Count -gt 0) {
    Write-Host "`n SAFE ARCHIVE COMMAND:" -ForegroundColor Yellow
    Write-Host "" -ForegroundColor Yellow
    
    $archiveDir = "_archive_unused_$(Get-Date -Format 'yyyy-MM-dd')"
    
    Write-Host "`nmkdir $archiveDir" -ForegroundColor White
    foreach ($file in $unusedList) {
        Write-Host "Move-Item '$file' '$archiveDir\'" -ForegroundColor White
    }
}
