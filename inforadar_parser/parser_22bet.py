import os
import time
import logging
from datetime import datetime
from typing import Any, Dict, List, Optional

import pymysql
import requests

from config_22bet import (
    BOOKMAKER_ID,
    PARSER_LOOP_INTERVAL,
    REQUEST_TIMEOUT,
    MYSQL_HOST,
    MYSQL_PORT,
    MYSQL_USER,
    MYSQL_PASSWORD,
    MYSQL_DB,
    PROXY_URL,
    SPORTS,
    get_endpoint,
)

# ЛОГИ
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s",
)
logger = logging.getLogger("parser_22bet_v2")

# ПРОКСИ
PROXIES: Optional[Dict[str, str]] = None
if PROXY_URL:
    PROXIES = {"http": PROXY_URL, "https": PROXY_URL}
    logger.info(f"Используем proxy: {PROXY_URL}")
else:
    logger.warning("⚠ PROXY_URL пуст — запросы идут БЕЗ прокси")


# ====================== MySQL ======================

def get_db_connection():
    while True:
        try:
            return pymysql.connect(
                host=MYSQL_HOST,
                port=MYSQL_PORT,
                user=MYSQL_USER,
                password=MYSQL_PASSWORD,
                database=MYSQL_DB,
                autocommit=True,
                cursorclass=pymysql.cursors.DictCursor,
            )
        except Exception as e:
            logger.error(f"MySQL ошибка: {e}")
            time.sleep(5)


# ====================== HTTP ======================

def http_get(url: str, retries: int = 3) -> Optional[Dict[str, Any]]:
    for attempt in range(1, retries + 1):
        try:
            r = requests.get(
                url,
                timeout=REQUEST_TIMEOUT,
                proxies=PROXIES,
                headers={"User-Agent": "Mozilla/5.0"},
            )
            if r.status_code != 200:
                logger.warning(f"[{r.status_code}] Ошибка запроса: {url}")
                continue
            return r.json()

        except Exception as e:
            logger.error(f"Ошибка http_get (попытка {attempt}/{retries}): {e}")
            time.sleep(1)

    return None


# ====================== PARSE ======================

def parse_events(json_data: Dict[str, Any]) -> List[Dict[str, Any]]:
    events = []
    value = json_data.get("Value")

    if not isinstance(value, list):
        return events

    for item in value:
        try:
            event_id = item.get("I")
            league = item.get("L") or ""
            home = item.get("O1") or ""
            away = item.get("O2") or ""
            ts = item.get("S") or 0
            start_time = datetime.utcfromtimestamp(ts) if ts else None

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
            logger.error(f"Ошибка парсинга события: {e}")

    return events


# ====================== INSERT ======================

def insert_matches(conn, events, sport_obj, is_live):
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

    for m in events:
        try:
            cur.execute(
                sql,
                (
                    BOOKMAKER_ID,
                    m["event_id"],
                    sport_obj.code,
                    m["league"],
                    m["home"],
                    m["away"],
                    m["start_time"],
                    is_live,
                ),
            )
            count += 1
        except Exception as e:
            logger.error(f"Ошибка вставки матча {m['event_id']}: {e}")

    return count


# ====================== MAIN LOOP ======================

def run_parser():
    conn = get_db_connection()

    logger.info("=== Старт цикла парсера 22BET ===")

    while True:
        logger.info(f"{datetime.utcnow()} Старт цикла")

        for sport_key, sport_obj in SPORTS.items():
            logger.info(f"--- Спорт: {sport_obj.code} ({sport_obj.name}) ---")

            # prematch
            if sport_obj.prematch:
                prematch_url = get_endpoint(
                    "prematch_by_sport",
                    sport_id=sport_obj.sport_id_22bet
                )
                prematch_json = http_get(prematch_url)
                prematch_events = parse_events(prematch_json) if prematch_json else []
                prematch_count = insert_matches(conn, prematch_events, sport_obj, False)
            else:
                prematch_count = 0

            # live
            if sport_obj.live:
                live_url = get_endpoint(
                    "live_by_sport",
                    sport_id=sport_obj.sport_id_22bet
                )
                live_json = http_get(live_url)
                live_events = parse_events(live_json) if live_json else []
                live_count = insert_matches(conn, live_events, sport_obj, True)
            else:
                live_count = 0

            logger.info(
                f"[{sport_obj.code}] Вставлено: prematch={prematch_count}, live={live_count}"
            )

        logger.info("Цикл завершён. Ждём 30 сек.\n")
        time.sleep(PARSER_LOOP_INTERVAL)


if __name__ == "__main__":
    try:
        run_parser()
    except Exception as e:
        logger.error(f"Фатальная ошибка парсера: {e}")
