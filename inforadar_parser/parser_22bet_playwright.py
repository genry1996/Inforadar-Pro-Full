import os
import time
import logging
from datetime import datetime
from typing import Dict, Any, List, Optional
from urllib.parse import urlparse

import pymysql
import asyncio
from playwright.async_api import async_playwright, Page

from config_22bet import (
    BOOKMAKER_ID,
    PARSER_LOOP_INTERVAL,
    PROXY_URL,
    PLAYWRIGHT_PROXY,        # 👈 добавили
    SPORTS,
    PLAYWRIGHT_MIRRORS,
    SPORT_LINE_URLS,
    PLAYWRIGHT_HEADLESS,
    PLAYWRIGHT_SLOW_MO_MS,
    PLAYWRIGHT_PAGE_TIMEOUT_MS,
)

# ================== ЛОГИ ==================

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s",
)
logger = logging.getLogger("parser_22bet_playwright")

# ================== MySQL ==================
# Внутри контейнера параметры берутся из ENV, которые ты передаёшь в docker-compose.
# Эти значения — только дефолт на случай, если переменных нет.

MYSQL_HOST = os.getenv("MYSQL_HOST", "mysql_inforadar")
MYSQL_PORT = int(os.getenv("MYSQL_PORT", "3306"))
MYSQL_USER = os.getenv("MYSQL_USER", "root")
MYSQL_PASSWORD = os.getenv("MYSQL_PASSWORD", "ryban8991!")
MYSQL_DB = os.getenv("MYSQL_DB", "inforadar")


def get_db_connection():
    """Подключение к MySQL с ретраями."""
    while True:
        try:
            conn = pymysql.connect(
                host=MYSQL_HOST,
                port=MYSQL_PORT,
                user=MYSQL_USER,
                password=MYSQL_PASSWORD,
                database=MYSQL_DB,
                autocommit=True,
                cursorclass=pymysql.cursors.DictCursor,
            )
            logger.info("✅ Успешное подключение к MySQL")
            return conn
        except Exception as e:
            logger.error(f"❌ Ошибка подключения к MySQL: {e}")
            logger.info("Повторим через 5 секунд.")
            time.sleep(5)

# ================== ПРОКСИ ДЛЯ PLAYWRIGHT ==================

def build_playwright_proxy() -> Optional[Dict[str, Any]]:
    """
    Возвращает конфиг прокси для Playwright.

    1) Если в config_22bet задан PLAYWRIGHT_PROXY — используем его как есть.
    2) Иначе, если задан PROXY_URL (строка), парсим её.
    3) Если ничего нет — работаем без прокси.
    """
    # Вариант 1: готовый словарь
    if PLAYWRIGHT_PROXY and PLAYWRIGHT_PROXY.get("server"):
        logger.info(
            f"Используем Playwright прокси (dict): {PLAYWRIGHT_PROXY['server']}"
        )
        return PLAYWRIGHT_PROXY

    # Вариант 2: строка PROXY_URL
    if not PROXY_URL:
        logger.warning("⚠ PROXY_URL пуст — Playwright пойдёт без прокси")
        return None

    parsed = urlparse(PROXY_URL)
    scheme = parsed.scheme or "http"

    # если вдруг будет socks5h → для Chromium лучше http
    if scheme.startswith("socks"):
        scheme_for_browser = "http"
    else:
        scheme_for_browser = scheme

    server = f"{scheme_for_browser}://{parsed.hostname}:{parsed.port}"
    proxy: Dict[str, Any] = {"server": server}

    if parsed.username:
        proxy["username"] = parsed.username
    if parsed.password:
        proxy["password"] = parsed.password

    logger.info(
        f"Используем Playwright прокси (из PROXY_URL): {server}"
        + (f" (user={parsed.username})" if parsed.username else "")
    )
    return proxy

# ================== ВСТАВКА МАТЧЕЙ В БД ==================

def insert_matches(conn, events: List[Dict[str, Any]], sport_code: str):
    """
    Вставка матчей в таблицу matches.
    Ожидаем структуру events:
      {
        "league": str,
        "home": str,
        "away": str,
        "start_time": datetime | None,
      }
    """
    if not events:
        return 0

    sql = """
        INSERT INTO matches (
            bookmaker_id, sport, league,
            home_team, away_team, start_time, is_live
        )
        VALUES (%s,%s,%s,%s,%s,%s,%s)
        ON DUPLICATE KEY UPDATE
            league     = VALUES(league),
            home_team  = VALUES(home_team),
            away_team  = VALUES(away_team),
            start_time = VALUES(start_time),
            is_live    = VALUES(is_live)
    """

    cur = conn.cursor()
    count = 0

    for m in events:
        try:
            cur.execute(
                sql,
                (
                    BOOKMAKER_ID,
                    sport_code,
                    m.get("league", ""),
                    m.get("home", ""),
                    m.get("away", ""),
                    m.get("start_time"),
                    False,  # пока парсим только прематч
                ),
            )
            count += 1
        except Exception as e:
            logger.error(f"Ошибка вставки матча {m}: {e}")

    return count

# ================== ПАРСИНГ СТРАНИЦЫ (пока простая версия) ==================

async def parse_football_page(page: Page) -> List[Dict[str, Any]]:
    """
    Упрощённый парсер линии футбола 22BET.
    Сейчас основная задача — проверить, что мы стабильно проходим на линию.
    Когда будет стабильное зеркало — можно будет допилить селекторы.

    Возвращает список events с полями:
      league, home, away, start_time
    """
    events: List[Dict[str, Any]] = []

    # небольшая пауза, чтобы страница успела дорисоваться
    await page.wait_for_timeout(2000)

    html = await page.content()

    # Если попали на Cloudflare/522 — просто логируем и выходим
    if "Connection timed out" in html or "cf-wrapper" in html:
        logger.warning("Похоже, попали на Cloudflare / 522 страницу, матчей нет.")
        return events

    # Пробуем найти блоки лиг 22BET (по типичным классам 1xBet/22Bet)
    league_blocks = await page.query_selector_all(
        "div.c-events__liga, div.c-events__league"
    )

    if not league_blocks:
        # на случай смены вёрстки просто логируем кусок HTML
        snippet = html[:1000].replace("\n", " ")
        logger.warning(
            "Не нашли блоков лиг по селектору c-events__liga/c-events__league."
        )
        logger.warning(f"Фрагмент HTML: {snippet}")
        return events

    logger.info(f"На странице найдено блоков лиг: {len(league_blocks)}")

    # ⚠ Здесь можно потом аккуратно реализовать разбор каждой лиги и матчей.
    # Пока оставляем как заглушку, чтобы цикл работал и было видно HTML в логах.
    # Когда появится стабильное рабочее зеркало — вместе допилим конкретные селекторы.

    return events

# ================== ВЫБОР РАБОЧЕГО ЗЕРКАЛА ==================

async def find_working_mirror(page: Page) -> Optional[str]:
    """
    Проходит по PLAYWRIGHT_MIRRORS и возвращает первое живое зеркало.
    """
    for base in PLAYWRIGHT_MIRRORS:
        try:
            logger.info(f"Пробуем зеркало: {base}")
            await page.goto(
                base,
                wait_until="domcontentloaded",
                timeout=PLAYWRIGHT_PAGE_TIMEOUT_MS,
            )
            logger.info(f"Зеркало ответило: {page.url}")
            return base
        except Exception as e:
            logger.warning(f"Зеркало не работает: {base} → {e}")
    logger.error("Не удалось найти рабочее зеркало 22BET через Playwright.")
    return None

# ================== ОСНОВНОЙ ЦИКЛ PLAYWRIGHT-ПАРСЕРА ==================

async def run_playwright_loop():
    conn = get_db_connection()

    while True:
        logger.info("=== Старт цикла Playwright-парсера 22BET ===")

        proxy_cfg = build_playwright_proxy()

        try:
            async with async_playwright() as p:
                browser = await p.chromium.launch(
                    headless=PLAYWRIGHT_HEADLESS,
                    slow_mo=PLAYWRIGHT_SLOW_MO_MS,
                    proxy=proxy_cfg,
                )
                page = await browser.new_page()

                # 1. Находим рабочее зеркало
                base = await find_working_mirror(page)
                if not base:
                    await browser.close()
                    logger.error("Нет рабочего зеркала — выходим из цикла итерации.")
                else:
                    # 2. Проходим по видам спорта (сейчас у нас только football)
                    for sport_key, sport_cfg in SPORTS.items():
                        if sport_key not in SPORT_LINE_URLS:
                            logger.warning(
                                f"Для спорта {sport_key} нет URL линии в SPORT_LINE_URLS"
                            )
                            continue

                        line_path = SPORT_LINE_URLS[sport_key]
                        full_url = base.rstrip("/") + line_path

                        logger.info(
                            f"Открываем линию спорта {sport_cfg.name} ({sport_key}): {full_url}"
                        )

                        try:
                            await page.goto(
                                full_url,
                                wait_until="domcontentloaded",
                                timeout=PLAYWRIGHT_PAGE_TIMEOUT_MS,
                            )
                        except Exception as e:
                            logger.error(
                                f"Ошибка загрузки линии {sport_key} по адресу {full_url}: {e}"
                            )
                            continue

                        # 3. Парсим страницу
                        if sport_key == "football":
                            events = await parse_football_page(page)
                        else:
                            events = []

                        # 4. Вставляем в MySQL
                        inserted = insert_matches(conn, events, sport_key)
                        logger.info(
                            f"[{sport_key}] Вставлено матчей (Playwright): {inserted}"
                        )

                await browser.close()

        except Exception as e:
            logger.error(f"Фатальная ошибка Playwright-парсера: {e}")

        logger.info(f"Цикл завершён. Спим {PARSER_LOOP_INTERVAL} сек.\n")
        await asyncio.sleep(PARSER_LOOP_INTERVAL)


def main():
    try:
        asyncio.run(run_playwright_loop())
    except KeyboardInterrupt:
        logger.info("Остановка по Ctrl+C")


if __name__ == "__main__":
    main()
