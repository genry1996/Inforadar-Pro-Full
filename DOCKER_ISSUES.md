# Инфо о Docker контейнерах

## Статус:
1. anomaly_detector - SILENT (не выводит логи, контейнер не работает)
2. arbitrage_detector - OK (собран успешно)
3. parser_22bet_live - BLOCKED (net::ERR_CONNECTION_CLOSED)

## Файлы:
- detectors/odds_analyzer.py - не запускается
- detectors/Dockerfile - создан корректно
- Dockerfile.arbitrage - исправлен
- parsers/playwright_22bet/ - имеет проблему с подключением

## Нужно проверить:
1. Почему anomaly_detector не выводит никаких логов?
2. Почему playwright не может подключиться к 22bet?
3. Нужна ли proxy конфигурация?
