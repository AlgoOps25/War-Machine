# restore_and_deploy.ps1
# Automatically handles git pull conflicts when restoring archived files

param(
    [Parameter(Mandatory=$false)]
    [string]$Message = "restore: bring back archived modules for scanner.py"
)

Write-Host "`n Starting restore and deploy process..." -ForegroundColor Cyan

# Pull first
Write-Host "`n Pulling latest changes..." -ForegroundColor Yellow
git pull --rebase

# Stage all Python files you've restored
Write-Host "`n Staging restored files..." -ForegroundColor Yellow
git add *.py

# Show status
Write-Host "`n Current status:" -ForegroundColor Cyan
git status --short

# Commit
Write-Host "`n Committing..." -ForegroundColor Yellow
git commit -m $Message

# Push
Write-Host "`n Pushing to Railway..." -ForegroundColor Yellow
git push

Write-Host "`n Deploy complete!" -ForegroundColor Green
