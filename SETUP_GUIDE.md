# 🎯 BETWATCH EXTENDED SYSTEM v3
## Полная система детектора сигналов + Dashboard

---

## 🚀 ЧТО ВКЛЮЧЕНО

✅ **betwatch_parser.py** — детектор всех сигналов:
- 📉 Sharp Move (падение коэффициента)
- ↔️ Line Shift (сдвиг линии AH/OU)
- 🗑️ Market Removal (рынок исчез)
- ✂️ Odds Squeeze (сжатие котировок)
- 💸 Limit Cut (урезка лимита)
- ⛔ Bet Blocked (заблокирована ставка)

✅ **API Server** (FastAPI) — REST API для получения данных

✅ **Dashboard** (Vue.js) — красивый веб-интерфейс

✅ **MySQL** — сохранение всех сигналов в БД

✅ **Docker Compose** — одна команда для запуска всего

---

## 📋 ФАЙЛЫ

```
D:\Inforadar_Pro\
├── docker-compose.yml           ← Обновленный
├── .env                          ← Переменные окружения
├── inforadar_parser/
│   ├── betwatch_parser.py        ← НОВЫЙ парсер v3 (Extended)
│   ├── Dockerfile.betwatch       ← Docker для парсера
│   └── requirements_betwatch.txt ← Зависимости
├── api_server.py                 ← FastAPI сервер
├── Dockerfile.api                ← Docker для API
└── dashboard.html                ← Веб-интерфейс
```

---

## 🛠️ УСТАНОВКА (5 шагов)

### 1️⃣ Скопируй файлы

```powershell
# Замени файлы в папке
cp betwatch_parser.py D:\Inforadar_Pro\inforadar_parser\
cp betwatch_extended.py D:\Inforadar_Pro\inforadar_parser\
cp requirements_betwatch.txt D:\Inforadar_Pro\inforadar_parser\
cp Dockerfile.betwatch D:\Inforadar_Pro\inforadar_parser\
cp Dockerfile.api D:\Inforadar_Pro\
cp api_server.py D:\Inforadar_Pro\
cp docker-compose.yml D:\Inforadar_Pro\
cp dashboard.html D:\Inforadar_Pro\
```

### 2️⃣ Обновить .env

```bash
# D:\Inforadar_Pro\.env
TELEGRAM_TOKEN=YOUR_BOT_TOKEN
TELEGRAM_CHAT_ID=YOUR_CHAT_ID
MYSQL_HOST=mysql_inforadar
MYSQL_USER=root
MYSQL_PASSWORD=root_password
MYSQL_DB=inforadar_db
```

### 3️⃣ Создать SQL таблицы

```bash
# Подключись к MySQL и выполни:
mysql -h 127.0.0.1 -u root -p inforadar_db < betwatch_sql.sql
```

### 4️⃣ Запустить Docker

```powershell
cd D:\Inforadar_Pro
docker-compose down
docker-compose up -d --build
```

### 5️⃣ Проверить логи

```powershell
docker-compose logs -f playwright_betwatch
```

---

## 📊 ACCESSING THE SYSTEM

### 🌐 Dashboard
```
http://localhost:8000/dashboard.html
```

### 📡 API Endpoints

```bash
# Health check
curl http://localhost:8000/api/health

# Последние сигналы (1 час)
curl "http://localhost:8000/api/signals/recent?hours=1&limit=50"

# Статистика по типам
curl http://localhost:8000/api/signals/stats

# Топ событий
curl http://localhost:8000/api/events/top?limit=20

# Полная сводка для dashboard
curl http://localhost:8000/api/dashboard/summary

# Сигналы конкретного типа
curl "http://localhost:8000/api/signals/by-type/Sharp%20Move"
```

---

## 📊 DATABASE QUERIES

```sql
-- Все сигналы за последний час
SELECT * FROM betwatch_signals 
WHERE timestamp >= DATE_SUB(NOW(), INTERVAL 1 HOUR)
ORDER BY timestamp DESC;

-- Статистика по типам
SELECT signal_type, COUNT(*) as count 
FROM betwatch_signals 
GROUP BY signal_type 
ORDER BY count DESC;

-- Топ событий
SELECT * FROM top_signal_events;

-- Sharp moves сегодня
SELECT event_name, league, COUNT(*) as count
FROM betwatch_signals
WHERE signal_type LIKE '%Sharp%'
AND DATE(timestamp) = CURDATE()
GROUP BY event_name, league
ORDER BY count DESC;
```

---

## ⚙️ КОНФИГУРАЦИЯ

Все параметры в `betwatch_parser.py`:

```python
CONFIG = {
    "pause_sec": 5,              # Проверяем каждые 5 сек
    "koefPercentMin": 8,         # Минимум падения 8%
    "koefPercentMax": 35,        # Максимум падения 35%
    "squeeze_threshold": 0.15,   # Squeeze при 15%+ сжатии
    "limit_cut_percent": 60,     # Limit cut при 60% урезке
    "money_min": 3000,           # Минимум денег €3000
}
```

---

## 📈 WHAT'S NEXT?

Система готова к:
- [ ] Интеграции с 22bet (поиск арбитража)
- [ ] Дополнительных фильтров по лигам
- [ ] Telegram команд для управления
- [ ] Исторических отчетов
- [ ] Экспорта данных в Excel

---

## 🚨 TROUBLESHOOTING

### API not responding
```bash
docker-compose logs betwatch_api
```

### Parser not starting
```bash
docker-compose logs playwright_betwatch
```

### MySQL connection error
```bash
docker-compose logs mysql_inforadar
```

---

## 💬 SUPPORT

Все файлы готовы к использованию. 

Запусти систему и смотри в Dashboard! 🚀

```
🎯 System Status:
- ✅ Parser running
- ✅ API listening (8000)
- ✅ Dashboard ready
- ✅ DB connected
```