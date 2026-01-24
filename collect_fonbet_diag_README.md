# Диагностика Fonbet (Inforadar)

ZIP создаётся скриптом collect_fonbet_diag.ps1.
Нужен чтобы проверить цепочку:
prematch парсер -> MySQL (fonbet_events) -> fonbet_api (/fonbet/events) -> UI (/fonbet)

Как запускать:
powershell -ExecutionPolicy Bypass -File .\collect_fonbet_diag.ps1
powershell -ExecutionPolicy Bypass -File .\collect_fonbet_diag.ps1 -ApiPort 8010
