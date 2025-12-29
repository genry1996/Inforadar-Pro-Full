from flask import Blueprint, render_template, jsonify, request
import os
import pymysql
import logging

logger = logging.getLogger(__name__)
fonbet_bp = Blueprint("fonbet_bp", __name__)

DB_CONFIG = {
    "host": os.getenv("MYSQL_HOST", "localhost"),
    "user": os.getenv("MYSQL_USER", "root"),
    "password": os.getenv("MYSQL_PASSWORD", ""),
    "database": os.getenv("MYSQL_DB", "inforadar"),
    "charset": "utf8mb4",
    "cursorclass": pymysql.cursors.DictCursor,
}

def get_connection():
    try:
        return pymysql.connect(**DB_CONFIG)
    except Exception as e:
        logger.error(f"MySQL connection error (fonbet blueprint): {e}")
        return None

@fonbet_bp.get("/fonbet")
def fonbet_page():
    return render_template("fonbet.html")

@fonbet_bp.get("/fonbet/api/odds")
def fonbet_api_odds():
    sport = (request.args.get("sport", "football") or "football").strip()
    live = int(request.args.get("live", "0"))
    limit = int(request.args.get("limit", "500"))
    limit = max(1, min(limit, 5000))

    conn = get_connection()
    if not conn:
        return jsonify({"error": "Database connection failed"}), 500

    try:
        cur = conn.cursor()
        cur.execute(
            """
            SELECT
              m.league,
              m.team1,
              m.team2,
              DATE_FORMAT(m.start_time, '%%Y-%%m-%%d %%H:%%i:%%s') AS start_time,
              o.market_key,
              o.outcome_key,
              o.odd,
              o.limit_value,
              DATE_FORMAT(o.updated_at, '%%Y-%%m-%%d %%H:%%i:%%s') AS updated_at
            FROM fonbet_matches m
            JOIN fonbet_odds o
              ON o.event_id = m.event_id
            WHERE m.sport=%s AND m.is_live=%s
            ORDER BY o.updated_at DESC
            LIMIT %s
            """,
            (sport, live, limit),
        )
        rows = cur.fetchall()
        cur.close()
        return jsonify(rows)
    finally:
        conn.close()
