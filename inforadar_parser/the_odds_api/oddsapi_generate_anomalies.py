# -*- coding: utf-8 -*-
"""
oddsapi_generate_anomalies.py

Берём данные из oddsapi_events / oddsapi_odds
и создаём записи в таблице anomalies.

Логика:
  - для каждого события + исхода (event_id, outcome_name)
  - смотрим коэффициенты у разных БК (market_key = 'h2h')
  - если разброс между max и min >= 15% -> пишем аномалию ODDS_SPREAD
"""

import os
from collections import defaultdict
from decimal import Decimal
from typing import List, Dict, Any

import pymysql

# ========= НАСТРОЙКИ ПОДКЛЮЧЕНИЯ К БАЗЕ =========
# ВАЖНО: скрипт запускается с Windows-хоста, поэтому:
#   - host = 127.0.0.1
#   - port = 3307  (в docker-compose у тебя 3307:3306)
MYSQL_HOST = os.getenv("MYSQL_HOST", "127.0.0.1")
MYSQL_PORT = int(os.getenv("MYSQL_PORT", "3307"))
MYSQL_USER = os.getenv("MYSQL_USER", "root")
MYSQL_PASSWORD = os.getenv("MYSQL_PASSWORD", "ryban8991!")
MYSQL_DB = os.getenv("MYSQL_DB", "inforadar")

# Порог аномалии по разбросу коэффициентов (в %)
ODDS_SPREAD_PCT = float(os.getenv("ODDS_SPREAD_PCT", "15.0"))


def get_connection():
    print(f"🔗 Подключаемся к MySQL {MYSQL_HOST}:{MYSQL_PORT} DB={MYSQL_DB}")
    try:
        conn = pymysql.connect(
            host=MYSQL_HOST,
            port=MYSQL_PORT,
            user=MYSQL_USER,
            password=MYSQL_PASSWORD,
            database=MYSQL_DB,
            cursorclass=pymysql.cursors.DictCursor,
            autocommit=True,
        )
        return conn
    except Exception as e:
        print(f"❌ Не удалось подключиться к MySQL: {repr(e)}")
        return None


def fetch_epl_odds(conn) -> List[Dict[str, Any]]:
    """
    Забираем все H2H-коэффы по EPL из oddsapi_*
    """
    sql = """
        SELECT
            e.event_id,
            e.sport_key,
            e.sport_title,
            e.commence_time,
            e.home_team,
            e.away_team,

            o.bookmaker_key,
            o.bookmaker_title,
            o.market_key,
            o.outcome_name,
            o.outcome_price,
            o.last_update
        FROM oddsapi_events e
        JOIN oddsapi_odds o
          ON o.event_id = e.event_id
        WHERE e.sport_key = 'soccer_epl'
          AND o.market_key = 'h2h'
    """
    with conn.cursor() as cur:
        cur.execute(sql)
        rows = cur.fetchall()
    print(f"🔎 Загружено строк odds: {len(rows)}")
    return rows


def calc_pct_change(high: Decimal, low: Decimal) -> float:
    """
    high -> low, возвращаем (%), обычно отрицательный.
    """
    if high <= 0 or low <= 0:
        return 0.0
    pct = (low / high - Decimal("1.0")) * Decimal("100.0")
    return float(pct)


def detect_spread_anomalies(rows: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """
    Аномалия: большой разброс по тот же самый исход между БК.
    Группируем по (event_id, outcome_name).
    """
    grouped: Dict[tuple, List[Dict[str, Any]]] = defaultdict(list)

    for r in rows:
        key = (r["event_id"], r["outcome_name"])
        grouped[key].append(r)

    anomalies: List[Dict[str, Any]] = []

    for (event_id, outcome_name), items in grouped.items():
        if len(items) < 2:
            continue  # нужен хотя бы 2 БК

        # сортировка по цене
        items_sorted = sorted(items, key=lambda x: Decimal(str(x["outcome_price"])))
        low = items_sorted[0]
        high = items_sorted[-1]

        high_price = Decimal(str(high["outcome_price"]))
        low_price = Decimal(str(low["outcome_price"]))

        diff_pct = calc_pct_change(high_price, low_price)

        if abs(diff_pct) >= ODDS_SPREAD_PCT:
            comment = (
                f"{outcome_name}: {high['bookmaker_title']} {high_price} vs "
                f"{low['bookmaker_title']} {low_price}"
            )
            anomalies.append(
                {
                    # пока кладём в match_id = 1, чтобы не было NULL
                    "match_id": 1,
                    "anomaly_type": "ODDS_SPREAD",
                    "before_value": f"{high_price}",
                    "after_value": f"{low_price}",
                    "diff_pct": round(diff_pct, 2),
                    "comment": comment[:240],
                }
            )

    print(f"⚙️  Найдено аномалий по разбросу: {len(anomalies)}")
    return anomalies


def insert_anomalies(conn, anomalies: List[Dict[str, Any]]):
    if not anomalies:
        print("ℹ️  Нет аномалий для вставки.")
        return

    sql = """
        INSERT INTO anomalies
            (match_id, anomaly_type, before_value, after_value, diff_pct, comment)
        VALUES
            (%s, %s, %s, %s, %s, %s)
    """
    with conn.cursor() as cur:
        for a in anomalies:
            cur.execute(
                sql,
                (
                    a["match_id"],
                    a["anomaly_type"],
                    a["before_value"],
                    a["after_value"],
                    a["diff_pct"],
                    a["comment"],
                ),
            )
    print(f"✅ Вставлено записей в anomalies: {len(anomalies)}")


def main():
    print("=== oddsapi_generate_anomalies.py start ===")
    conn = get_connection()
    if not conn:
        return

    try:
        rows = fetch_epl_odds(conn)
        anoms = detect_spread_anomalies(rows)
        insert_anomalies(conn, anoms)
    finally:
        conn.close()
        print("=== oddsapi_generate_anomalies.py done ===")


if __name__ == "__main__":
    main()
