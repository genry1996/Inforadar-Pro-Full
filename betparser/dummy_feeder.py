import os
import logging
from datetime import datetime, timedelta
from typing import Optional

import pymysql

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s"
)
logger = logging.getLogger(__name__)

MYSQL_HOST = os.getenv("MYSQL_HOST", "mysql_inforadar")
MYSQL_PORT = int(os.getenv("MYSQL_PORT", "3306"))
MYSQL_USER = os.getenv("MYSQL_USER", "root")
MYSQL_PASSWORD = os.getenv("MYSQL_PASSWORD", "ryban8991!")
MYSQL_DB = os.getenv("MYSQL_DB", "inforadar")


def get_conn():
    return pymysql.connect(
        host=MYSQL_HOST,
        port=MYSQL_PORT,
        user=MYSQL_USER,
        password=MYSQL_PASSWORD,
        database=MYSQL_DB,
        cursorclass=pymysql.cursors.DictCursor,
        autocommit=True,
    )


def ensure_bookmaker(conn) -> int:
    """
    Создаём тестового букмекера (или берём существующего).
    """
    with conn.cursor() as cur:
        cur.execute("SELECT id FROM bookmakers WHERE name = %s LIMIT 1", ("TestBook",))
        row = cur.fetchone()
        if row:
            return row["id"]

        cur.execute(
            "INSERT INTO bookmakers (name) VALUES (%s)",
            ("TestBook",)
        )
        return cur.lastrowid


def ensure_match(conn) -> int:
    """
    Создаём тестовый матч (или берём существующий).
    """
    with conn.cursor() as cur:
        cur.execute("""
            SELECT id FROM matches
            WHERE sport = %s AND league = %s AND home_team = %s AND away_team = %s
            LIMIT 1
        """, ("Football", "Test League", "Team A", "Team B"))
        row = cur.fetchone()
        if row:
            return row["id"]

        # start_time и другие поля если есть — пусть заполнятся дефолтами/NULL
        cur.execute("""
            INSERT INTO matches (sport, league, home_team, away_team)
            VALUES (%s, %s, %s, %s)
        """, ("Football", "Test League", "Team A", "Team B"))
        return cur.lastrowid


def insert_history_row(
    conn,
    match_id: int,
    bookmaker_id: int,
    market: str,
    outcome: str,
    line: Optional[float],
    odd: Optional[float],
    limit_value: Optional[float],
    is_live: int,
    created_at: datetime,
):
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO odds_history (
                match_id,
                bookmaker_id,
                market,
                outcome,
                line,
                odd,
                limit_value,
                is_live,
                created_at
            )
            VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)
            """,
            (
                match_id,
                bookmaker_id,
                market,
                outcome,
                line,
                odd,
                limit_value,
                is_live,
                created_at.strftime("%Y-%m-%d %H:%M:%S"),
            ),
        )


def main():
    conn = get_conn()
    try:
        bm_id = ensure_bookmaker(conn)
        match_id = ensure_match(conn)

        now = datetime.utcnow()

        logger.info("Создаём тестовые записи в odds_history...")

        # 1) Падение коэффициента: 2.10 -> 1.60 за 10 минут
        insert_history_row(
            conn,
            match_id,
            bm_id,
            market="AH",
            outcome="Home -6",
            line=-6.0,
            odd=2.10,
            limit_value=5000,
            is_live=0,
            created_at=now - timedelta(minutes=20),
        )
        insert_history_row(
            conn,
            match_id,
            bm_id,
            market="AH",
            outcome="Home -6",
            line=-6.0,
            odd=1.60,
            limit_value=5000,
            is_live=0,
            created_at=now - timedelta(minutes=5),
        )

        # 2) Рост коэффициента: 1.80 -> 2.30
        insert_history_row(
            conn,
            match_id,
            bm_id,
            market="OU",
            outcome="Over 2.5",
            line=2.5,
            odd=1.80,
            limit_value=3000,
            is_live=0,
            created_at=now - timedelta(minutes=25),
        )
        insert_history_row(
            conn,
            match_id,
            bm_id,
            market="OU",
            outcome="Over 2.5",
            line=2.5,
            odd=2.30,
            limit_value=3000,
            is_live=0,
            created_at=now - timedelta(minutes=3),
        )

        # 3) Порезка лимита: 10000 -> 500
        insert_history_row(
            conn,
            match_id,
            bm_id,
            market="ML",
            outcome="Home",
            line=None,
            odd=1.90,
            limit_value=10000,
            is_live=0,
            created_at=now - timedelta(minutes=18),
        )
        insert_history_row(
            conn,
            match_id,
            bm_id,
            market="ML",
            outcome="Home",
            line=None,
            odd=1.85,
            limit_value=500,
            is_live=0,
            created_at=now - timedelta(minutes=2),
        )

        logger.info("Тестовые данные записаны в odds_history")

    finally:
        conn.close()


if __name__ == "__main__":
    main()
