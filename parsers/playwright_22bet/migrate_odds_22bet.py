#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import os
import sys
import pymysql

TABLE = "odds_22bet"

# Columns expected by prematch_football_12h.py (22bet prematch parser)
EXPECTED_COLUMNS = [
    ("event_id", "BIGINT NULL"),
    ("event_name", "VARCHAR(255) NOT NULL"),
    ("home_team", "VARCHAR(255) NULL"),
    ("away_team", "VARCHAR(255) NULL"),
    ("sport", "VARCHAR(50) NULL"),
    ("league", "VARCHAR(255) NULL"),
    ("match_time", "DATETIME NULL"),
    ("market_type", "VARCHAR(32) NULL"),
    ("odd_1", "DECIMAL(10,3) NULL"),
    ("odd_x", "DECIMAL(10,3) NULL"),
    ("odd_2", "DECIMAL(10,3) NULL"),
    ("liquidity_level", "VARCHAR(32) NULL"),
    ("is_suspicious", "TINYINT(1) NOT NULL DEFAULT 0"),
    ("status", "VARCHAR(20) NOT NULL DEFAULT 'prematch'"),
    ("bookmaker", "VARCHAR(32) NOT NULL DEFAULT '22bet'"),
    ("updated_at", "TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP"),
]

def env(name: str, default: str = "") -> str:
    v = os.getenv(name, default)
    return default if v is None else v

def connect():
    host = env("DB_HOST", "127.0.0.1")
    port = int(env("DB_PORT", "3306"))
    user = env("DB_USER", "root")
    password = env("DB_PASSWORD", "")
    db = env("DB_NAME", "inforadar")
    return pymysql.connect(
        host=host,
        port=port,
        user=user,
        password=password,
        database=db,
        charset="utf8mb4",
        autocommit=True,
        cursorclass=pymysql.cursors.DictCursor,
    )

def column_exists(cur, db: str, table: str, col: str) -> bool:
    cur.execute(
        "SELECT 1 FROM information_schema.columns "
        "WHERE table_schema=%s AND table_name=%s AND column_name=%s LIMIT 1",
        (db, table, col),
    )
    return cur.fetchone() is not None

def index_exists(cur, db: str, table: str, index_name: str) -> bool:
    cur.execute(
        "SELECT 1 FROM information_schema.statistics "
        "WHERE table_schema=%s AND table_name=%s AND index_name=%s LIMIT 1",
        (db, table, index_name),
    )
    return cur.fetchone() is not None

def table_exists(cur, db: str, table: str) -> bool:
    cur.execute(
        "SELECT 1 FROM information_schema.tables "
        "WHERE table_schema=%s AND table_name=%s LIMIT 1",
        (db, table),
    )
    return cur.fetchone() is not None

def create_table(cur):
    cur.execute(
        f'''
        CREATE TABLE IF NOT EXISTS {TABLE} (
          id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
          event_id BIGINT NULL,
          event_name VARCHAR(255) NOT NULL,
          home_team VARCHAR(255) NULL,
          away_team VARCHAR(255) NULL,
          sport VARCHAR(50) NULL,
          league VARCHAR(255) NULL,
          match_time DATETIME NULL,
          market_type VARCHAR(32) NULL,
          odd_1 DECIMAL(10,3) NULL,
          odd_x DECIMAL(10,3) NULL,
          odd_2 DECIMAL(10,3) NULL,
          liquidity_level VARCHAR(32) NULL,
          is_suspicious TINYINT(1) NOT NULL DEFAULT 0,
          status VARCHAR(20) NOT NULL DEFAULT 'prematch',
          bookmaker VARCHAR(32) NOT NULL DEFAULT '22bet',
          updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
          PRIMARY KEY (id)
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
        '''
    )

def migrate():
    conn = connect()
    db = conn.db.decode() if isinstance(conn.db, (bytes, bytearray)) else str(conn.db)

    with conn.cursor() as cur:
        if not table_exists(cur, db, TABLE):
            print(f"[+] Table {db}.{TABLE} not found -> creating")
            create_table(cur)

        changed = 0
        for col, ddl in EXPECTED_COLUMNS:
            if not column_exists(cur, db, TABLE, col):
                print(f"[+] ADD COLUMN {col} {ddl}")
                cur.execute(f"ALTER TABLE {TABLE} ADD COLUMN {col} {ddl}")
                changed += 1

        # Unique key for ON DUPLICATE KEY UPDATE (upsert)
        uq = "uq_odds_22bet_event_market_bm"
        if not index_exists(cur, db, TABLE, uq):
            print(f"[+] ADD UNIQUE INDEX {uq} (event_id, market_type, bookmaker)")
            cur.execute(f"ALTER TABLE {TABLE} ADD UNIQUE INDEX {uq} (event_id, market_type, bookmaker)")
            changed += 1

        print(f"[OK] migration done. schema changes: {changed}")

    conn.close()

if __name__ == "__main__":
    try:
        migrate()
    except Exception as e:
        print(f"[ERR] {e}")
        sys.exit(1)
