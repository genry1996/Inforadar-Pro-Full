# 22BET Anomaly Parser 🎯

Парсер коэффициентов 22BET с обнаружением аномалий в реальном времени.

**Статус:** ✅ Production Ready | **Порог:** -1% | **Обновление:** каждую минуту

---

## 📋 Содержание

- [Быстрый старт](#-быстрый-старт)
- [Установка](#-установка)
- [Конфигурация](#⚙️-конфигурация)
- [Использование](#-использование)
- [Структура проекта](#-структура-проекта)
- [Схема БД](#-схема-бд)
- [Тестирование](#-тестирование)
- [Лицензия](#-лицензия)

---

## 🚀 Быстрый старт

```bash
# 1. Клонировать репо
git clone https://github.com/YOUR_USERNAME/Inforadar_Pro.git
cd Inforadar_Pro

# 2. Создать виртуальное окружение
python -m venv venv
source venv/bin/activate  # Linux/Mac
venv\Scripts\activate     # Windows

# 3. Установить зависимости
pip install -r requirements.txt

# 4. Настроить переменные
cp .env.example .env
# Отредактируйте .env с вашими данными БД

# 5. Запустить парсер
python parser_22bet_anomaly_detector.py
```

---

## 📦 Установка

### Требования

- **Python:** 3.8+
- **MySQL:** 5.7+ или 8.0+
- **ОЗУ:** 512 МБ минимум
- **Интернет:** стабильное соединение

### Пошаговая установка

#### 1️⃣ Клонировать репозиторий

```bash
git clone https://github.com/YOUR_USERNAME/Inforadar_Pro.git
cd Inforadar_Pro
```

#### 2️⃣ Создать виртуальное окружение

**Linux/Mac:**
```bash
python3 -m venv venv
source venv/bin/activate
```

**Windows:**
```bash
python -m venv venv
venv\Scripts\activate
```

#### 3️⃣ Установить зависимости

```bash
pip install --upgrade pip
pip install -r requirements.txt
```

#### 4️⃣ Инициализировать БД

```bash
mysql -u root -p < database/schema.sql
```

Или вручную:
```bash
mysql -u root -p
mysql> CREATE DATABASE inforadar;
mysql> USE inforadar;
mysql> source database/schema.sql;
mysql> exit;
```

---

## ⚙️ Конфигурация

### .env переменные

Скопируйте `.env.example` в `.env`:

```bash
cp .env.example .env
```

**Основные параметры:**

| Переменная | Значение | Описание |
|-----------|----------|---------|
| `MYSQL_HOST` | localhost | Хост БД |
| `MYSQL_USER` | root | Пользователь БД |
| `MYSQL_PASSWORD` | your_password | Пароль БД |
| `MYSQL_DB` | inforadar | Имя БД |
| `DETECTION_THRESHOLD` | -1.0 | Порог обнаружения аномалии (%) |
| `UPDATE_INTERVAL` | 60 | Интервал проверки (сек) |
| `TELEGRAM_BOT_TOKEN` | xxx | Токен Telegram бота (опционально) |

**Пример .env:**

```env
MYSQL_HOST=localhost
MYSQL_PORT=3306
MYSQL_USER=root
MYSQL_PASSWORD=MySecurePass123
MYSQL_DB=inforadar

DETECTION_THRESHOLD=-1.0
CONFIRMATION_DELAY=5
UPDATE_INTERVAL=60

LOG_LEVEL=INFO
APP_MODE=production
```

---

## 🎯 Использование

### Базовый запуск

```bash
python parser_22bet_anomaly_detector.py
```

**Вывод:**

```
2025-12-15 22:09:47,781 | INFO | 🚀 Парсер 22BET запущен
2025-12-15 22:09:48,145 | INFO | 🌐 Пробуем: https://22betluck.com
2025-12-15 22:09:51,784 | INFO | ✅ Работает: https://22betluck.com
2025-12-15 22:09:51,797 | INFO | 📌 Загружаем: https://22betluck.com/line/football/
2025-12-15 22:09:57,327 | INFO | 📊 Найдено событий: 50
2025-12-15 22:09:57,417 | INFO |  ✓ Manchester United vs Bournemouth: 1.80 | 4.10 | 3.94
...
```

### С логированием в файл

```bash
python parser_22bet_anomaly_detector.py > logs/parser.log 2>&1 &
```

### С Prometheus метриками

```bash
# Включить в .env
ENABLE_PROMETHEUS=true
PROMETHEUS_PORT=8000

# Запустить
python parser_22bet_anomaly_detector.py

# Проверить метрики
curl http://localhost:8000/metrics
```

---

## 📂 Структура проекта

```
Inforadar_Pro/
├── parser_22bet_anomaly_detector.py   # Основной парсер
├── requirements.txt                    # Зависимости
├── .env.example                        # Шаблон конфигурации
├── .gitignore                          # Git исключения
├── README.md                           # Документация
│
├── database/
│   └── schema.sql                      # Схема БД MySQL
│
├── tests/
│   └── anomalies-monitor.spec.ts       # Playwright тесты
│
└── logs/
    └── parser.log                      # Логи (создается автоматически)
```

---

## 📊 Схема БД

### Таблица: `odds_22bet`

Хранит текущие и исторические коэффициенты.

```sql
CREATE TABLE odds_22bet (
  id INT AUTO_INCREMENT PRIMARY KEY,
  event_name VARCHAR(255) NOT NULL,
  sport VARCHAR(100),
  league VARCHAR(100),
  market_type VARCHAR(50) DEFAULT '1X2',
  odd_1 DECIMAL(6,3),
  odd_x DECIMAL(6,3),
  odd_2 DECIMAL(6,3),
  status VARCHAR(50) DEFAULT 'active',
  updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  UNIQUE KEY unique_event (event_name, market_type),
  INDEX idx_sport (sport),
  INDEX idx_updated (updated_at)
);
```

### Таблица: `anomalies_22bet`

Хранит обнаруженные аномалии.

```sql
CREATE TABLE anomalies_22bet (
  id INT AUTO_INCREMENT PRIMARY KEY,
  event_name VARCHAR(255),
  sport VARCHAR(100),
  league VARCHAR(100),
  anomaly_type VARCHAR(50),
  market_type VARCHAR(50),
  before_value DECIMAL(8,3),
  after_value DECIMAL(8,3),
  diff_pct DECIMAL(8,2),
  status VARCHAR(50) DEFAULT 'new',
  comment TEXT,
  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
  INDEX idx_type (anomaly_type),
  INDEX idx_sport (sport),
  INDEX idx_created (created_at)
);
```

---

## 🧪 Тестирование

### Запуск Playwright тестов

```bash
# Установить браузеры для Playwright
playwright install

# Запустить тесты
npx playwright test tests/anomalies-monitor.spec.ts

# С отчетом
npx playwright test --reporter=html
```

### Ручное тестирование

```bash
# Проверить подключение к 22BET
curl https://22betluck.com/line/football/

# Проверить подключение к БД
mysql -u root -p inforadar -e "SELECT COUNT(*) FROM odds_22bet;"

# Проверить метрики Prometheus
curl http://localhost:8000/metrics
```

---

## 🔍 Мониторинг

### Проверка статуса

```bash
# Количество событий в БД
mysql -u inforadar -p inforadar -e "SELECT COUNT(*) as total_events FROM odds_22bet;"

# Последние аномалии
mysql -u inforadar -p inforadar -e "SELECT * FROM anomalies_22bet ORDER BY created_at DESC LIMIT 10;"

# Статистика по спортам
mysql -u inforadar -p inforadar -e "SELECT sport, COUNT(*) FROM odds_22bet GROUP BY sport;"
```

### Логи

```bash
# Просмотр логов в реальном времени
tail -f logs/parser.log

# Поиск ошибок
grep ERROR logs/parser.log

# Поиск аномалий
grep "Аномалия" logs/parser.log
```

---

## 🐛 Troubleshooting

### Проблема: Connection refused

**Решение:**
```bash
# Проверить, запущена ли MySQL
sudo service mysql status

# Проверить параметры подключения в .env
cat .env | grep MYSQL
```

### Проблема: ModuleNotFoundError

**Решение:**
```bash
# Убедитесь, что venv активирован
source venv/bin/activate  # Linux/Mac
venv\Scripts\activate     # Windows

# Переустановите зависимости
pip install -r requirements.txt --force-reinstall
```

### Проблема: 22BET недоступен

**Решение:**
```bash
# Проверить интернет
ping 22betluck.com

# Включить прокси в .env
USE_PROXY=true
PROXY_SERVER=http://your_proxy:port
```

---

## 📈 Параметры аномалий

Система обнаруживает следующие типы аномалий:

| Тип | Описание | Порог |
|-----|---------|--------|
| **ODDS_DROP** | Резкое падение коэффициента | < -1% |
| **ODDS_SPIKE** | Резкий рост коэффициента | > +1% |
| **LIMIT_CUT** | Порезка максимальной ставки | любое снижение |
| **MARKET_REMOVED** | Матч убран из линии | статус changed |
| **MARKET_FROZEN** | Линия заморожена | timeout > 5 мин |

---

## 📝 Лицензия

MIT License - свободное использование в личных и коммерческих целях.

---

## 👤 Автор

**Your Name**  
GitHub: [@YOUR_USERNAME](https://github.com/YOUR_USERNAME)  
Email: your.email@example.com

---

## 🤝 Вклад

Предложения и баг-репорты приветствуются! 
[Создать Issue](https://github.com/YOUR_USERNAME/Inforadar_Pro/issues)

---

**Последнее обновление:** 2025-12-15  
**Версия:** 1.0.0
