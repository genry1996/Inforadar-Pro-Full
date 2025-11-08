Write-Host "== Docker cleanup started ==" -ForegroundColor Cyan

# Show current disk usage
docker system df

# Stop and remove dangling/unused containers (not running)
Write-Host "`nPruning stopped containers..." -ForegroundColor Yellow
docker container prune -f

# Remove dangling images (<none>)
Write-Host "`nPruning dangling images..." -ForegroundColor Yellow
docker image prune -f

# Remove build cache (can be large)
Write-Host "`nPruning build cache..." -ForegroundColor Yellow
docker builder prune -af

# Remove unused networks
Write-Host "`nPruning unused networks..." -ForegroundColor Yellow
docker network prune -f

# Remove unused volumes (NOTE: volumes used by running containers are kept)
Write-Host "`nPruning unused volumes..." -ForegroundColor Yellow
docker volume prune -f

Write-Host "`n== Docker cleanup complete ==" -ForegroundColor Green
docker system df
