import os
from dataclasses import dataclass
from typing import Dict, Any

# =========================
# ОБЩИЕ НАСТРОЙКИ
# =========================

BOOKMAKER_ID = 1
PARSER_LOOP_INTERVAL = int(os.getenv("PARSER_LOOP_INTERVAL", "30"))
REQUEST_TIMEOUT = int(os.getenv("REQUEST_TIMEOUT", "15"))
ANOMALY_WINDOW_MINUTES = int(os.getenv("ANOMALY_WINDOW_MINUTES", "30"))

# =========================
# БАЗА ДАННЫХ
# =========================

MYSQL_HOST = os.getenv("MYSQL_HOST", "127.0.0.1")
MYSQL_PORT = int(os.getenv("MYSQL_PORT", "3307"))
MYSQL_USER = os.getenv("MYSQL_USER", "radar")
MYSQL_PASSWORD = os.getenv("MYSQL_PASSWORD", "ryban8991!")
MYSQL_DB = os.getenv("MYSQL_DB", "inforadar")

# =========================
# ПРОКСИ IPRoyal ISP (Sweden)
# =========================
# !!! ЭТО ОСНОВНАЯ ИСПРАВЛЕННАЯ ЧАСТЬ !!!
# Playwright и curl требуют авторизацию.
# Если указать только host:port → будет 407 Proxy Authentication Required.

PROXY_HOST = "213.137.91.35"
PROXY_PORT = 12323
PROXY_USER = "14ab48c9d85c1"
PROXY_PASS = "5d234f6517"

# Полная строка — для requests, curl, http-клиентов
PROXY_URL = f"http://{PROXY_USER}:{PROXY_PASS}@{PROXY_HOST}:{PROXY_PORT}"

REQUESTS_PROXIES = {
    "http": PROXY_URL,
    "https": PROXY_URL,
}

# Формат для Playwright
PLAYWRIGHT_PROXY: Dict[str, Any] = {
    "server": f"http://{PROXY_HOST}:{PROXY_PORT}",
    "username": PROXY_USER,
    "password": PROXY_PASS,
}

# =========================
# СПОРТЫ И МАРКЕТЫ
# =========================

@dataclass
class MarketConfig:
    code: str
    name: str
    collect: bool = True

@dataclass
class SportConfig:
    code: str
    name: str
    sport_id_22bet: int
    prematch: bool = True
    live: bool = True
    markets: Dict[str, MarketConfig] = None

SPORTS: Dict[str, SportConfig] = {
    "football": SportConfig(
        code="football",
        name="Football",
        sport_id_22bet=1,
        prematch=True,
        live=True,
        markets={
            "1X2": MarketConfig("1X2", "Основной исход"),
            "TOTAL": MarketConfig("TOTAL", "Тотал"),
            "AH": MarketConfig("AH", "Гандикап"),
            "BTTS": MarketConfig("BTTS", "Обе забьют"),
            "DC": MarketConfig("DC", "Double Chance"),
        }
    ),
}

# =========================
# (СТАРЫЕ) API 22bet — пусть остаются
# =========================

BASE_URL = "https://betlines.xyz"

ENDPOINTS = {
    "prematch_by_sport":
        BASE_URL + "/LineFeed/GetEvents?sportId={sport_id}&lng=en&cfview=0&mode=4&count=200&partner=51&getEmpty=true",

    "live_by_sport":
        BASE_URL + "/LiveFeed/GetEvents?sportId={sport_id}&lng=en&cfview=0&mode=4&count=200&partner=51&getEmpty=true",
}

def get_endpoint(name: str, **kwargs: Any) -> str:
    template = ENDPOINTS.get(name)
    if not template:
        raise ValueError(f"Unknown endpoint: {name}")
    return template.format(**kwargs)

# =========================
# PLAYWRIGHT — зеркала 22Bet
# =========================

# рекомендованный порядок — от самых рабочих
PLAYWRIGHT_MIRRORS = [
    "https://22betluck.com",
    "https://22bet-8.com",
    "https://22bet7.com",
    "https://22bet1.com",
    "https://22bet.com",
]

SPORT_LINE_URLS = {
    "football": "/line/football/",
}

PLAYWRIGHT_HEADLESS = True
PLAYWRIGHT_SLOW_MO_MS = 50
PLAYWRIGHT_PAGE_TIMEOUT_MS = 45000
