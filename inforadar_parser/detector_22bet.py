# detector_22bet.py
import os
import time
from datetime import datetime, timedelta
from typing import List, Dict, Any, Tuple, Optional

import pymysql
from pymysql.cursors import DictCursor

MYSQL_HOST = os.getenv("MYSQL_HOST", "mysql_inforadar")
MYSQL_PORT = int(os.getenv("MYSQL_PORT", "3306"))
MYSQL_USER = os.getenv("MYSQL_USER", "root")
MYSQL_PASSWORD = os.getenv("MYSQL_PASSWORD", "root")
MYSQL_DB = os.getenv("MYSQL_DB", "inforadar")

BOOKMAKER_ID = int(os.getenv("BOOKMAKER_ID", "1"))

WINDOW_MINUTES = int(os.getenv("ANOMALY_WINDOW_MINUTES", "30"))

ODDS_JUMP_PCT = float(os.getenv("ODDS_JUMP_PCT", "15.0"))    # % изменения
LIMIT_DROP_PCT = float(os.getenv("LIMIT_DROP_PCT", "50.0"))  # % падения лимита


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


def fetch_recent_odds(conn) -> List[Dict[str, Any]]:
    """
    Берём историю коэффициентов за последние WINDOW_MINUTES
    и группируем по match_id + market_id + outcome_code + is_live.
    """
    since_ts = datetime.utcnow() - timedelta(minutes=WINDOW_MINUTES)

    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT
                id,
                match_id,
                market_id,
                bookmaker_id,
                market_type,
                market_param,
                outcome_code,
                odds,
                limit_value,
                is_live,
                collected_at
            FROM odds_history
            WHERE bookmaker_id = %s
              AND collected_at >= %s
            ORDER BY match_id, market_id, outcome_code, collected_at ASC
            """,
            (BOOKMAKER_ID, since_ts)
        )
        rows = cur.fetchall()

    return rows


def group_series(rows: List[Dict[str, Any]]) -> Dict[Tuple[int, int, str, int], List[Dict[str, Any]]]:
    """
    Группируем в серии:
      key = (match_id, market_id, outcome_code, is_live)
    """
    series: Dict[Tuple[int, int, str, int], List[Dict[str, Any]]] = {}
    for r in rows:
        key = (r["match_id"], r["market_id"], r["outcome_code"], r["is_live"])
        series.setdefault(key, []).append(r)
    return series


def insert_anomaly(
    conn,
    match_id: int,
    market_id: int,
    anomaly_type: str,
    before_odd: Optional[float],
    after_odd: Optional[float],
    before_limit: Optional[float],
    after_limit: Optional[float],
    diff_pct: Optional[float],
    window_seconds: int,
    comment: str,
):
    """
    Таблица anomalies (мы уже делали):
      id BIGINT PK,
      match_id INT NOT NULL,
      bookmaker_id INT NULL,
      anomaly_type VARCHAR(100) NOT NULL,

      before_odd DECIMAL(10,3),
      after_odd DECIMAL(10,3),

      before_limit DECIMAL(12,2),
      after_limit DECIMAL(12,2),

      diff_pct DECIMAL(10,2),
      window_seconds INT,

      comment VARCHAR(255),
      occurred_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
      INDEX idx_anom_match (match_id),
      INDEX idx_anom_type (anomaly_type, occurred_at DESC)
    """
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO anomalies (
                match_id, bookmaker_id, anomaly_type,
                before_odd, after_odd,
                before_limit, after_limit,
                diff_pct, window_seconds, comment, occurred_at
            )
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, NOW())
            """,
            (
                match_id,
                BOOKMAKER_ID,
                anomaly_type,
                before_odd,
                after_odd,
                before_limit,
                after_limit,
                diff_pct,
                window_seconds,
                comment,
            )
        )


def analyze_series(conn, key, events: List[Dict[str, Any]]):
    """
    Находим аномалии по одной серии (match+market+исход+live/prematch)
    """
    if len(events) < 2:
        return

    match_id, market_id, outcome_code, is_live = key
    first = events[0]
    last = events[-1]

    before_odd = float(first["odds"])
    after_odd = float(last["odds"])

    before_limit = first["limit_value"]
    after_limit = last["limit_value"]

    if before_limit is not None:
        try:
            before_limit = float(before_limit)
        except Exception:
            before_limit = None
    if after_limit is not None:
        try:
            after_limit = float(after_limit)
        except Exception:
            after_limit = None

    window_seconds = int((last["collected_at"] - first["collected_at"]).total_seconds())

    # ==== 1. Резкое изменение коэффициента (в любую сторону) ====
    if before_odd > 0:
        change_pct = (after_odd - before_odd) / before_odd * 100.0
        if abs(change_pct) >= ODDS_JUMP_PCT:
            direction = "рост" if change_pct > 0 else "падение"
            anomaly_type = "ODDS_JUMP"
            comment = (
                f"{'LIVE' if is_live else 'PREMATCH'} | Исход {outcome_code} | "
                f"{direction} кэфа: {before_odd:.3f} → {after_odd:.3f} ({change_pct:+.1f}%)"
            )
            insert_anomaly(
                conn,
                match_id=match_id,
                market_id=market_id,
                anomaly_type=anomaly_type,
                before_odd=before_odd,
                after_odd=after_odd,
                before_limit=None,
                after_limit=None,
                diff_pct=round(change_pct, 2),
                window_seconds=window_seconds,
                comment=comment,
            )

    # ==== 2. Порезка лимита ====
    if before_limit and after_limit and before_limit > 0:
        limit_change_pct = (after_limit - before_limit) / before_limit * 100.0
        # нас интересует сильное падение лимита
        if limit_change_pct <= -LIMIT_DROP_PCT:
            anomaly_type = "LIMIT_DROP"
            comment = (
                f"{'LIVE' if is_live else 'PREMATCH'} | Исход {outcome_code} | "
                f"падение лимита: {before_limit:.0f} → {after_limit:.0f} ({limit_change_pct:.1f}%)"
            )
            insert_anomaly(
                conn,
                match_id=match_id,
                market_id=market_id,
                anomaly_type=anomaly_type,
                before_odd=None,
                after_odd=None,
                before_limit=before_limit,
                after_limit=after_limit,
                diff_pct=round(limit_change_pct, 2),
                window_seconds=window_seconds,
                comment=comment,
            )


def run_detector_loop():
    while True:
        print("=" * 60)
        print(datetime.now(), "Старт цикла детектора 22BET")
        try:
            with get_connection() as conn:
                rows = fetch_recent_odds(conn)
                series_map = group_series(rows)
                print("Серий для анализа:", len(series_map))

                for key, events in series_map.items():
                    try:
                        analyze_series(conn, key, events)
                    except Exception as e:
                        print("[WARN] Ошибка в analyze_series:", repr(e))

        except Exception as e:
            print("[ERROR] В цикле детектора:", repr(e))

        print("Цикл детектора завершён, ждём 60 секунд\n")
        time.sleep(60)


if __name__ == "__main__":
    run_detector_loop()
