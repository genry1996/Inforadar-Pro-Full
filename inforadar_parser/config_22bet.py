# config_22bet.py
import os
from dataclasses import dataclass
from typing import Dict, Any


# ====== ОБЩИЕ НАСТРОЙКИ ======

BOOKMAKER_ID = 1  # условный ID 22BET в таблице bookmakers

# Интервал между циклами сбора (секунды)
PARSER_LOOP_INTERVAL = int(os.getenv("PARSER_LOOP_INTERVAL", "30"))

# Таймаут HTTP/Playwright-запросов (секунды)
REQUEST_TIMEOUT = int(os.getenv("REQUEST_TIMEOUT", "15"))

# Сколько последних минут хранить/анализировать в детекторе
ANOMALY_WINDOW_MINUTES = int(os.getenv("ANOMALY_WINDOW_MINUTES", "30"))


# ====== НАСТРОЙКИ БД ======

# config_22bet.py

MYSQL_HOST = os.getenv("MYSQL_HOST", "127.0.0.1")  # или 'localhost'
MYSQL_PORT = int(os.getenv("MYSQL_PORT", "3307"))  # порт из docker‑compose
MYSQL_USER = os.getenv("MYSQL_USER", "radar")      # как в docker‑compose
MYSQL_PASSWORD = os.getenv("MYSQL_PASSWORD", "ryban8991!")  # пароль
MYSQL_DB = os.getenv("MYSQL_DB", "inforadar")

# ====== ПРОКСИ ДЛЯ PLAYWRIGHT ======
# Пример: http://user:pass@ip:port  или  socks5://user:pass@ip:port

PROXY_URL = os.getenv("PROXY_URL", "")  # если пусто — без прокси


# ====== СПОРТЫ И МАРКЕТЫ ======
# Здесь мы описываем, какие виды спорта и какие маркеты собираем.
# Ты можешь дополнять это под себя.

@dataclass
class MarketConfig:
    code: str          # наш внутренний код ('1X2', 'TOTAL', 'AH', 'BTTS', 'DC')
    name: str          # человекочитаемое имя
    collect: bool = True


@dataclass
class SportConfig:
    code: str              # наш внутренний код ('football', 'basketball', ...)
    name: str              # для отображения
    sport_id_22bet: int    # ID спорта у 22BET (нужно посмотреть в DevTools)
    prematch: bool = True
    live: bool = True
    markets: Dict[str, MarketConfig] = None


SPORTS: Dict[str, SportConfig] = {
    "football": SportConfig(
        code="football",
        name="Football",
        sport_id_22bet=1,   # TODO: глянуть реальный ID у 22BET
        prematch=True,
        live=True,
        markets={
            "1X2": MarketConfig(code="1X2", name="Основной исход"),
            "TOTAL": MarketConfig(code="TOTAL", name="Тоталы (Over/Under)"),
            "AH": MarketConfig(code="AH", name="Азиатский гандикап"),
            "BTTS": MarketConfig(code="BTTS", name="Обе забьют"),
            "DC": MarketConfig(code="DC", name="Double Chance"),
        }
    ),
    "basketball": SportConfig(
        code="basketball",
        name="Basketball",
        sport_id_22bet=3,   # TODO: реальный ID
        prematch=True,
        live=True,
        markets={
            "1X2": MarketConfig(code="1X2", name="Победа"),
            "TOTAL": MarketConfig(code="TOTAL", name="Тотал очков"),
            "AH": MarketConfig(code="AH", name="Фора / AH"),
        }
    ),
    # Можешь добавить tennis, hockey, esports и т.д.
}


# ====== ЭНДПОИНТЫ 22BET (ШАБЛОН) ======
# ВАЖНО: эти URL нужно проверить в DevTools на real 22BET / зеркале.
# Обычно у них есть LineFeed API: /LineFeed/GetEvents, /LineFeed/GetLiveEvents и т.п.

BASE_URL = "https://22bet.com"  # либо зеркало

ENDPOINTS = {
    # Прематч по спорту (примерный шаблон)
    "prematch_by_sport": (
        BASE_URL
        + "/LineFeed/GetEvents?sportId={sport_id}&lng=en&cfview=0&count=200&mode=4"
        "&country=132&partner=51&getEmpty=true"
    ),

    # Лайв по спорту (примерный шаблон)
    "live_by_sport": (
        BASE_URL
        + "/LiveFeed/GetEvents?sportId={sport_id}&lng=en&cfview=0&count=200&mode=4"
        "&country=132&partner=51&getEmpty=true"
    ),
}


def get_endpoint(name: str, **kwargs: Any) -> str:
    """
    Вспомогательная функция: подставляем параметры в шаблон URL.
    """
    template = ENDPOINTS.get(name)
    if not template:
        raise ValueError(f"Unknown endpoint name: {name}")
    return template.format(**kwargs)
