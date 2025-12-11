# 🚀 InfoRadar Pro - Setup Instructions

## ШАГИ НАСТРОЙКИ:

### 1️⃣ Очистка старых файлов
```bash
# Windows PowerShell
cd D:\Inforadar_Pro

# Запусти cleanup скрипт
.\cleanup.bat

# Или вручную удали (если что-то пошло не так):
rm D:\Inforadar_Pro\inforadar_parser\betwatch_debug*.py
rm D:\Inforadar_Pro\inforadar_parser\parser_22bet.py
rm D:\Inforadar_Pro\inforadar_parser\debug_22bet*.html
```

### 2️⃣ Замени docker-compose.yml
```bash
# Скопируй новый файл
cp docker-compose-correct.yml docker-compose.yml

# Проверь синтаксис
docker-compose config
```

### 3️⃣ Замени Dockerfiles
```bash
# Скопируй новые Dockerfiles
cp Dockerfile.betwatch-new Dockerfile.betwatch
cp Dockerfile.22bet-new Dockerfile.22bet
cp Dockerfile.arbitrage-new Dockerfile.arbitrage
```

### 4️⃣ Обнови requirements.txt
```bash
# Скопируй в папку inforadar_parser/
cp requirements_betwatch-new.txt inforadar_parser/requirements_betwatch.txt
```

### 5️⃣ Убедись что у тебя есть нужные парсеры
```bash
# Должны быть эти файлы в inforadar_parser/:
ls inforadar_parser/ | grep -E "(betwatch-advanced|parser_22bet_playwright|arbitrage-detector)"

# Если чего-то не хватает, скопируй из текстовых файлов выше
```

### 6️⃣ Настрой .env переменные
```bash
# Создай/отредактируй .env файл в корне проекта
notepad .env
```

**Содержимое .env:**
```
TELEGRAM_TOKEN=your_bot_token_here
PROXY_IP=213.137.91.35
PROXY_PORT=12323
PROXY_USER=14ab48c9d85c1
PROXY_PASS=5d234f6517
MYSQL_ROOT_PASSWORD=root_password
```

### 7️⃣ Проверь структуру проекта
```
D:\Inforadar_Pro\
├── docker-compose.yml          ✅ (новый)
├── Dockerfile.betwatch         ✅ (новый)
├── Dockerfile.22bet            ✅ (новый)
├── Dockerfile.arbitrage        ✅ (новый)
├── dashboard.html              ✅ (новый)
├── .env                        ✅ (с переменными)
└── inforadar_parser/
    ├── betwatch-advanced.py         ✅ (новый)
    ├── parser_22bet_playwright.py   ✅ (старый, рабочий)
    ├── arbitrage-detector.py        ✅ (новый)
    ├── requirements_betwatch.txt    ✅ (новый)
    └── requirements.txt             ✅ (старый, рабочий)
```

### 8️⃣ Запуск Docker
```bash
# Собери образы
docker-compose build

# Запусти все сервисы
docker-compose up -d

# Проверь логи
docker-compose logs -f playwright_betwatch
docker-compose logs -f playwright_22bet
docker-compose logs -f arbitrage_detector

# Переди на Dashboard
http://localhost:8080
```

### 9️⃣ Проверка работы
```bash
# Проверь что контейнеры запустились
docker-compose ps

# Должно быть:
# mysql_inforadar           mysql                    Up
# playwright_betwatch       Dockerfile.betwatch      Up
# playwright_22bet          Dockerfile.22bet         Up
# arbitrage_detector        Dockerfile.arbitrage     Up
# dashboard_server          node:18-alpine           Up
```

---

## ❌ Если что-то не работает:

### Ошибка: "services.depends_on must be a mapping"
→ Используешь старый docker-compose.yml, замени на новый!

### Ошибка: "service not found"
→ Убедись что все файлы скопированы в правильные места

### Ошибка: "ModuleNotFoundError"
→ Пересобери Docker образы:
```bash
docker-compose build --no-cache
```

### Ошибка: MySQL не подключается
→ Проверь что mysql_inforadar контейнер запустился:
```bash
docker-compose logs mysql_inforadar
```

---

## 📊 Информация об архитектуре:

```
┌─────────────────────────────────────────────────────────┐
│                    InfoRadar Pro                         │
└─────────────────────────────────────────────────────────┘

┌────────────────────────────────────────────────────────────┐
│                      MySQL Database                         │
│  (signals, arbitrage_signals, event_history)               │
└────────────────────────────────────────────────────────────┘
          ↑                    ↑                    ↑
          │                    │                    │
   ┌──────────────┐  ┌──────────────┐  ┌──────────────────┐
   │   Betwatch   │  │   22bet      │  │  Arbitrage       │
   │   Parser     │  │   Parser     │  │  Detector        │
   │              │  │              │  │                  │
   │ • Sharp Move │  │ • Coeff.     │  │ • Calculates     │
   │ • Line Shift │  │ • Live       │  │   profit         │
   │ • Squeeze    │  │   events     │  │ • Maps odds      │
   │ • Vol Spike  │  │              │  │ • Sends alerts   │
   └──────────────┘  └──────────────┘  └──────────────────┘

          ↓                    ↓                    ↓
   ┌──────────────────────────────────────────────────────┐
   │              Web Dashboard (HTML)                     │
   │                                                       │
   │  • Real-time signals                                 │
   │  • Arbitrage opportunities                           │
   │  • Charts & statistics                               │
   │  • Auto-refresh every 30 sec                         │
   └──────────────────────────────────────────────────────┘
```

---

## 🎯 Следующие шаги:

1. ✅ Выполни шаги 1-4 выше
2. ✅ Запусти `docker-compose up -d`
3. ✅ Проверь логи всех контейнеров
4. ✅ Открой http://localhost:8080 в браузере
5. ✅ Убедись что сигналы появляются в Dashboard

**Готов начинать?** 🚀
