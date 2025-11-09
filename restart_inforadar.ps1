Write-Host "🔄 Перезапуск Inforadar..." -ForegroundColor Cyan

# Переход в директорию проекта
Set-Location "C:\Inforadar_Pro"

# Остановка контейнеров
docker compose down

# Запуск без пересборки образов
docker compose up -d

Write-Host "✅ Inforadar успешно перезапущен!" -ForegroundColor Green
