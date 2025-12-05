# -*- coding: utf-8 -*-
"""
sync_odds_to_mysql.py — синхронизация The Odds API -> MySQL.
"""

from __future__ import annotations

import os
import sys
from datetime import datetime
from typing import Any, Dict, List

import pymysql

from client import OddsApiClient, OddsApiError


# === Настройки MySQL (подправишь под свои, если нужно) ===
MYSQL_HOST = os.getenv("MYSQL_HOST", "localhost")
MYSQL_PORT = int(os.getenv("MYSQL_PORT", "3306"))  # если проброшен 3307 — поменяешь
MYSQL_USER = os.getenv("MYSQL_USER", "root")
MYSQL_PASSWORD = os.getenv("MYSQL_PASSWORD", "ryban8991!")
MYSQL_DB = os.getenv("MYSQL_DB", "inforadar")


def get_connection():
    return pymysql.connect(
        host=MYSQL_HOST,
        port=MYSQL_PORT,
        user=MYSQL_USER,
        password=MYSQL_PASSWORD,
        database=MYSQL_DB,
        cursorclass=pymysql.cursors.DictCursor,
        autocommit=True,
    )


def parse_iso_dt(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        # "2025-12-06T12:30:00Z" -> datetime
        if value.endswith("Z"):
            value = value.replace("Z", "+00:00")
        dt = datetime.fromisoformat(value)
        # убираем tzinfo, чтобы писать в DATETIME (UTC)
        if dt.tzinfo is not None:
            dt = dt.astimezone(tz=None).replace(tzinfo=None)
        return dt
    except Exception:
        return None


def ensure_tables(conn) -> None:
    with conn.cursor() as cur:
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS oddsapi_sports (
                sport_key   VARCHAR(64) PRIMARY KEY,
                title       VARCHAR(255) NOT NULL,
                active      TINYINT(1) NOT NULL DEFAULT 0,
                group_name  VARCHAR(64) NULL,
                details     VARCHAR(255) NULL,
                created_at  TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at  TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                           ON UPDATE CURRENT_TIMESTAMP
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
            """
        )

        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS oddsapi_events (
                event_id      VARCHAR(64) PRIMARY KEY,
                sport_key     VARCHAR(64) NOT NULL,
                sport_title   VARCHAR(255) NULL,
                commence_time DATETIME NULL,
                home_team     VARCHAR(255) NOT NULL,
                away_team     VARCHAR(255) NOT NULL,
                completed     TINYINT(1) NOT NULL DEFAULT 0,
                last_update   DATETIME NULL,
                created_at    TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at    TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                              ON UPDATE CURRENT_TIMESTAMP,
                INDEX idx_sport_time (sport_key, commence_time)
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
            """
        )

        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS oddsapi_odds (
                id               BIGINT AUTO_INCREMENT PRIMARY KEY,
                event_id         VARCHAR(64) NOT NULL,
                bookmaker_key    VARCHAR(64) NOT NULL,
                bookmaker_title  VARCHAR(255) NOT NULL,
                market_key       VARCHAR(32) NOT NULL,
                outcome_name     VARCHAR(255) NOT NULL,
                outcome_price    DECIMAL(10,3) NOT NULL,
                last_update      DATETIME NULL,
                inserted_at      TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                UNIQUE KEY uniq_odds (
                    event_id, bookmaker_key, market_key, outcome_name
                ),
                INDEX idx_event (event_id)
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
            """
        )


def sync_sports(client: OddsApiClient, conn) -> int:
    data, info = client.get_sports(all_=True)
    print("sync_sports: remaining =", info["remaining"], "used =", info["used"])

    count = 0
    with conn.cursor() as cur:
        for s in data:
            sport_key = s["key"]
            title = s.get("title") or ""
            active = 1 if s.get("active") else 0
            group_name = s.get("group")
            details = s.get("description") or s.get("details")

            cur.execute(
                """
                INSERT INTO oddsapi_sports (sport_key, title, active, group_name, details)
                VALUES (%s, %s, %s, %s, %s)
                ON DUPLICATE KEY UPDATE
                    title = VALUES(title),
                    active = VALUES(active),
                    group_name = VALUES(group_name),
                    details = VALUES(details);
                """,
                (sport_key, title, active, group_name, details),
            )
            count += 1
    return count


def sync_events_and_odds(
    client: OddsApiClient,
    conn,
    sport_key: str,
    markets: str = "h2h",
    regions: str = "eu",
) -> Dict[str, Any]:
    data, info = client.get_odds(
        sport_key=sport_key,
        regions=regions,
        markets=markets,
    )
    print(
        f"sync_events_and_odds({sport_key}): remaining =",
        info["remaining"],
        "used =",
        info["used"],
    )

    events_count = 0
    odds_count = 0

    with conn.cursor() as cur:
        for ev in data:
            event_id = ev["id"]
            sport_title = ev.get("sport_title")
            commence = parse_iso_dt(ev.get("commence_time"))
            home_team = ev.get("home_team") or ""
            away_team = ev.get("away_team") or ""
            completed = 1 if ev.get("completed") else 0
            last_update = parse_iso_dt(ev.get("last_update"))

            # upsert события
            cur.execute(
                """
                INSERT INTO oddsapi_events (
                    event_id, sport_key, sport_title,
                    commence_time, home_team, away_team,
                    completed, last_update
                )
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                ON DUPLICATE KEY UPDATE
                    sport_key = VALUES(sport_key),
                    sport_title = VALUES(sport_title),
                    commence_time = VALUES(commence_time),
                    home_team = VALUES(home_team),
                    away_team = VALUES(away_team),
                    completed = VALUES(completed),
                    last_update = VALUES(last_update);
                """,
                (
                    event_id,
                    sport_key,
                    sport_title,
                    commence,
                    home_team,
                    away_team,
                    completed,
                    last_update,
                ),
            )
            events_count += 1

            # коэффициенты по букмекерам
            for bm in ev.get("bookmakers", []):
                bm_key = bm.get("key") or ""
                bm_title = bm.get("title") or ""
                bm_last_update = parse_iso_dt(bm.get("last_update"))

                for market in bm.get("markets", []):
                    m_key = market.get("key") or ""
                    for outcome in market.get("outcomes", []):
                        name = outcome.get("name") or ""
                        price = outcome.get("price")
                        if price is None:
                            continue
                        cur.execute(
                            """
                            INSERT INTO oddsapi_odds (
                                event_id, bookmaker_key, bookmaker_title,
                                market_key, outcome_name, outcome_price, last_update
                            )
                            VALUES (%s, %s, %s, %s, %s, %s, %s)
                            ON DUPLICATE KEY UPDATE
                                outcome_price = VALUES(outcome_price),
                                last_update = VALUES(last_update);
                            """,
                            (
                                event_id,
                                bm_key,
                                bm_title,
                                m_key,
                                name,
                                price,
                                bm_last_update,
                            ),
                        )
                        odds_count += 1

    return {"events": events_count, "odds": odds_count}


def main(argv: List[str] | None = None) -> int:
    import argparse

    parser = argparse.ArgumentParser(
        description="Синхронизация The Odds API -> MySQL (один спорт)."
    )
    parser.add_argument(
        "--sport",
        default="soccer_epl",
        help="ключ вида спорта (по умолчанию soccer_epl)",
    )
    parser.add_argument(
        "--markets",
        default="h2h",
        help="список рынков, через запятую (например: h2h,spreads,totals)",
    )
    parser.add_argument(
        "--regions",
        default="eu",
        help="регионы БК (eu/us/uk/au)",
    )

    args = parser.parse_args(argv)

    try:
        client = OddsApiClient()
    except OddsApiError as e:
        print("❌ Ошибка клиента:", e, file=sys.stderr)
        return 1

    conn = get_connection()
    ensure_tables(conn)

    sports_synced = sync_sports(client, conn)
    print(f"✅ Обновлено видов спорта: {sports_synced}")

    stats = sync_events_and_odds(
        client,
        conn,
        sport_key=args.sport,
        markets=args.markets,
        regions=args.regions,
    )
    print(
        f"✅ Спорт {args.sport}: событий={stats['events']}, исходов (odds)={stats['odds']}"
    )

    conn.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
