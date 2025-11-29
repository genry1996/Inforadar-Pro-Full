# parser_22bet.py
import json
import time
from datetime import datetime
from typing import Dict, Any, List, Optional, Tuple

import pymysql
from pymysql.cursors import DictCursor
from playwright.sync_api import sync_playwright

from config_22bet import (
    MYSQL_HOST, MYSQL_PORT, MYSQL_USER, MYSQL_PASSWORD, MYSQL_DB,
    PROXY_URL, PARSER_LOOP_INTERVAL, REQUEST_TIMEOUT,
    SPORTS, BOOKMAKER_ID, get_endpoint
)


# ============ Подключение к БД ============

def get_connection():
    return pymysql.connect(
        host=MYSQL_HOST,
        port=MYSQL_PORT,
        user=MYSQL_USER,
        password=MYSQL_PASSWORD,
        database=MYSQL_DB,
        cursorclass=DictCursor,
        autocommit=True,
    )


# ==== ВСПОМОГАТЕЛЬНЫЕ ВСТАВКИ/АПДЕЙТЫ В БД ====

def upsert_match(conn, sport: str, league: str,
                 home_team: str, away_team: str,
                 start_time: Optional[datetime],
                 is_live: bool) -> int:
    """
    Обеспечиваем, что матч есть в таблице matches.
    Возвращаем match_id.
    Ожидается, что у тебя таблица matches примерно такая:
      id, sport, league, home_team, away_team, start_time, status, created_at, updated_at, ...
    """

    status = "live" if is_live else "upcoming"

    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT id FROM matches
            WHERE sport = %s AND league = %s
              AND home_team = %s AND away_team = %s
              AND (start_time IS NULL OR start_time = %s)
            LIMIT 1
            """,
            (sport, league, home_team, away_team, start_time)
        )
        row = cur.fetchone()

        if row:
            match_id = row["id"]
            cur.execute(
                """
                UPDATE matches
                SET status = %s, updated_at = NOW()
                WHERE id = %s
                """,
                (status, match_id)
            )
            return match_id

        cur.execute(
            """
            INSERT INTO matches (sport, league, home_team, away_team, start_time, status, created_at, updated_at)
            VALUES (%s, %s, %s, %s, %s, %s, NOW(), NOW())
            """,
            (sport, league, home_team, away_team, start_time, status)
        )
        return cur.lastrowid


def get_or_create_market(conn, match_id: int, market_type: str, market_param: str) -> int:
    """
    Таблица markets:
      id, match_id, market_type, market_param, created_at, updated_at
    """
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT id FROM markets
            WHERE match_id = %s AND market_type = %s AND market_param = %s
            LIMIT 1
            """,
            (match_id, market_type, market_param)
        )
        row = cur.fetchone()
        if row:
            return row["id"]

        cur.execute(
            """
            INSERT INTO markets (match_id, market_type, market_param, created_at, updated_at)
            VALUES (%s, %s, %s, NOW(), NOW())
            """,
            (match_id, market_type, market_param)
        )
        return cur.lastrowid


def insert_odds_history(
    conn,
    match_id: int,
    market_id: int,
    market_type: str,
    market_param: str,
    outcome_code: str,
    odds: float,
    limit: Optional[float],
    is_live: bool,
) -> None:
    """
    Таблица odds_history (примерная структура):
      id BIGINT PK,
      match_id INT,
      market_id INT,
      bookmaker_id INT,
      market_type VARCHAR(50),
      market_param VARCHAR(50),
      outcome_code VARCHAR(50),
      odds DECIMAL(10,3),
      limit_value DECIMAL(12,2) NULL,
      is_live TINYINT(1),
      collected_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
      INDEX (match_id, market_type, collected_at)
    """
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO odds_history (
                match_id, market_id, bookmaker_id,
                market_type, market_param, outcome_code,
                odds, limit_value, is_live, collected_at
            )
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, NOW())
            """,
            (
                match_id,
                market_id,
                BOOKMAKER_ID,
                market_type,
                market_param,
                outcome_code,
                odds,
                limit,
                1 if is_live else 0,
            )
        )


# ====== PARSER 22BET JSON ======
# ВАЖНО: структуру ответа надо посмотреть в DevTools.
# Здесь — шаблон, который ожидает, что придёт список events с полями
# (нужно подправить под реальный JSON).

def parse_22bet_event(raw_event: Dict[str, Any]) -> Dict[str, Any]:
    """
    Приводим raw JSON по 22BET к единому виду.
    Вернём:
      {
        "league": str,
        "home_team": str,
        "away_team": str,
        "start_time": datetime | None,
        "markets": List[{
            "market_type": "1X2"/"TOTAL"/"AH"/"BTTS"/"DC",
            "market_param": "2.5" / "-1.5" / "" ...
            "outcomes": [
                {"code": "1", "odds": 1.85, "limit": None},
                {"code": "X", "odds": 3.5, "limit": None},
                {"code": "2", "odds": 4.2, "limit": None},
            ]
        }]
      }
    """

    # TODO: подправь согласно реальным ключам
    league = raw_event.get("L", "") or raw_event.get("LeagueName", "")
    home_team = raw_event.get("O1", "") or raw_event.get("HomeTeam", "")
    away_team = raw_event.get("O2", "") or raw_event.get("AwayTeam", "")

    # Время начала:
    # часто у 22BET есть поле StartTime/StartDate или Unix timestamp
    start_time = None
    ts = raw_event.get("StartTime") or raw_event.get("S")
    if ts:
        try:
            # если timestamp в секундах:
            start_time = datetime.fromtimestamp(int(ts))
        except Exception:
            start_time = None

    # Маркеты и исходы надо достать из raw_event["Markets"] или похожего
    markets: List[Dict[str, Any]] = []

    # Шаблон: предполагаем, что raw_event["Markets"] = список словарей
    for m in raw_event.get("Markets", []):
        # Примеры: m["MType"], m["Name"], m["P"], m["O"] и т.п.
        market_type = m.get("Type") or m.get("MType") or ""
        market_param = str(m.get("P", ""))

        # Маппинг в наши коды
        # TODO: подправить под реальные типы 22BET
        if "1x2" in market_type.lower():
            internal_type = "1X2"
        elif "total" in market_type.lower() or "over/under" in market_type.lower():
            internal_type = "TOTAL"
        elif "handicap" in market_type.lower() or "ah" in market_type.lower():
            internal_type = "AH"
        elif "both teams to score" in market_type.lower() or "btts" in market_type.lower():
            internal_type = "BTTS"
        elif "double chance" in market_type.lower():
            internal_type = "DC"
        else:
            # Игнорируем неинтересные маркеты
            continue

        outcomes = []
        for o in m.get("Outcomes", []):
            code = o.get("Code") or o.get("OutcomeCode") or o.get("Name")
            odds = float(o.get("Odds") or o.get("K") or 0)
            limit = o.get("Limit")
            if limit is not None:
                try:
                    limit = float(limit)
                except Exception:
                    limit = None
            outcomes.append(
                {
                    "code": str(code),
                    "odds": odds,
                    "limit": limit,
                }
            )

        if outcomes:
            markets.append(
                {
                    "market_type": internal_type,
                    "market_param": market_param or "",
                    "outcomes": outcomes,
                }
            )

    return {
        "league": league,
        "home_team": home_team,
        "away_team": away_team,
        "start_time": start_time,
        "markets": markets,
    }


# ====== ЗАПРОСЫ В 22BET ЧЕРЕЗ PLAYWRIGHT ======

def fetch_events_for_sport(context, endpoint_name: str, sport_id_22bet: int) -> List[Dict[str, Any]]:
    url = get_endpoint(endpoint_name, sport_id=sport_id_22bet)
    resp = context.request.get(url, timeout=REQUEST_TIMEOUT * 1000)
    if resp.status != 200:
        print(f"[WARN] {endpoint_name} {url} -> HTTP {resp.status}")
        return []
    try:
        data = resp.json()
    except Exception:
        text = resp.text()
        print(f"[WARN] Can't parse JSON from {url}, first 500 chars:\n{text[:500]}")
        return []

    # TODO: подправить путь до списка событий (Events, Value, etc.)
    events = data.get("Events") or data.get("Value") or []
    if not isinstance(events, list):
        return []
    return events


def run_parser_loop():
    while True:
        print("=" * 60)
        print(datetime.now(), "Старт цикла парсера 22BET (prematch + live)")
        try:
            with get_connection() as conn, sync_playwright() as p:
                browser = p.chromium.launch(headless=True)
                context_kwargs = {}
                if PROXY_URL:
                    context_kwargs["proxy"] = {"server": PROXY_URL}

                context = browser.new_context(**context_kwargs)

                for sport_code, sport_cfg in SPORTS.items():
                    print(f"\n--- Спорт: {sport_cfg.name} ({sport_code}) ---")

                    # Прематч
                    if sport_cfg.prematch:
                        raw_events = fetch_events_for_sport(
                            context,
                            "prematch_by_sport",
                            sport_cfg.sport_id_22bet
                        )
                        process_events_batch(
                            conn, raw_events, sport_code, is_live=False
                        )

                    # Лайв
                    if sport_cfg.live:
                        raw_events_live = fetch_events_for_sport(
                            context,
                            "live_by_sport",
                            sport_cfg.sport_id_22bet
                        )
                        process_events_batch(
                            conn, raw_events_live, sport_code, is_live=True
                        )

                context.close()
                browser.close()

        except Exception as e:
            print("[ERROR] В цикле парсера:", repr(e))

        print("Цикл завершён, спим", PARSER_LOOP_INTERVAL, "секунд")
        time.sleep(PARSER_LOOP_INTERVAL)


def process_events_batch(conn, raw_events: List[Dict[str, Any]], sport_code: str, is_live: bool):
    print(f"Обнаружено событий: {len(raw_events)} | is_live={is_live}")
    for raw in raw_events:
        try:
            parsed = parse_22bet_event(raw)
            league = parsed["league"]
            home_team = parsed["home_team"]
            away_team = parsed["away_team"]
            start_time = parsed["start_time"]
            markets = parsed["markets"]

            if not home_team or not away_team:
                continue

            match_id = upsert_match(
                conn,
                sport=sport_code,
                league=league,
                home_team=home_team,
                away_team=away_team,
                start_time=start_time,
                is_live=is_live,
            )

            for m in markets:
                market_type = m["market_type"]
                market_param = m["market_param"]
                market_id = get_or_create_market(conn, match_id, market_type, market_param)

                for out in m["outcomes"]:
                    outcome_code = out["code"]
                    odds = float(out["odds"])
                    limit = out["limit"]
                    insert_odds_history(
                        conn,
                        match_id=match_id,
                        market_id=market_id,
                        market_type=market_type,
                        market_param=market_param,
                        outcome_code=outcome_code,
                        odds=odds,
                        limit=limit,
                        is_live=is_live,
                    )

        except Exception as e:
            print("[WARN] Ошибка обработки события:", repr(e))


if __name__ == "__main__":
    run_parser_loop()
