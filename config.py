# ===============================
# 🚀 OddlyOdds Production – CONFIG
# ===============================

# === БАЗА ДАННЫХ ===
MYSQL_HOST = "mysql_inforadar"   # внутри Docker
MYSQL_PORT = 3306
MYSQL_USER = "root"
MYSQL_PASSWORD = "ryban8991!"
MYSQL_DB = "inforadar"

# ========================
# ⚽ СПОРТЫ (пока 22BET)
# ========================
SPORTS = {
    "football": 1,
    "basketball": 3,
    "tennis": 5,
    "esports": 7,
}
SPORT_ID = SPORTS["football"]   # на старте парсим только футбол

BOOKMAKER = "22bet"

# =========================
# 🔗 API зеркала 22BET
# =========================
BETLINE_MIRRORS = [
    f"https://betline.betgamesapi.net/LineFeed/Get1x2_Zip?sports={SPORT_ID}&lng=en",
    f"https://22bet.betgamesapi.net/LineFeed/Get1x2_Zip?sports={SPORT_ID}&lng=en",
]

# =========================
# 🌐 ПРОКСИ
# =========================
PLAYWRIGHT_PROXY = "socks5://api6c4c28f3734e47c5:W5HMlkDB@176.103.231.20:50100"

REQUESTS_PROXIES = {
    "http": PLAYWRIGHT_PROXY,
    "https": PLAYWRIGHT_PROXY,
}

# =========================
# 🎯 ЦЕЛЕВЫЕ РЫНКИ
# =========================
TARGET_MARKETS = {
    "1x2": ["1", "X", "2"],
    "ah": ["AH", "HANDICAP"],
    "ou": ["TOTAL", "OVER_UNDER"],
    "htft": ["HTFT"],
    "halftime": ["1H", "2H"],
}

# =========================
# ⏱️ НАСТРОЙКИ ПАРСЕРА
# =========================
RUN_INTERVAL_SEC = 10            # каждые 10 сек (однопоточно)
REQUEST_TIMEOUT = 15

# =========================
# ⚠️ ПОРОГИ АНОМАЛИЙ
# =========================
ODDS_JUMP_PCT = 15.0             # % резкого падения/роста
LIMIT_CUT_PCT = 30.0             # % порезки лимита
ANOMALY_WINDOW_SEC = 600         # берём историю за 10 минут

# =========================
# 🧭 ВИДЫ АНОМАЛИЙ
# =========================
ANOMALY_TYPES = {
    "odds_drop": "Резкое падение коэффициента",
    "odds_rise": "Резкий рост коэффициента",
    "limit_cut": "Порезка лимита",
    "market_removed": "Снятие рынка",
    "match_removed": "Матч снят с линии",
    "market_added": "Возобновление рынка",
    "line_shift": "Резкое изменение форы/тотала",
}

# =========================
# 🔧 PLAYWRIGHT
# =========================
PLAYWRIGHT_SETTINGS = {
    "headless": True,
    "slow_mo": 50,
    "timeout": 25000,
    "proxy": PLAYWRIGHT_PROXY,
}

# =========================
# 📢 TELEGRAM
# =========================
TELEGRAM_TOKEN = ""
TELEGRAM_CHAT_ID = ""

# =========================
# 📝 ЛОГИРОВАНИЕ
# =========================
LOG_LEVEL = "INFO"
