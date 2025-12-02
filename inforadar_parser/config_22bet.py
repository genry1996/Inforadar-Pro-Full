import os
from dataclasses import dataclass
from typing import Dict, Any

# ====== ОБЩИЕ ======

BOOKMAKER_ID = 1
PARSER_LOOP_INTERVAL = int(os.getenv("PARSER_LOOP_INTERVAL", "30"))
REQUEST_TIMEOUT = int(os.getenv("REQUEST_TIMEOUT", "15"))
ANOMALY_WINDOW_MINUTES = int(os.getenv("ANOMALY_WINDOW_MINUTES", "30"))

# ====== БАЗА ДАННЫХ ======

MYSQL_HOST = os.getenv("MYSQL_HOST", "127.0.0.1")
MYSQL_PORT = int(os.getenv("MYSQL_PORT", "3307"))
MYSQL_USER = os.getenv("MYSQL_USER", "radar")
MYSQL_PASSWORD = os.getenv("MYSQL_PASSWORD", "ryban8991!")
MYSQL_DB = os.getenv("MYSQL_DB", "inforadar")

# ====== ПРОКСИ (IPROYAL RESIDENTIAL SOCKS5) ======

# ВАЖНО: это та же строка, что ты уже используешь
PROXY_URL = "socks5h://p5wCXOtxz2NYPe7k:ll0NYne2DSrm18Ot@geo.iproyal.com:12321"

# ====== СПОРТЫ ======

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

# ====== (СТАРОЕ) API 22BET — можно не трогать, если понадобится ======

BASE_URL = "https://betlines.xyz"   # сейчас не используется, можно потом удалить

ENDPOINTS = {
    "prematch_by_sport": (
        BASE_URL
        + "/LineFeed/GetEvents?sportId={sport_id}&lng=en&cfview=0&mode=4&count=200&partner=51&getEmpty=true"
    ),
    "live_by_sport": (
        BASE_URL
        + "/LiveFeed/GetEvents?sportId={sport_id}&lng=en&cfview=0&mode=4&count=200&partner=51&getEmpty=true"
    ),
}

def get_endpoint(name: str, **kwargs: Any) -> str:
    template = ENDPOINTS.get(name)
    if not template:
        raise ValueError(f"Unknown endpoint: {name}")
    return template.format(**kwargs)

# ====== PLAYWRIGHT НАСТРОЙКИ ДЛЯ 22BET ======

# Зеркала фронта 22BET — браузер будет по очереди пробовать каждое
PLAYWRIGHT_MIRRORS = [
    "https://22bet.com",
    "https://22bet1.com",
    "https://22bet7.com",
    "https://22bet-7.com",
    "https://22bet-8.com",
]

# URL-линии по видам спорта (относительно домена из PLAYWRIGHT_MIRRORS)
# Эти пути можно править, если вдруг у 22BET поменяется структура
SPORT_LINE_URLS = {
    "football": "/line/football/",   # типичный путь для футбольной линии
}

# Настройки браузера
PLAYWRIGHT_HEADLESS = True          # можно поставить False для дебага
PLAYWRIGHT_SLOW_MO_MS = 50          # замедление, чтобы не рвало всё резко
PLAYWRIGHT_PAGE_TIMEOUT_MS = 30000  # 30 сек на загрузку страницы
