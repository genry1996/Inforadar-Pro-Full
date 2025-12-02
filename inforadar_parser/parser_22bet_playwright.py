import asyncio
import logging
import time
from datetime import datetime
from typing import Dict, Any, List, Optional
from urllib.parse import urlparse

import pymysql
from playwright.async_api import async_playwright, Browser, Page

from config_22bet import (
    BOOKMAKER_ID,
    PARSER_LOOP_INTERVAL,
    MYSQL_HOST,
    MYSQL_PORT,
    MYSQL_USER,
    MYSQL_PASSWORD,
    MYSQL_DB,
    PROXY_URL,
    SPORTS,
    PLAYWRIGHT_MIRRORS,
    SPORT_LINE_URLS,
    PLAYWRIGHT_HEADLESS,
    PLAYWRIGHT_SLOW_MO_MS,
    PLAYWRIGHT_PAGE_TIMEOUT_MS,
)

# ============ ЛОГИ ============

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s",
)
logger = logging.getLogger("parser_22bet_playwright")


# ============ MySQL ============

def get_db_connection():
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
            return conn
        except Exception as e:
            logger.error(f"Ошибка подключения к MySQL: {e}")
            logger.info("Повторим через 5 секунд...")
            time.sleep(5)


def insert_matches(conn, events: List[Dict[str, Any]], sport_code: str, is_live: bool) -> int:
    if not events:
        return 0

    sql = """
        INSERT INTO matches (bookmaker_id, event_id, sport, league, home_team, away_team, start_time, is_live)
        VALUES (%s,%s,%s,%s,%s,%s,%s,%s)
        ON DUPLICATE KEY UPDATE
            league = VALUES(league),
            home_team = VALUES(home_team),
            away_team = VALUES(away_team),
            start_time = VALUES(start_time),
            is_live = VALUES(is_live)
    """

    cur = conn.cursor()
    count = 0

    for e in events:
        try:
            cur.execute(
                sql,
                (
                    BOOKMAKER_ID,
                    e["event_id"],
                    sport_code,
                    e.get("league"),
                    e.get("home"),
                    e.get("away"),
                    e.get("start_time"),
                    is_live,
                ),
            )
            count += 1
        except Exception as ex:
            logger.error(f"Ошибка вставки матча {e.get('event_id')}: {ex}")

    return count


# ============ ПРОКСИ ДЛЯ PLAYWRIGHT ============

def build_playwright_proxy(proxy_url: str) -> Optional[Dict[str, str]]:
    """
    Превращаем строку вида:
    socks5h://user:pass@host:port
    в dict для Playwright:
    {"server": "socks5://host:port", "username": "user", "password": "pass"}
    """
    if not proxy_url:
        return None

    parsed = urlparse(proxy_url)
    host = parsed.hostname
    port = parsed.port
    user = parsed.username
    password = parsed.password
    scheme = parsed.scheme.replace("h", "")  # "socks5h" -> "socks5"

    server = f"{scheme}://{host}:{port}"
    proxy_dict: Dict[str, str] = {"server": server}

    if user:
        proxy_dict["username"] = user
    if password:
        proxy_dict["password"] = password

    return proxy_dict


# ============ ВЫБОР РАБОЧЕГО ЗЕРКАЛА ============

async def choose_working_mirror(browser: Browser) -> Optional[str]:
    """
    Перебирает PLAYWRIGHT_MIRRORS и возвращает первое зеркало,
    которое успешно отдает главную страницу.
    """
    for base in PLAYWRIGHT_MIRRORS:
        page = await browser.new_page()
        try:
            logger.info(f"Пробуем зеркало: {base}")
            await page.goto(base, wait_until="domcontentloaded", timeout=PLAYWRIGHT_PAGE_TIMEOUT_MS)
            await page.wait_for_timeout(1000)
            # Простая проверка: есть ли вообще какой-то контент
            content = await page.content()
            if "22bet" in content.lower() or "sports" in content.lower():
                logger.info(f"Выбрано зеркало: {base}")
                await page.close()
                return base
        except Exception as e:
            logger.warning(f"Зеркало не работает: {base} → {e}")
        finally:
            try:
                await page.close()
            except Exception:
                pass

    logger.error("Не удалось найти рабочее зеркало 22BET через Playwright.")
    return None


# ============ ПАРСИНГ ЛИНИИ ФУТБОЛА ============

async def parse_football_line(page: Page) -> List[Dict[str, Any]]:
    """
    Примерный парсинг футбольной линии 22BET.
    Ориентируемся на типичную разметку 1xBet/22bet:
    div.c-events__item[data-id]
      span.c-events__team
    """
    events: List[Dict[str, Any]] = []

    # даем странице догрузиться
    await page.wait_for_timeout(3000)

    event_cards = await page.query_selector_all("div.c-events__item")
    logger.info(f"Найдено событий на странице: {len(event_cards)}")

    for card in event_cards:
        try:
            event_id = await card.get_attribute("data-id")

            team_nodes = await card.query_selector_all(".c-events__team")
            teams = [ (await t.inner_text()).strip() for t in team_nodes ]
            if len(teams) >= 2:
                home, away = teams[0], teams[1]
            else:
                continue

            # лига часто в блоке .c-events__liga или похожем
            league_node = await card.query_selector(".c-events__liga, .c-events__champ")
            league = (await league_node.inner_text()).strip() if league_node else ""

            # времени в явном unix-формате обычно нет, поэтому ставим None или текущий
            start_time = None  # можно доработать позже

            events.append(
                {
                    "event_id": event_id,
                    "league": league,
                    "home": home,
                    "away": away,
                    "start_time": start_time,
                }
            )
        except Exception as e:
            logger.error(f"Ошибка парсинга карточки события: {e}")

    return events


async def scrape_sport_line(base_url: str, browser: Browser, sport_code: str) -> List[Dict[str, Any]]:
    """
    Открывает страницу линии нужного вида спорта и парсит события.
    Пока реализовано только для football.
    """
    path = SPORT_LINE_URLS.get(sport_code)
    if not path:
        logger.warning(f"Для спорта {sport_code} не задан SPORT_LINE_URLS — пропускаем.")
        return []

    url = base_url.rstrip("/") + path
    logger.info(f"Открываем линию спорта {sport_code}: {url}")

    page = await browser.new_page()
    try:
        await page.goto(url, wait_until="networkidle", timeout=PLAYWRIGHT_PAGE_TIMEOUT_MS)

        if sport_code == "football":
            events = await parse_football_line(page)
        else:
            events = []

        return events

    except Exception as e:
        logger.error(f"Ошибка при загрузке линии {sport_code}: {e}")
        return []
    finally:
        try:
            await page.close()
        except Exception:
            pass


# ============ ОСНОВНОЙ ЦИКЛ ============

async def main_loop():
    conn = get_db_connection()
    logger.info("=== Старт цикла Playwright-парсера 22BET ===")

    proxy_cfg = build_playwright_proxy(PROXY_URL)
    if proxy_cfg:
        logger.info(f"Используем Playwright прокси: {proxy_cfg['server']}")
    else:
        logger.warning("⚠ PROXY_URL пуст — запускаем браузер БЕЗ прокси (22BET может блочить).")

    from playwright.async_api import async_playwright

    async with async_playwright() as p:
        browser = await p.chromium.launch(
            headless=PLAYWRIGHT_HEADLESS,
            slow_mo=PLAYWRIGHT_SLOW_MO_MS,
            proxy=proxy_cfg,
        )

        base_url = await choose_working_mirror(browser)
        if not base_url:
            logger.error("Нет рабочего зеркала — выходим.")
            await browser.close()
            return

        while True:
            logger.info(f"{datetime.utcnow()} Старт цикла")

            for sport_key, sport_obj in SPORTS.items():
                logger.info(f"--- Спорт: {sport_obj.code} ({sport_obj.name}) [Playwright] ---")

                # пока считаем, что парсим только прематч линию
                events = await scrape_sport_line(base_url, browser, sport_obj.code)
                inserted = insert_matches(conn, events, sport_obj.code, is_live=False)

                logger.info(f"[{sport_obj.code}] Вставлено матчей (prematch/Playwright): {inserted}")

            logger.info(f"Цикл завершён. Спим {PARSER_LOOP_INTERVAL} сек.\n")
            await asyncio.sleep(PARSER_LOOP_INTERVAL)

        await browser.close()


if __name__ == "__main__":
    try:
        asyncio.run(main_loop())
    except KeyboardInterrupt:
        logger.info("Остановлено вручную (Ctrl+C).")
    except Exception as e:
        logger.error(f"Фатальная ошибка Playwright-парсера: {e}")
