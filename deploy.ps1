# War Machine - Deployment Script (PowerShell)
# ==============================================

Write-Host "`n" -NoNewline
Write-Host "===============================================================================" -ForegroundColor Cyan
Write-Host "  WAR MACHINE - DEPLOYMENT SCRIPT" -ForegroundColor Cyan
Write-Host "===============================================================================" -ForegroundColor Cyan
Write-Host ""

# Step 1: Git Status
Write-Host "[1/4] Checking Git status..." -ForegroundColor Yellow
git status --short

if ($LASTEXITCODE -ne 0) {
    Write-Host "ERROR: Git status failed" -ForegroundColor Red
    exit 1
}

Write-Host ""

# Step 2: Git Add
Write-Host "[2/4] Adding changes to Git..." -ForegroundColor Yellow
git add .

if ($LASTEXITCODE -ne 0) {
    Write-Host "ERROR: Git add failed" -ForegroundColor Red
    exit 1
}

Write-Host "OK All changes staged" -ForegroundColor Green
Write-Host ""

# Step 3: Git Commit
Write-Host "[3/4] Committing changes..." -ForegroundColor Yellow
$commitMessage = "Add regime filter - Phase 2C complete"
git commit -m $commitMessage

if ($LASTEXITCODE -ne 0) {
    Write-Host "WARNING: Commit failed (might be nothing to commit)" -ForegroundColor Yellow
} else {
    Write-Host "OK Commit successful" -ForegroundColor Green
}

Write-Host ""

# Step 4: Git Push
Write-Host "[4/4] Pushing to GitHub..." -ForegroundColor Yellow
git push origin main

if ($LASTEXITCODE -ne 0) {
    Write-Host "ERROR: Push failed" -ForegroundColor Red
    exit 1
}

Write-Host "OK Push successful" -ForegroundColor Green
Write-Host ""

# Success
Write-Host "===============================================================================" -ForegroundColor Green
Write-Host "  DEPLOYMENT COMPLETE" -ForegroundColor Green
Write-Host "===============================================================================" -ForegroundColor Green
Write-Host ""
Write-Host "Next steps:" -ForegroundColor Cyan
Write-Host "  1. Check Railway deployment logs" -ForegroundColor White
Write-Host "  2. Look for: [VALIDATOR] Regime filter enabled" -ForegroundColor White
Write-Host "  3. Monitor first scan cycle for regime checks" -ForegroundColor White
Write-Host ""
